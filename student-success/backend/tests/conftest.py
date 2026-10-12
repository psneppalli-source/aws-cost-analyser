import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ssp-test-")
os.environ.update(AUTH_MODE="local-demo", STORAGE="sqlite", SQLITE_PATH=str(Path(TMP) / "test.db"),
                  LOCAL_DEMO_SECRET="test-secret-not-for-production", INSIGHT_CACHE_SECONDS="0")
os.environ.pop("AWS_LAMBDA_FUNCTION_NAME", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    return seed.run(with_accounts=True)


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def tokens(client, seeded):
    out = {}
    for p in seed.PERSONAS:
        r = client.post("/api/auth/local/login", json={"username": p["username"]})
        assert r.status_code == 200, r.text
        out[p["username"]] = r.json()["token"]
    return out


@pytest.fixture
def h(tokens):
    import hashlib

    def headers(user: str, body: bytes | None = None) -> dict:
        hd = {"X-App-Authorization": f"Bearer {tokens[user]}"}
        if body is not None:
            hd["x-amz-content-sha256"] = hashlib.sha256(body).hexdigest()
            hd["Content-Type"] = "application/json"
        return hd
    return headers


@pytest.fixture
def call(client, h):
    """call(user, method, path, json=None) with the payload hash header the frontend sends."""
    import json as _json

    def _call(user, method, path, json=None, raw=None, headers=None):
        body = raw if raw is not None else (_json.dumps(json).encode() if json is not None else None)
        hd = h(user, body if method in ("POST", "PUT", "PATCH") else None)
        if method in ("POST", "PUT", "PATCH") and body is None:
            body = b""
            import hashlib
            hd["x-amz-content-sha256"] = hashlib.sha256(b"").hexdigest()
        hd.update(headers or {})
        return client.request(method, path, content=body, headers=hd)
    return _call


def first(dept: str, year: int) -> str:
    return f"{dept}{(2026 - year + 1) % 100:02d}001"
