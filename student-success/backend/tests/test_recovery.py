"""Forgotten password and lost authenticator (Cognito replaced by a fake that records calls)."""

import types

import pytest

from app import recovery


class FakeCognito:
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class UserNotFoundException(Exception): pass
        class InvalidParameterException(Exception): pass
        class NotAuthorizedException(Exception): pass
        class LimitExceededException(Exception): pass
        class CodeMismatchException(Exception): pass
        class ExpiredCodeException(Exception): pass
        class InvalidPasswordException(Exception): pass

    def __init__(self):
        self.calls = []

    def forgot_password(self, **kw):
        self.calls.append(("forgot", kw["Username"]))

    def confirm_forgot_password(self, **kw):
        if kw["ConfirmationCode"] != "123456":
            raise self.exceptions.CodeMismatchException("bad code")
        self.calls.append(("confirm", kw["Username"]))

    def admin_user_global_sign_out(self, **kw):
        self.calls.append(("signout", kw["Username"]))

    def admin_reset_user_password(self, **kw):
        self.calls.append(("admin_reset", kw["Username"]))


@pytest.fixture()
def cognito(monkeypatch):
    fake = FakeCognito()
    cfg = types.SimpleNamespace(auth_mode="cognito", cognito_client_id="client", cognito_pool_id="pool", region="eu-west-2")
    monkeypatch.setattr(recovery, "settings", lambda: cfg)
    monkeypatch.setattr(recovery, "_cognito", lambda: fake)
    resets = []
    monkeypatch.setattr(recovery, "reset_mfa", lambda u: resets.append(u))
    fake.resets = resets
    return fake


def test_forgot_password_sends_code_with_same_answer_for_unknown_users(cognito):
    a = recovery.start("student.cse")
    b = recovery.start("no.such.user")
    assert a == b and ("forgot", "student.cse") in cognito.calls


def test_new_password_needs_the_emailed_code(cognito):
    with pytest.raises(recovery.ValidationError) as e:
        recovery.complete("student.cse", "999999", "Str0ng!Passw0rd")
    assert "code" in e.value.errors
    with pytest.raises(recovery.ValidationError) as e:
        recovery.complete("student.cse", "123456", "weak")
    assert "password" in e.value.errors
    r = recovery.complete("student.cse", "123456", "Str0ng!Passw0rd")
    assert "changed" in r["message"] and ("signout", "student.cse") in cognito.calls and not cognito.resets


def test_lost_authenticator_for_students_also_needs_date_of_birth(cognito):
    from app import db
    dob = db.table().get("STU#real#CSE24001", "MASTER")["date_of_birth"]
    with pytest.raises(recovery.ValidationError) as e:
        recovery.complete("student.cse", "123456", "Str0ng!Passw0rd", reset_authenticator=True, date_of_birth="2001-01-01")
    assert "date_of_birth" in e.value.errors and not cognito.resets
    r = recovery.complete("student.cse", "123456", "Str0ng!Passw0rd", reset_authenticator=True, date_of_birth=dob)
    assert cognito.resets == ["student.cse"] and "authenticator" in r["message"]


def test_staff_can_reset_authenticator_with_the_email_code(cognito):
    recovery.complete("mentor.arjun", "123456", "Str0ng!Passw0rd", reset_authenticator=True)
    assert cognito.resets == ["mentor.arjun"]


def test_recovery_endpoints_and_admin_reset(call, cognito):
    assert call("admin.priya", "POST", "/api/recovery/start", {"username": "student.cse"}).status_code == 200
    bad = call("admin.priya", "POST", "/api/recovery/complete", {"username": "student.cse", "code": "12", "password": "x"})
    assert bad.status_code == 422 and {"code", "password"} <= set(bad.json()["error"]["details"])
    users = {u["username"]: u for u in call("sysadmin.dev", "GET", "/api/users").json()["items"]}
    sub = users["mentor.arjun"]["sub"]
    assert call("mentor.arjun", "POST", f"/api/users/{sub}/password-reset").status_code == 403
    assert call("sysadmin.dev", "POST", f"/api/users/{sub}/password-reset").status_code == 200
    assert ("admin_reset", "mentor.arjun") in cognito.calls


def test_not_available_without_cognito(call):
    r = call("admin.priya", "POST", "/api/recovery/start", {"username": "student.cse"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_available"
