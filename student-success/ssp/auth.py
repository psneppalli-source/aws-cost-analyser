"""Authentication and the user directory.

AWS mode : users live in a Cognito user pool. The browser signs in through
           Cognito's hosted login (OAuth code + PKCE, optional TOTP MFA) and
           sends the ID token as a Bearer token. We verify its RS256 signature
           against the pool's published keys, plus issuer, audience, expiry
           and token use, then read the role from `cognito:groups`.
Local    : users live in the item table with scrypt password hashes; login
           issues an HS256 token carrying the same claims.

Either way the result is a `Principal`, and every authorisation decision is
made server-side from it (see access.py). Nothing the browser says about its
own role is trusted.
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
from dataclasses import dataclass

from . import settings
from .storage import get_store

ROLES = ["admin", "hod", "mentor", "placement", "student"]
ROLE_LABELS = {"admin": "Administrator", "hod": "Head of Department", "mentor": "Faculty / Mentor",
               "placement": "Placement Officer", "student": "Student"}


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    username: str
    name: str
    role: str
    dept: str = ""
    student_id: str = ""

    def as_dict(self) -> dict:
        return {"username": self.username, "name": self.name, "role": self.role,
                "role_label": ROLE_LABELS[self.role], "dept": self.dept, "student_id": self.student_id}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _role_from_groups(groups: list[str]) -> str:
    for r in ROLES:  # most privileged first, if a user is (wrongly) in several groups
        if r in groups:
            return r
    raise AuthError("Your account has no role assigned. Ask an administrator to add you to a group.")


def _principal(claims: dict) -> Principal:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return Principal(
        username=claims.get("cognito:username") or claims.get("username") or claims["sub"],
        name=claims.get("name") or claims.get("email") or claims.get("cognito:username", ""),
        role=_role_from_groups(groups),
        dept=claims.get("custom:dept", "") or "",
        student_id=claims.get("custom:student_id", "") or "",
    )


# --------------------------------------------------------------------------- Cognito (RS256)
_jwks: dict = {"keys": {}, "fetched": 0.0}
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _issuer() -> str:
    return f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com/{settings.USER_POOL_ID}"


def _load_jwks(force: bool = False) -> dict:
    if force or not _jwks["keys"] or time.time() - _jwks["fetched"] > 3600:
        with urllib.request.urlopen(_issuer() + "/.well-known/jwks.json", timeout=5) as r:
            keys = json.load(r)["keys"]
        _jwks["keys"] = {k["kid"]: (int.from_bytes(_b64d(k["n"]), "big"), int.from_bytes(_b64d(k["e"]), "big"))
                         for k in keys if k.get("kty") == "RSA"}
        _jwks["fetched"] = time.time()
    return _jwks["keys"]


def rsa_sha256_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (JWT 'RS256'), per RFC 8017 section 8.2.2."""
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_DIGESTINFO + hashlib.sha256(message).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_cognito(token: str) -> Principal:
    try:
        h64, p64, s64 = token.split(".")
        header, claims = json.loads(_b64d(h64)), json.loads(_b64d(p64))
    except Exception as exc:
        raise AuthError("Malformed token") from exc
    if header.get("alg") != "RS256":
        raise AuthError("Unexpected token algorithm")
    keys = _load_jwks()
    if header.get("kid") not in keys:
        keys = _load_jwks(force=True)  # keys rotated
    if header.get("kid") not in keys:
        raise AuthError("Unknown signing key")
    n, e = keys[header["kid"]]
    if not rsa_sha256_verify(n, e, f"{h64}.{p64}".encode(), _b64d(s64)):
        raise AuthError("Invalid token signature")
    now = time.time()
    if claims.get("iss") != _issuer():
        raise AuthError("Wrong token issuer")
    if claims.get("token_use") != "id" or claims.get("aud") != settings.USER_POOL_CLIENT_ID:
        raise AuthError("Wrong token audience")
    if claims.get("exp", 0) < now - 30:
        raise AuthError("Session expired. Sign in again.")
    return _principal(claims)


# --------------------------------------------------------------------------- local (HS256)
def _local_secret() -> bytes:
    if settings.LOCAL_JWT_SECRET:
        return settings.LOCAL_JWT_SECRET.encode()
    p = settings.LOCAL_DIR / "jwt.secret"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
        os.chmod(p, 0o600)
    return p.read_text().encode()


def issue_local_token(user: dict) -> str:
    now = int(time.time())
    claims = {"cognito:username": user["username"], "name": user["name"], "cognito:groups": [user["role"]],
              "custom:dept": user.get("dept", ""), "custom:student_id": user.get("student_id", ""),
              "iat": now, "exp": now + settings.SESSION_HOURS * 3600, "token_use": "id"}
    h = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = _b64e(json.dumps(claims).encode())
    sig = _b64e(hmac.new(_local_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def verify_local(token: str) -> Principal:
    try:
        h, p, s = token.split(".")
    except ValueError as exc:
        raise AuthError("Malformed token") from exc
    expected = _b64e(hmac.new(_local_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, s):
        raise AuthError("Invalid token signature")
    claims = json.loads(_b64d(p))
    if claims.get("exp", 0) < time.time():
        raise AuthError("Session expired. Sign in again.")
    user = get_store().table.get("USER", claims["cognito:username"])
    if not user or not user.get("active", True):
        raise AuthError("Account disabled")
    return _principal(claims)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return h.hex(), salt.hex()


def local_login(username: str, password: str) -> tuple[str, Principal]:
    t = get_store().table
    user = t.get("USER", username.strip().lower())
    now = time.time()
    if user and user.get("locked_until", 0) > now:
        raise AuthError("Too many failed attempts. Try again in 15 minutes.")
    ok = False
    if user and user.get("active", True):
        h, _ = hash_password(password, bytes.fromhex(user["salt"]))
        ok = hmac.compare_digest(h, user["pw_hash"])
    else:
        hash_password(password)  # same work either way, so timing doesn't reveal valid usernames
    if not ok:
        if user:
            user["failed"] = user.get("failed", 0) + 1
            if user["failed"] >= settings.MAX_FAILED_LOGINS:
                user["locked_until"] = now + settings.LOCKOUT_MINUTES * 60
                user["failed"] = 0
            t.put("USER", user["username"], user)
        raise AuthError("Incorrect username or password.")
    user["failed"] = 0
    user["locked_until"] = 0
    t.put("USER", user["username"], user)
    token = issue_local_token(user)
    return token, _principal(json.loads(_b64d(token.split(".")[1])))


def authenticate(headers: dict) -> Principal:
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AuthError("Sign in required.")
    token = auth[7:].strip()
    return verify_cognito(token) if settings.MODE == "aws" else verify_local(token)


# --------------------------------------------------------------------------- user directory
class Directory:
    """Create, list and disable users in whichever identity store is active."""

    def list(self) -> list[dict]:
        if settings.MODE == "aws":
            return self._cognito_list()
        return [{k: u.get(k, "") for k in ("username", "name", "role", "dept", "student_id")} | {"active": u.get("active", True)}
                for u in get_store().table.query("USER")]

    def create(self, username: str, name: str, role: str, dept: str = "", student_id: str = "",
               password: str | None = None, email: str = "") -> dict:
        if role not in ROLES:
            raise ValueError(f"Unknown role {role}")
        username = username.strip().lower()
        if settings.MODE == "aws":
            return self._cognito_create(username, name, role, dept, student_id, password, email)
        if not password:
            raise ValueError("A password is required in local mode")
        h, s = hash_password(password)
        user = {"username": username, "name": name, "role": role, "dept": dept, "student_id": student_id,
                "pw_hash": h, "salt": s, "active": True, "failed": 0, "locked_until": 0}
        get_store().table.put("USER", username, user)
        return {"username": username, "name": name, "role": role, "dept": dept, "student_id": student_id, "active": True}

    def set_active(self, username: str, active: bool) -> None:
        if settings.MODE == "aws":
            c = self._cognito()
            (c.admin_enable_user if active else c.admin_disable_user)(UserPoolId=settings.USER_POOL_ID, Username=username)
            if not active:
                c.admin_user_global_sign_out(UserPoolId=settings.USER_POOL_ID, Username=username)
            return
        t = get_store().table
        u = t.get("USER", username)
        if not u:
            raise ValueError("No such user")
        u["active"] = active
        t.put("USER", username, u)

    # Cognito helpers
    def _cognito(self):
        import boto3
        return boto3.client("cognito-idp", region_name=settings.AWS_REGION)

    def _cognito_list(self) -> list[dict]:
        c = self._cognito()
        users = {}
        for role in ROLES:
            token = None
            while True:
                kw = {"UserPoolId": settings.USER_POOL_ID, "GroupName": role}
                if token:
                    kw["NextToken"] = token
                r = c.list_users_in_group(**kw)
                for u in r["Users"]:
                    a = {x["Name"]: x["Value"] for x in u.get("Attributes", [])}
                    users.setdefault(u["Username"], {
                        "username": u["Username"], "name": a.get("name", u["Username"]), "role": role,
                        "dept": a.get("custom:dept", ""), "student_id": a.get("custom:student_id", ""),
                        "active": u.get("Enabled", True)})
                token = r.get("NextToken")
                if not token:
                    break
        return sorted(users.values(), key=lambda u: (ROLES.index(u["role"]), u["username"]))

    def _cognito_create(self, username, name, role, dept, student_id, password, email) -> dict:
        c = self._cognito()
        attrs = [{"Name": "name", "Value": name}]
        if email:
            attrs += [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}]
        if dept:
            attrs.append({"Name": "custom:dept", "Value": dept})
        if student_id:
            attrs.append({"Name": "custom:student_id", "Value": student_id})
        kw = {"UserPoolId": settings.USER_POOL_ID, "Username": username, "UserAttributes": attrs}
        if password:
            kw["MessageAction"] = "SUPPRESS"
        elif email:
            kw["DesiredDeliveryMediums"] = ["EMAIL"]  # Cognito emails a temporary password
        c.admin_create_user(**kw)
        if password:
            c.admin_set_user_password(UserPoolId=settings.USER_POOL_ID, Username=username,
                                      Password=password, Permanent=True)
        c.admin_add_user_to_group(UserPoolId=settings.USER_POOL_ID, Username=username, GroupName=role)
        return {"username": username, "name": name, "role": role, "dept": dept, "student_id": student_id, "active": True}


directory = Directory()
