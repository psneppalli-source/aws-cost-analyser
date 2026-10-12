"""Student self-registration, matched against data already in the system.

Flow (public endpoints, no sign-in):
  1. start:    student ID + date of birth + email must all match the student's record, the record must be
               active and not already linked to an account. A verification code is emailed to that address.
               The response is the same whether or not anything matched, so the form can't be used to find
               out who is enrolled.
  2. complete: the code proves the email; only then does the student choose a user ID and password.
               The account is created with a verified email and linked to their record with the student role.
  Authenticator-app MFA is then required before any student data is shown (see auth.load_principal).

Email delivery in AWS uses Cognito's own sender (no SES): a short-lived placeholder user is created with
the code as its temporary password, so Cognito's invitation message (template in infra/template.yaml)
delivers it. The code is generated here and only its hash is stored, so it is checked without signing in.
Locally (no Cognito) the code is returned in the response for development only.

Limits: 3 codes per student per 24 hours, 5 attempts per code, codes expire after 30 minutes.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
import time
from datetime import date

from . import accounts, audit, db
from .categories import ID_RE, ValidationError
from .policy import Principal
from .recordsvc import Conflict
from .settings import settings
from .store import C, ConditionFailed

DS = "real"
CODE_TTL = 30 * 60
MAX_SENDS = 3
MAX_TRIES = 5
GENERIC = ("If those details match a student record without an account, a verification code has been sent to "
           "that email address. It expires in 30 minutes.")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
REGISTRAR = Principal("registration", "registration", "Student self-registration")


def _key(sid: str) -> tuple[str, str]:
    return f"REGISTER#{DS}#{sid}", "STATE"


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def new_code() -> str:
    """Easy to read and type, and valid as a Cognito temporary password (12 chars, upper, lower, digit, symbol)."""
    up = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    low = "abcdefghjkmnpqrstuvwxyz"
    return ("".join(secrets.choice(string.digits) for _ in range(6)) + "-" + "".join(secrets.choice(up) for _ in range(2))
            + "".join(secrets.choice(low) for _ in range(2)) + "!")


def password_problems(pw: str) -> list[str]:
    out = []
    if len(pw) < 12:
        out.append("at least 12 characters")
    if not re.search(r"[A-Z]", pw):
        out.append("an upper-case letter")
    if not re.search(r"[a-z]", pw):
        out.append("a lower-case letter")
    if not re.search(r"\d", pw):
        out.append("a number")
    if not re.search(r"[^A-Za-z0-9]", pw):
        out.append("a symbol")
    return out


def account_for_student(ds: str, sid: str) -> dict | None:
    for u in db.table().query("USERS", index="gsi2", limit=1000)[0]:
        st = u.get("student") or {}
        if st.get("dataset") == ds and st.get("student_id") == sid:
            return u
    return None


def _cognito():
    import boto3
    return boto3.client("cognito-idp", region_name=settings().region)


def _norm(sid: str, dob: str, email: str) -> tuple[str, str, str]:
    errs = {}
    sid = (sid or "").strip().upper()
    if not ID_RE.match(sid):
        errs["student_id"] = "enter your student ID, e.g. CSE24007"
    try:
        dob = date.fromisoformat((dob or "").strip()).isoformat()
    except ValueError:
        errs["date_of_birth"] = "enter your date of birth"
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 120:
        errs["email"] = "enter the email address the college holds for you"
    if errs:
        raise ValidationError(errs)
    return sid, dob, email


def start(student_id: str, date_of_birth: str, email: str) -> dict:
    sid, dob, email = _norm(student_id, date_of_birth, email)
    out = {"message": GENERIC}
    t = db.table()
    m = t.get(f"STU#{DS}#{sid}", "MASTER")
    matched = bool(m and m.get("status", "active") == "active" and m.get("date_of_birth") == dob
                   and (m.get("email") or "").lower() == email and not account_for_student(DS, sid))
    audit.log(REGISTRAR, "registration.requested", "student", sid, {"matched": matched})
    if not matched:
        time.sleep(0.3)  # similar timing either way
        return out
    pk, sk = _key(sid)
    st = t.get(pk, sk) or {}
    now = int(time.time())
    sends = [s for s in st.get("sends", []) if now - s < 86400]
    if len(sends) >= MAX_SENDS:
        return out  # silently rate-limited; same response
    code, salt = new_code(), secrets.token_hex(8)
    placeholder = f"verify-{sid.lower()}-{secrets.token_hex(3)}"
    if settings().auth_mode == "cognito":
        c = _cognito()
        if st.get("placeholder"):
            try:
                c.admin_delete_user(UserPoolId=settings().cognito_pool_id, Username=st["placeholder"])
            except Exception:
                pass
        # Cognito's invitation email (InviteMessageTemplate) delivers the code; the placeholder is never used to sign in.
        c.admin_create_user(UserPoolId=settings().cognito_pool_id, Username=placeholder, TemporaryPassword=code,
                            UserAttributes=[{"Name": "email", "Value": email}], DesiredDeliveryMediums=["EMAIL"])
    else:
        out["dev_code"] = code  # local development only: no email is sent
    item = {"pk": pk, "sk": sk, "student_id": sid, "email": email, "code_hash": _hash(code, salt), "salt": salt,
            "expires_at": now + CODE_TTL, "tries": 0, "sends": sends + [now], "placeholder": placeholder,
            "status": "code_sent", "version": st.get("version", 0) + 1}
    t.put(item, C.version(st["version"]) if st else C.not_exists())
    return out


def complete(student_id: str, email: str, code: str, username: str, password: str) -> dict:
    sid = (student_id or "").strip().upper()
    email = (email or "").strip().lower()
    code = re.sub(r"\s+", "", code or "")
    username = (username or "").strip().lower()
    t = db.table()
    pk, sk = _key(sid)
    st = t.get(pk, sk)
    bad = ValidationError({"code": "that code is not valid or has expired; request a new one"})
    if not st or st.get("status") != "code_sent" or st.get("email") != email or int(time.time()) > st["expires_at"]:
        raise bad
    if st["tries"] >= MAX_TRIES:
        raise ValidationError({"code": "too many attempts; request a new code"})
    try:
        t.put({**st, "tries": st["tries"] + 1, "version": st["version"] + 1}, C.version(st["version"]))
    except ConditionFailed:
        raise Conflict("Please try again.") from None
    st = {**st, "tries": st["tries"] + 1, "version": st["version"] + 1}
    if not secrets.compare_digest(_hash(code, st["salt"]), st["code_hash"]):
        left = MAX_TRIES - st["tries"]
        raise ValidationError({"code": f"that code is not correct ({left} attempt{'s' if left != 1 else ''} left)"})
    # email verified: now the user ID and password
    errs = {}
    if not USERNAME_RE.match(username) or username.startswith("verify-"):
        errs["username"] = "3-40 characters: lower-case letters, digits, dot, dash or underscore"
    probs = password_problems(password or "")
    if probs:
        errs["password"] = "needs " + ", ".join(probs)
    if errs:
        raise ValidationError(errs)
    m = t.get(f"STU#{DS}#{sid}", "MASTER")
    if not m or account_for_student(DS, sid):
        raise bad
    if any(u["username"] == username for u in t.query("USERS", index="gsi2", limit=1000)[0]):
        raise ValidationError({"username": "that user ID is taken; choose another"})
    sub = None
    if settings().auth_mode == "cognito":
        c = _cognito()
        try:
            r = c.admin_create_user(UserPoolId=settings().cognito_pool_id, Username=username, MessageAction="SUPPRESS",
                                    UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"},
                                                    {"Name": "name", "Value": m["name"]}])
        except c.exceptions.UsernameExistsException:
            raise ValidationError({"username": "that user ID is taken; choose another"}) from None
        sub = next(a["Value"] for a in r["User"]["Attributes"] if a["Name"] == "sub")
        try:
            c.admin_set_user_password(UserPoolId=settings().cognito_pool_id, Username=username, Password=password, Permanent=True)
        except c.exceptions.InvalidPasswordException as e:
            c.admin_delete_user(UserPoolId=settings().cognito_pool_id, Username=username)
            raise ValidationError({"password": str(e).split(":")[-1].strip()}) from None
        try:
            c.admin_delete_user(UserPoolId=settings().cognito_pool_id, Username=st["placeholder"])
        except Exception:
            pass
    prof = accounts.create_user(REGISTRAR, username, m["name"], email, sub=sub, system=True)
    accounts.set_roles(REGISTRAR, prof["sub"], [{"role": "student", "dataset": DS, "student_id": sid}], prof["version"], system=True)
    t.put({**st, "status": "registered", "username": username, "code_hash": None, "version": st["version"] + 1})
    audit.log(REGISTRAR, "registration.completed", "student", sid, {"username": username})
    return {"username": username, "message": "Your account is ready. Sign in, then set up your authenticator app."}
