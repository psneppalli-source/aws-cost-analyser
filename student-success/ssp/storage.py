"""Storage behind two small interfaces, so the same code runs on AWS and locally.

Blob store  : S3 (aws) or a directory (local). Holds canonical records,
              staged uploads, score snapshots and scoring-config versions.
Item table  : DynamoDB (aws) or SQLite (local). Holds interventions, upload
              history, scoring runs, the audit log and the write lock.

Writes that change records go through `lock()`, a conditional DynamoDB item
with an expiry, so two concurrent uploads can never interleave.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import settings


class Conflict(Exception):
    """Another writer holds the lock, or a conditional write failed."""


# --------------------------------------------------------------------------- blobs
class LocalBlobs:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid key")
        return p

    def get(self, key: str) -> bytes | None:
        p = self._p(key)
        return p.read_bytes() if p.exists() else None

    def put(self, key: str, data: bytes) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic on POSIX: readers never see a half-written file

    def list(self, prefix: str) -> list[str]:
        base = self.root
        return sorted(str(p.relative_to(base)) for p in base.rglob("*")
                      if p.is_file() and str(p.relative_to(base)).startswith(prefix) and not p.name.endswith(".tmp"))

    def delete(self, key: str) -> None:
        p = self._p(key)
        if p.exists():
            p.unlink()


def _retry_config():
    from botocore.config import Config
    # Adaptive retries absorb throttling on the free-tier 5 WCU table during bulk work.
    return Config(retries={"max_attempts": 10, "mode": "adaptive"})


class S3Blobs:
    def __init__(self, bucket: str):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=settings.AWS_REGION, config=_retry_config())

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")

    def list(self, prefix: str) -> list[str]:
        keys, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            keys += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return sorted(keys)
            token = r["NextContinuationToken"]

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=key)


# --------------------------------------------------------------------------- items
class LocalTable:
    """DynamoDB-shaped table on SQLite: items keyed by (pk, sk) with a JSON body."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS items (pk TEXT, sk TEXT, body TEXT, expires REAL, PRIMARY KEY (pk, sk))")

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            c.execute("PRAGMA journal_mode=WAL")
            self._local.c = c
        return c

    def put(self, pk: str, sk: str, item: dict) -> None:
        self._conn().execute("INSERT OR REPLACE INTO items VALUES (?,?,?,NULL)", (pk, sk, json.dumps(item)))

    def get(self, pk: str, sk: str) -> dict | None:
        r = self._conn().execute("SELECT body FROM items WHERE pk=? AND sk=?", (pk, sk)).fetchone()
        return json.loads(r[0]) if r else None

    def query(self, pk: str, sk_prefix: str = "", newest_first: bool = False, limit: int | None = None) -> list[dict]:
        sql = "SELECT body FROM items WHERE pk=? AND sk LIKE ? ORDER BY sk " + ("DESC" if newest_first else "ASC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [json.loads(r[0]) for r in self._conn().execute(sql, (pk, sk_prefix.replace("%", "") + "%"))]

    def delete(self, pk: str, sk: str) -> None:
        self._conn().execute("DELETE FROM items WHERE pk=? AND sk=?", (pk, sk))

    def acquire(self, pk: str, sk: str, owner: str, ttl: float) -> bool:
        c = self._conn()
        now = time.time()
        c.execute("BEGIN IMMEDIATE")
        try:
            r = c.execute("SELECT expires FROM items WHERE pk=? AND sk=?", (pk, sk)).fetchone()
            if r and r[0] and r[0] > now:
                c.execute("ROLLBACK")
                return False
            c.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?)", (pk, sk, json.dumps({"owner": owner}), now + ttl))
            c.execute("COMMIT")
            return True
        except Exception:
            c.execute("ROLLBACK")
            raise

    def release(self, pk: str, sk: str, owner: str) -> None:
        r = self.get(pk, sk)
        if r and r.get("owner") == owner:
            self.delete(pk, sk)


class DynamoTable:
    """Items stored as {pk, sk, body(JSON string), expires}; bodies stay plain JSON (no Decimal)."""

    def __init__(self, name: str):
        import boto3
        self.t = boto3.resource("dynamodb", region_name=settings.AWS_REGION, config=_retry_config()).Table(name)

    def put(self, pk: str, sk: str, item: dict) -> None:
        self.t.put_item(Item={"pk": pk, "sk": sk, "body": json.dumps(item)})

    def get(self, pk: str, sk: str) -> dict | None:
        r = self.t.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return json.loads(r["body"]) if r and "body" in r else None

    def query(self, pk: str, sk_prefix: str = "", newest_first: bool = False, limit: int | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Key
        cond = Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix) if sk_prefix else Key("pk").eq(pk)
        out, kw = [], {"KeyConditionExpression": cond, "ScanIndexForward": not newest_first}
        while True:
            if limit:
                kw["Limit"] = limit - len(out)
            r = self.t.query(**kw)
            out += [json.loads(i["body"]) for i in r["Items"] if "body" in i]
            if "LastEvaluatedKey" not in r or (limit and len(out) >= limit):
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def delete(self, pk: str, sk: str) -> None:
        self.t.delete_item(Key={"pk": pk, "sk": sk})

    def acquire(self, pk: str, sk: str, owner: str, ttl: float) -> bool:
        from botocore.exceptions import ClientError
        now = int(time.time())
        try:
            self.t.put_item(
                Item={"pk": pk, "sk": sk, "owner": owner, "expires": now + int(ttl)},
                ConditionExpression="attribute_not_exists(pk) OR expires < :now",
                ExpressionAttributeValues={":now": now},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def release(self, pk: str, sk: str, owner: str) -> None:
        from botocore.exceptions import ClientError
        try:
            self.t.delete_item(Key={"pk": pk, "sk": sk}, ConditionExpression="#o = :o",
                               ExpressionAttributeNames={"#o": "owner"}, ExpressionAttributeValues={":o": owner})
        except ClientError:
            pass


# --------------------------------------------------------------------------- facade
class Store:
    def __init__(self, blobs, table):
        self.blobs = blobs
        self.table = table

    def get_json(self, key: str):
        raw = self.blobs.get(key)
        if raw is None:
            return None
        if key.endswith(".gz"):
            raw = gzip.decompress(raw)
        return json.loads(raw)

    def put_json(self, key: str, obj) -> None:
        raw = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()
        self.blobs.put(key, gzip.compress(raw) if key.endswith(".gz") else raw)

    @contextlib.contextmanager
    def lock(self, name: str = "records", ttl: float = 120):
        owner = uuid.uuid4().hex
        if not self.table.acquire("LOCK", name, owner, ttl):
            raise Conflict("Another upload or recalculation is in progress. Try again in a minute.")
        try:
            yield
        finally:
            self.table.release("LOCK", name, owner)


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        if settings.MODE == "aws":
            _store = Store(S3Blobs(settings.DATA_BUCKET), DynamoTable(settings.TABLE_NAME))
        else:
            _store = Store(LocalBlobs(settings.LOCAL_DIR / "blobs"), LocalTable(settings.LOCAL_DIR / "items.db"))
    return _store


def set_store(store: Store | None) -> None:
    """Used by tests and the seeding script to point at a specific store."""
    global _store
    _store = store
