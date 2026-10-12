"""Single-table storage with two interchangeable backends.

DynamoTable : Amazon DynamoDB (provisioned capacity, two GSIs). Used in AWS.
SqliteTable : the same key model on SQLite for local development and tests,
              including conditional writes, all-or-nothing transactions,
              GSIs and cursor pagination, so behaviour matches DynamoDB.

Items are dicts with string keys `pk`/`sk` and optional `gsi1pk`/`gsi1sk`,
`gsi2pk`/`gsi2sk`. Writes take an optional condition tree built with `C`.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

INDEXES = {"gsi1": ("gsi1pk", "gsi1sk"), "gsi2": ("gsi2pk", "gsi2sk")}


class ConditionFailed(Exception):
    """A conditional write or transaction check did not hold (e.g. a version conflict)."""


# --------------------------------------------------------------------------- conditions
@dataclass(frozen=True)
class C:
    kind: str
    name: str = ""
    value: Any = None
    parts: tuple = ()

    @staticmethod
    def not_exists() -> "C":
        return C("not_exists")

    @staticmethod
    def exists() -> "C":
        return C("exists")

    @staticmethod
    def eq(name: str, value) -> "C":
        return C("eq", name, value)

    @staticmethod
    def lt(name: str, value) -> "C":
        return C("lt", name, value)

    @staticmethod
    def version(n: int) -> "C":
        return C("eq", "version", n)

    @staticmethod
    def any(*parts: "C") -> "C":
        return C("or", parts=parts)

    @staticmethod
    def all(*parts: "C") -> "C":
        return C("and", parts=parts)

    def holds(self, item: dict | None) -> bool:
        k = self.kind
        if k == "not_exists":
            return item is None
        if k == "exists":
            return item is not None
        if k == "eq":
            return item is not None and item.get(self.name) == self.value
        if k == "lt":
            return item is not None and self.name in item and item[self.name] < self.value
        if k == "or":
            return any(p.holds(item) for p in self.parts)
        if k == "and":
            return all(p.holds(item) for p in self.parts)
        raise ValueError(k)

    def to_boto(self):
        from boto3.dynamodb.conditions import Attr
        k = self.kind
        if k == "not_exists":
            return Attr("pk").not_exists()
        if k == "exists":
            return Attr("pk").exists()
        if k == "eq":
            return Attr(self.name).eq(_to_dynamo(self.value))
        if k == "lt":
            return Attr(self.name).lt(_to_dynamo(self.value))
        if k in ("or", "and"):
            out = self.parts[0].to_boto()
            for p in self.parts[1:]:
                out = (out | p.to_boto()) if k == "or" else (out & p.to_boto())
            return out
        raise ValueError(k)


@dataclass
class Put:
    item: dict
    cond: C | None = None


@dataclass
class Delete:
    pk: str
    sk: str
    cond: C | None = None


@dataclass
class Check:
    pk: str
    sk: str
    cond: C = field(default_factory=C.exists)


def encode_cursor(key: dict | None) -> str | None:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode() if key else None


def decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except Exception as exc:
        raise ValueError("Invalid pagination cursor") from exc


def _to_dynamo(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_dynamo(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [_to_dynamo(x) for x in v]
    return v


def _from_dynamo(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _from_dynamo(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_from_dynamo(x) for x in v]
    return v


# --------------------------------------------------------------------------- SQLite
class SqliteTable:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS items (pk TEXT NOT NULL, sk TEXT NOT NULL,
            gsi1pk TEXT, gsi1sk TEXT, gsi2pk TEXT, gsi2sk TEXT, body TEXT NOT NULL, PRIMARY KEY (pk, sk))""")
        self._db.execute("CREATE INDEX IF NOT EXISTS i1 ON items (gsi1pk, gsi1sk, pk, sk)")
        self._db.execute("CREATE INDEX IF NOT EXISTS i2 ON items (gsi2pk, gsi2sk, pk, sk)")

    def _get(self, pk, sk):
        r = self._db.execute("SELECT body FROM items WHERE pk=? AND sk=?", (pk, sk)).fetchone()
        return json.loads(r[0]) if r else None

    def _write(self, item):
        self._db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?)",
                         (item["pk"], item["sk"], item.get("gsi1pk"), item.get("gsi1sk"),
                          item.get("gsi2pk"), item.get("gsi2sk"), json.dumps(item)))

    def get(self, pk: str, sk: str) -> dict | None:
        with self._lock:
            return self._get(pk, sk)

    def batch_get(self, keys: list[tuple[str, str]]) -> list[dict]:
        with self._lock:
            return [i for i in (self._get(pk, sk) for pk, sk in keys) if i]

    def put(self, item: dict, cond: C | None = None) -> None:
        self.transact([Put(item, cond)])

    def delete(self, pk: str, sk: str, cond: C | None = None) -> None:
        self.transact([Delete(pk, sk, cond)])

    def transact(self, ops: list) -> None:
        if len(ops) > 100:
            raise ValueError("A transaction can hold at most 100 operations")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for op in ops:
                    pk, sk = (op.item["pk"], op.item["sk"]) if isinstance(op, Put) else (op.pk, op.sk)
                    if op.cond is not None and not op.cond.holds(self._get(pk, sk)):
                        raise ConditionFailed(f"Condition failed for {pk} / {sk}")
                for op in ops:
                    if isinstance(op, Put):
                        self._write({k: v for k, v in op.item.items() if v is not None})
                    elif isinstance(op, Delete):
                        self._db.execute("DELETE FROM items WHERE pk=? AND sk=?", (op.pk, op.sk))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def query(self, pk: str, sk_prefix: str = "", index: str | None = None, limit: int | None = None,
              cursor: str | None = None, reverse: bool = False) -> tuple[list[dict], str | None]:
        pcol, scol = INDEXES[index] if index else ("pk", "sk")
        order = "DESC" if reverse else "ASC"
        sql = f"SELECT body, {scol}, pk, sk FROM items WHERE {pcol}=? AND {scol} >= ? AND {scol} < ?"
        args: list = [pk, sk_prefix, sk_prefix + "￿"]
        start = decode_cursor(cursor)
        if start:
            cmp = "<" if reverse else ">"
            sql += f" AND ({scol}, pk, sk) {cmp} (?, ?, ?)"
            args += [start["s"], start["pk"], start["sk"]]
        sql += f" ORDER BY {scol} {order}, pk {order}, sk {order}"
        if limit:
            sql += " LIMIT ?"
            args.append(limit + 1)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        nxt = None
        if limit and len(rows) > limit:
            rows = rows[:limit]
            b, s, p, k = rows[-1]
            nxt = encode_cursor({"s": s, "pk": p, "sk": k})
        return [json.loads(r[0]) for r in rows], nxt

    def wipe(self, pk_prefix: str) -> int:
        with self._lock:
            return self._db.execute("DELETE FROM items WHERE pk LIKE ?", (pk_prefix.replace("%", "") + "%",)).rowcount


# --------------------------------------------------------------------------- DynamoDB
class DynamoTable:
    def __init__(self, name: str, region: str, endpoint_url: str | None = None):
        import boto3
        from botocore.config import Config
        cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"}, connect_timeout=3, read_timeout=8)
        self.name = name
        self.client = boto3.client("dynamodb", region_name=region, endpoint_url=endpoint_url, config=cfg)
        self.table = boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint_url, config=cfg).Table(name)
        from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
        self._ser, self._de = TypeSerializer(), TypeDeserializer()

    def get(self, pk: str, sk: str) -> dict | None:
        r = self.table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return _from_dynamo(r) if r else None

    def batch_get(self, keys: list[tuple[str, str]]) -> list[dict]:
        out = []
        for i in range(0, len(keys), 100):
            req = {self.name: {"Keys": [{"pk": pk, "sk": sk} for pk, sk in dict.fromkeys(keys[i:i + 100])]}}
            res = self.table.meta.client.batch_get_item(RequestItems=req)
            out += res["Responses"].get(self.name, [])
            while res.get("UnprocessedKeys"):
                res = self.table.meta.client.batch_get_item(RequestItems=res["UnprocessedKeys"])
                out += res["Responses"].get(self.name, [])
        return [_from_dynamo(i) for i in out]

    def put(self, item: dict, cond: C | None = None) -> None:
        from botocore.exceptions import ClientError
        kw = {"Item": _to_dynamo(item)}
        if cond is not None:
            kw["ConditionExpression"] = cond.to_boto()
        try:
            self.table.put_item(**kw)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConditionFailed(str(e)) from e
            raise

    def delete(self, pk: str, sk: str, cond: C | None = None) -> None:
        from botocore.exceptions import ClientError
        kw = {"Key": {"pk": pk, "sk": sk}}
        if cond is not None:
            kw["ConditionExpression"] = cond.to_boto()
        try:
            self.table.delete_item(**kw)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConditionFailed(str(e)) from e
            raise

    def _expr(self, cond: C) -> dict:
        from boto3.dynamodb.conditions import ConditionExpressionBuilder
        b = ConditionExpressionBuilder().build_expression(cond.to_boto())
        out = {"ConditionExpression": b.condition_expression, "ExpressionAttributeNames": b.attribute_name_placeholders}
        if b.attribute_value_placeholders:
            out["ExpressionAttributeValues"] = {k: self._ser.serialize(v) for k, v in b.attribute_value_placeholders.items()}
        return out

    def transact(self, ops: list) -> None:
        from botocore.exceptions import ClientError
        items = []
        for op in ops:
            if isinstance(op, Put):
                d = {"TableName": self.name, "Item": {k: self._ser.serialize(v) for k, v in _to_dynamo(op.item).items()}}
                if op.cond is not None:
                    d.update(self._expr(op.cond))
                items.append({"Put": d})
            elif isinstance(op, Delete):
                d = {"TableName": self.name, "Key": {"pk": {"S": op.pk}, "sk": {"S": op.sk}}}
                if op.cond is not None:
                    d.update(self._expr(op.cond))
                items.append({"Delete": d})
            else:
                items.append({"ConditionCheck": {"TableName": self.name, "Key": {"pk": {"S": op.pk}, "sk": {"S": op.sk}},
                                                 **self._expr(op.cond)}})
        try:
            self.client.transact_write_items(TransactItems=items)
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                raise ConditionFailed(str(e)) from e
            raise

    def query(self, pk: str, sk_prefix: str = "", index: str | None = None, limit: int | None = None,
              cursor: str | None = None, reverse: bool = False) -> tuple[list[dict], str | None]:
        from boto3.dynamodb.conditions import Key
        pcol, scol = INDEXES[index] if index else ("pk", "sk")
        cond = Key(pcol).eq(pk) & Key(scol).begins_with(sk_prefix) if sk_prefix else Key(pcol).eq(pk)
        kw = {"KeyConditionExpression": cond, "ScanIndexForward": not reverse}
        if index:
            kw["IndexName"] = index
        start = decode_cursor(cursor)
        if start:
            kw["ExclusiveStartKey"] = start
        out = []
        while True:
            if limit:
                kw["Limit"] = limit - len(out)
            r = self.table.query(**kw)
            out += r["Items"]
            last = r.get("LastEvaluatedKey")
            if not last or (limit and len(out) >= limit):
                return [_from_dynamo(i) for i in out], encode_cursor(_from_dynamo(last)) if last else None
            kw["ExclusiveStartKey"] = last
