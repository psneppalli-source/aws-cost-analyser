"""Authentication.

cognito    : verifies the Cognito ID token (RS256 signature against the pool's
             published keys, issuer, expiry, token_use and audience/client).
local-demo : HS256 tokens issued by /api/auth/local/login for development only.
             Refused inside AWS Lambda (see settings.py).

Token transport: behind CloudFront with Origin Access Control the
`Authorization` header carries CloudFront's SigV4 signature, so the
application token travels in `X-App-Authorization: Bearer <token>`.
Locally `Authorization` is also accepted.

The token only identifies the user (sub). Roles, departments, mentees,
subjects and student identity come from server-side assignments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.request

from . import db
from .policy import Principal
from .settings import ROOT, settings

_SHA256_DI = bytes.fromhex("3031300d060960864801650304020105000420")
_jwks: dict = {"keys": {}, "at": 0.0}
_principal_cache: dict = {}
PRINCIPAL_TTL = 15


class AuthError(Exception):
    pass


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def rsa_sha256_verify(n: int, e: int, msg: bytes, sig: bytes) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_DI + hashlib.sha256(msg).digest()
    return hmac.compare_digest(em, b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t)


def issuer() -> str:
    s = settings()
    return f"https://cognito-idp.{s.region}.amazonaws.com/{s.cognito_pool_id}"


def _keys(force=False) -> dict:
    if force or not _jwks["keys"] or time.time() - _jwks["at"] > 3600:
        with urllib.request.urlopen(issuer() + "/.well-known/jwks.json", timeout=4) as r:
            data = json.load(r)
        _jwks["keys"] = {k["kid"]: (int.from_bytes(b64d(k["n"]), "big"), int.from_bytes(b64d(k["e"]), "big"))
                         for k in data["keys"] if k.get("kty") == "RSA"}
        _jwks["at"] = time.time()
    return _jwks["keys"]


def verify_cognito(token: str) -> dict:
    try:
        h, p, s = token.split(".")
        header, claims = json.loads(b64d(h)), json.loads(b64d(p))
    except Exception as exc:
        raise AuthError("Malformed token") from exc
    if header.get("alg") != "RS256":
        raise AuthError("Unexpected token algorithm")
    keys = _keys()
    if header.get("kid") not in keys:
        keys = _keys(force=True)
    if header.get("kid") not in keys:
        raise AuthError("Unknown signing key")
    if not rsa_sha256_verify(*keys[header["kid"]], f"{h}.{p}".encode(), b64d(s)):
        raise AuthError("Invalid token signature")
    return check_claims(claims)


def check_claims(claims: dict) -> dict:
    s = settings()
    if claims.get("iss") != issuer():
        raise AuthError("Wrong token issuer")
    if claims.get("token_use") != "id":
        raise AuthError("Wrong token use")
    if claims.get("aud") != s.cognito_client_id:
        raise AuthError("Token was issued for a different application")
    if claims.get("exp", 0) < time.time():
        raise AuthError("Session expired")
    return claims


# --------------------------------------------------------------------------- local demo
def _local_secret() -> bytes:
    s = settings()
    if s.local_secret:
        return s.local_secret.encode()
    p = ROOT / ".local" / "demo-jwt.secret"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
        os.chmod(p, 0o600)
    return p.read_text().encode()


def issue_local(sub: str, ttl: int = 8 * 3600) -> str:
    if settings().auth_mode != "local-demo":
        raise AuthError("Local demo sign-in is disabled")
    now = int(time.time())
    h = b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64e(json.dumps({"sub": sub, "iat": now, "exp": now + ttl, "token_use": "id", "iss": "local-demo"}).encode())
    sig = b64e(hmac.new(_local_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def verify_local(token: str) -> dict:
    try:
        h, p, s = token.split(".")
    except ValueError as exc:
        raise AuthError("Malformed token") from exc
    if json.loads(b64d(h)).get("alg") != "HS256":
        raise AuthError("Unexpected token algorithm")
    good = b64e(hmac.new(_local_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(good, s):
        raise AuthError("Invalid token signature")
    claims = json.loads(b64d(p))
    if claims.get("exp", 0) < time.time():
        raise AuthError("Session expired")
    return claims


# --------------------------------------------------------------------------- principal
def token_from_headers(headers) -> str:
    raw = headers.get("x-app-authorization") or ""
    if not raw and settings().auth_mode == "local-demo":
        raw = headers.get("authorization") or ""
    if not raw.lower().startswith("bearer "):
        raise AuthError("Sign in required")
    return raw[7:].strip()


def load_principal(sub: str) -> Principal:
    hit = _principal_cache.get(sub)
    if hit and time.time() - hit[0] < PRINCIPAL_TTL:
        return hit[1]
    items, _ = db.table().query(f"USER#{sub}")
    prof = next((i for i in items if i["sk"] == "PROFILE"), None)
    if not prof or prof.get("status") != "active":
        raise AuthError("Your account is not active on this platform. Contact the system administrator.")
    p = Principal(sub=sub, username=prof["username"], display_name=prof.get("display_name", prof["username"]))
    for i in items:
        sk = i["sk"]
        if sk.startswith("ROLE#"):
            p.roles.add(i["role"])
            if i["role"] == "hod" and i.get("department"):
                p.departments.add(i["department"])
            if i["role"] == "student" and i.get("student_id"):
                p.student = (i["dataset"], i["student_id"])
        elif sk.startswith("MENTEE#"):
            p.mentees.add((i["dataset"], i["student_id"]))
        elif sk.startswith("SUBJ#"):
            p.subjects.add((i["department"], int(i["year"]), i["subject"]))
    if "mentor" not in p.roles:
        p.mentees, p.subjects = set(), set()
    _principal_cache[sub] = (time.time(), p)
    return p


def clear_principal_cache(sub: str | None = None) -> None:
    if sub:
        _principal_cache.pop(sub, None)
    else:
        _principal_cache.clear()


def authenticate(headers) -> Principal:
    token = token_from_headers(headers)
    claims = verify_cognito(token) if settings().auth_mode == "cognito" else verify_local(token)
    return load_principal(claims["sub"])
