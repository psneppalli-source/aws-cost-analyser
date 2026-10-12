"""Account recovery: forgotten password and lost authenticator app (public endpoints, no sign-in).

  1. start:    the user ID is entered; Cognito emails a 6-digit code to the account's verified email
               (ForgotPassword). The answer is the same whether or not the account exists.
  2. complete: the code and a new password are entered; Cognito checks the code and sets the password
               (ConfirmForgotPassword). Optionally the authenticator app is reset too (lost phone): student
               accounts must also give their date of birth for that. The user then sets up a new authenticator
               at the next sign-in, and every existing session is signed out.

Cognito limits how often codes can be requested and tried. Locally (no Cognito) there are no passwords,
so recovery is not available.
"""

from __future__ import annotations

import re

from . import audit, db
from .auth import clear_principal_cache, reset_mfa
from .categories import ValidationError
from .policy import Principal
from .registration import CODE_RE, password_problems
from .settings import settings

GENERIC = ("If that user ID has an account with a verified email address, a 6-digit code has been sent to it. "
           "Enter it below within an hour.")
RECOVERY = Principal("recovery", "recovery", "Account recovery")


class NotAvailable(Exception):
    pass


def _cognito():
    import boto3
    return boto3.client("cognito-idp", region_name=settings().region)


def _profile(username: str) -> dict | None:
    for u in db.table().query("USERS", index="gsi2", limit=1000)[0]:
        if u["username"] == username:
            return u
    return None


def _username(raw: str) -> str:
    u = (raw or "").strip().lower()
    if not re.match(r"^[a-z0-9][a-z0-9._-]{1,39}$", u):
        raise ValidationError({"username": "enter your user ID"})
    return u


def start(username: str) -> dict:
    if settings().auth_mode != "cognito":
        raise NotAvailable("Password recovery is used with the college sign-in on the hosted site.")
    u = _username(username)
    c = _cognito()
    try:
        c.forgot_password(ClientId=settings().cognito_client_id, Username=u)
    except (c.exceptions.UserNotFoundException, c.exceptions.InvalidParameterException,
            c.exceptions.NotAuthorizedException):
        pass  # unknown user, no verified email, or disabled: same answer
    except c.exceptions.LimitExceededException:
        raise ValidationError({"username": "too many requests; try again later"}) from None
    audit.log(RECOVERY, "recovery.requested", "user", u)
    return {"message": GENERIC}


def complete(username: str, code: str, password: str, reset_authenticator: bool = False,
             date_of_birth: str | None = None) -> dict:
    if settings().auth_mode != "cognito":
        raise NotAvailable("Password recovery is used with the college sign-in on the hosted site.")
    u = _username(username)
    code = re.sub(r"\s+", "", code or "")
    errs = {}
    if not CODE_RE.match(code):
        errs["code"] = "enter the 6-digit code from the email"
    probs = password_problems(password or "")
    if probs:
        errs["password"] = "needs " + ", ".join(probs)
    prof = _profile(u)
    st = (prof or {}).get("student") or {}
    if reset_authenticator and st.get("student_id"):
        # a lost phone is the second factor; students also confirm their date of birth
        m = db.table().get(f"STU#{st['dataset']}#{st['student_id']}", "MASTER") or {}
        if (date_of_birth or "").strip() != m.get("date_of_birth"):
            errs["date_of_birth"] = "enter your date of birth as held by the college"
    if errs:
        raise ValidationError(errs)
    c = _cognito()
    try:
        c.confirm_forgot_password(ClientId=settings().cognito_client_id, Username=u, ConfirmationCode=code, Password=password)
    except (c.exceptions.CodeMismatchException, c.exceptions.ExpiredCodeException, c.exceptions.UserNotFoundException):
        raise ValidationError({"code": "that code is not correct or has expired; request a new one"}) from None
    except c.exceptions.InvalidPasswordException as e:
        raise ValidationError({"password": str(e).split(":")[-1].strip()}) from None
    except c.exceptions.LimitExceededException:
        raise ValidationError({"code": "too many attempts; try again later"}) from None
    if reset_authenticator:
        reset_mfa(u)
    try:
        c.admin_user_global_sign_out(UserPoolId=settings().cognito_pool_id, Username=u)
    except Exception:
        pass
    if prof:
        clear_principal_cache(prof["sub"])
    audit.log(RECOVERY, "recovery.completed", "user", u, {"authenticator_reset": bool(reset_authenticator)})
    msg = "Your password has been changed."
    if reset_authenticator:
        msg += " Your authenticator app was reset: after signing in, scan the new QR code."
    return {"message": msg}


def admin_send_reset(p: Principal, sub: str) -> dict:
    """System Administrator: email the user a code to choose a new password (their current one stops working)."""
    prof = db.table().get(f"USER#{sub}", "PROFILE")
    if not prof:
        raise ValidationError({"user": "account not found"})
    if settings().auth_mode == "cognito":
        _cognito().admin_reset_user_password(UserPoolId=settings().cognito_pool_id, Username=prof["username"])
    clear_principal_cache(sub)
    audit.log(p, "password.reset_sent", "user", prof["username"])
    return {"message": f"A password reset code was emailed to {prof['username']}."}

