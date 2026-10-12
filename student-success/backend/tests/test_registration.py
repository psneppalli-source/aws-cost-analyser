"""Student self-registration (local provider) and the authenticator-app requirement."""

import pytest


def _master(call, sid="MECH26901", dob="2008-03-14", email="new.student@college.example"):
    r = call("admin.priya", "POST", "/api/students", {"student_id": sid, "name": "Asha Verma", "department": "MECH", "year": 1,
                                                      "email": email, "date_of_birth": dob, "dataset": "real"})
    assert r.status_code in (201, 409), r.text
    return sid, dob, email


def test_registration_requires_matching_record_then_verified_email(call):
    sid, dob, email = _master(call)
    # wrong date of birth: same generic answer, no code
    r = call("admin.priya", "POST", "/api/register/start", {"student_id": sid, "date_of_birth": "2008-03-15", "email": email})
    assert r.status_code == 200 and "dev_code" not in r.json()
    # wrong email: same
    r = call("admin.priya", "POST", "/api/register/start", {"student_id": sid, "date_of_birth": dob, "email": "x@y.example"})
    assert "dev_code" not in r.json() and r.json()["message"]
    # unknown student: same
    r = call("admin.priya", "POST", "/api/register/start", {"student_id": "MECH26999", "date_of_birth": dob, "email": email})
    assert "dev_code" not in r.json()
    # match: a code is issued (returned only in local development mode)
    r = call("admin.priya", "POST", "/api/register/start", {"student_id": sid, "date_of_birth": dob, "email": email.upper()})
    code = r.json()["dev_code"]
    # the user ID and password are only accepted with the right code
    bad = call("admin.priya", "POST", "/api/register/complete",
               {"student_id": sid, "email": email, "code": "000000-AAaa!", "username": "asha.v", "password": "Str0ng!Passw0rd"})
    assert bad.status_code == 422 and "attempt" in bad.json()["error"]["details"]["code"]
    weak = call("admin.priya", "POST", "/api/register/complete",
                {"student_id": sid, "email": email, "code": code, "username": "asha.v", "password": "short"})
    assert weak.status_code == 422 and "password" in weak.json()["error"]["details"]
    ok = call("admin.priya", "POST", "/api/register/complete",
              {"student_id": sid, "email": email, "code": code, "username": "asha.v", "password": "Str0ng!Passw0rd"})
    assert ok.status_code == 201, ok.text
    # the new account is a student linked to exactly this record
    tok = call("admin.priya", "POST", "/api/auth/local/login", {"username": "asha.v"}).json()["token"]
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    me = c.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["user"]["roles"] == ["student"] and me["user"]["student"] == {"dataset": "real", "student_id": sid}
    other = c.get("/api/students/real/CSE24001", headers={"Authorization": f"Bearer {tok}"})
    assert other.status_code == 403
    # a second registration for the same student is refused (generic answer, no code)
    again = call("admin.priya", "POST", "/api/register/start", {"student_id": sid, "date_of_birth": dob, "email": email})
    assert "dev_code" not in again.json()


def test_code_attempts_and_send_limits(call):
    sid, dob, email = _master(call, "ECE26902", "2007-11-02", "limit.test@college.example")
    codes = [call("admin.priya", "POST", "/api/register/start", {"student_id": sid, "date_of_birth": dob, "email": email}).json().get("dev_code")
             for _ in range(4)]
    assert all(codes[:3]) and codes[3] is None  # at most three codes a day
    for i in range(5):
        r = call("admin.priya", "POST", "/api/register/complete",
                 {"student_id": sid, "email": email, "code": "111111-AAaa!", "username": "lim.t", "password": "Str0ng!Passw0rd"})
        assert r.status_code == 422
    r = call("admin.priya", "POST", "/api/register/complete",
             {"student_id": sid, "email": email, "code": codes[2], "username": "lim.t", "password": "Str0ng!Passw0rd"})
    assert r.status_code == 422 and "too many attempts" in r.json()["error"]["details"]["code"]


def test_students_must_set_up_authenticator_first(client, tokens, monkeypatch):
    from app import main
    from app.auth import authenticate as real_auth

    def fake(headers):
        import dataclasses
        p = real_auth(headers)
        # a copy: never mutate the cached principal
        return dataclasses.replace(p, mfa_required=True, mfa_enabled=False) if "student" in p.roles else p
    monkeypatch.setattr(main, "authenticate", fake)
    h = {"Authorization": f"Bearer {tokens['student.cse']}"}
    me = client.get("/api/me", headers=h)
    assert me.status_code == 200 and me.json()["user"]["mfa"] == {"enabled": False, "required": True}
    blocked = client.get("/api/students/real/CSE24001", headers=h)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "mfa_setup_required"
    staff = client.get("/api/students/real/CSE24001", headers={"Authorization": f"Bearer {tokens['admin.priya']}"})
    assert staff.status_code == 200  # staff are not blocked


def test_date_of_birth_visibility(call):
    admin = call("admin.priya", "GET", "/api/students/real/CSE24001").json()["student"]
    assert admin.get("date_of_birth") and admin.get("email")
    own = call("student.cse", "GET", "/api/students/real/CSE24001").json()["student"]
    assert own.get("date_of_birth") == admin["date_of_birth"] and own.get("email")
    placement = call("placement.rohit", "GET", "/api/students/real/CSE24001").json()["student"]
    assert "date_of_birth" not in placement and "email" not in placement
