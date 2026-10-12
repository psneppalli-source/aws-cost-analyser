"""Accounts, role assignments, mentor and subject assignments.

Roles live in the database against the Cognito user ID (sub). Only a System
Administrator can create accounts or change roles, never their own, and an
account can't combine System Administrator with student-data roles.
Mentor/subject assignments are made by College Administrators (any
department) or HODs (their department).
"""

from __future__ import annotations

import secrets
import string

from . import audit, db, insights
from .auth import clear_principal_cache
from .categories import ValidationError
from .policy import Denied, Principal, require, separation_violation
from .recordsvc import Conflict, NotFound, get_master, target
from .settings import curriculum, role_matrix, settings
from .store import C, ConditionFailed, Delete, Put

ROLES = tuple(role_matrix()["roles"])


def _profile(sub: str) -> dict:
    p = db.table().get(f"USER#{sub}", "PROFILE")
    if not p:
        raise NotFound("Account not found")
    return p


def public_user(p: dict) -> dict:
    return {k: p.get(k) for k in ("sub", "username", "display_name", "email", "status", "roles", "departments",
                                   "student", "created_at", "version")}


def list_users(principal: Principal) -> list[dict]:
    require(principal, "user_account", "read")
    items, _ = db.table().query("USERS", index="gsi2", limit=500)
    return [public_user(i) for i in items]


def staff_directory(principal: Principal, role: str | None = None) -> list[dict]:
    """Minimal list of staff (name, sub, roles) for owner pickers; available to staff roles."""
    if not principal.roles - {"student", "system_admin"}:
        raise Denied()
    items, _ = db.table().query("USERS", index="gsi2", limit=500)
    out = []
    for i in items:
        roles = set(i.get("roles") or [])
        if i.get("status") != "active" or not roles - {"student", "system_admin"}:
            continue
        if role and role not in roles:
            continue
        out.append({"sub": i["sub"], "display_name": i.get("display_name"), "roles": sorted(roles)})
    return out


def _temp_password() -> str:
    alpha = string.ascii_letters + string.digits
    return "".join(secrets.choice(alpha) for _ in range(14)) + secrets.choice("!@#%^*") + secrets.choice(string.digits) + "Aa"


def account_target(prof: dict) -> dict:
    """Policy target for administering an account (its roles decide whether staff_accounts scope applies)."""
    return {"roles": list(prof.get("roles") or [])}


def create_user(principal: Principal, username: str, display_name: str, email: str = "", sub: str | None = None,
                system: bool = False) -> dict:
    if not system:
        require(principal, "user_account", "create")
    username = (username or "").strip().lower()
    if not username or not all(c.isalnum() or c in "._-" for c in username) or not 3 <= len(username) <= 40:
        raise ValidationError({"username": "3-40 characters: letters, digits, dot, dash or underscore"})
    email = (email or "").strip().lower()
    if email and ("@" not in email or "." not in email.split("@")[-1] or len(email) > 120):
        raise ValidationError({"email": "enter a valid email address"})
    temp = None
    if sub is None:
        if settings().auth_mode == "cognito":
            import boto3
            temp = _temp_password()
            attrs = [{"Name": "name", "Value": display_name}]
            if email:
                attrs += [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}]
            # with an email address, Cognito emails the user ID and temporary password (InviteMessageTemplate)
            kw = {"DesiredDeliveryMediums": ["EMAIL"]} if email else {"MessageAction": "SUPPRESS"}
            r = boto3.client("cognito-idp", region_name=settings().region).admin_create_user(
                UserPoolId=settings().cognito_pool_id, Username=username, UserAttributes=attrs,
                TemporaryPassword=temp, **kw)
            sub = next(a["Value"] for a in r["User"]["Attributes"] if a["Name"] == "sub")
        else:
            sub = f"local-{username}"
    ts = db.now()
    item = {"pk": f"USER#{sub}", "sk": "PROFILE", "gsi2pk": "USERS", "gsi2sk": username, "sub": sub, "username": username,
            "display_name": display_name or username, "email": email or None, "status": "active", "roles": [],
            "departments": [], "created_at": ts, "created_by": getattr(principal, "sub", "system"), "version": 1}
    try:
        db.table().put(item, C.not_exists())
    except ConditionFailed:
        raise Conflict(f"An account for {username} already exists") from None
    audit.log(principal, "user.created", "user", username)
    out = public_user(item)
    if temp:
        out["temporary_password"] = temp  # shown once to the administrator; never stored or logged
        out["invitation_emailed"] = bool(email)
    return out


def set_roles(principal: Principal, sub: str, assignments: list[dict], expected_version: int, system: bool = False) -> dict:
    prof = _profile(sub)
    roles = {a.get("role") for a in assignments}
    if not system:
        # the target covers the account's current and new roles: staff_accounts scope never reaches system_admin
        require(principal, "role_assignment", "assign", {"roles": sorted(roles | set(prof.get("roles") or []))})
        if principal.sub == sub:
            raise Denied("You can't change your own role assignments.")
    bad = roles - set(ROLES)
    if bad:
        raise ValidationError({"roles": f"unknown role(s): {', '.join(sorted(bad))}"})
    msg = separation_violation(roles)
    if msg:
        raise ValidationError({"roles": msg})
    items, ops, depts, student = [], [], [], None
    for a in assignments:
        r = a["role"]
        if r == "hod":
            if a.get("department") not in curriculum()["departments"]:
                raise ValidationError({"department": "a HOD assignment needs a valid department"})
            items.append({"sk": f"ROLE#hod#{a['department']}", "role": r, "department": a["department"]})
            depts.append(a["department"])
        elif r == "student":
            ds, sid = a.get("dataset", "real"), str(a.get("student_id", "")).upper()
            get_master(ds, sid)
            items.append({"sk": f"ROLE#student#{ds}#{sid}", "role": r, "dataset": ds, "student_id": sid})
            student = {"dataset": ds, "student_id": sid}
        else:
            items.append({"sk": f"ROLE#{r}", "role": r})
    t = db.table()
    existing, _ = t.query(f"USER#{sub}", "ROLE#")
    ops += [Delete(f"USER#{sub}", e["sk"]) for e in existing]
    ops += [Put({"pk": f"USER#{sub}", **i, "assigned_by": getattr(principal, "sub", "system"), "assigned_at": db.now()})
            for i in items]
    ops.append(Put({**prof, "roles": sorted(roles), "departments": sorted(depts), "student": student,
                    "version": prof["version"] + 1}, C.version(expected_version)))
    try:
        t.transact(ops)
    except ConditionFailed:
        raise Conflict("This account changed since you loaded it. Reload and try again.") from None
    clear_principal_cache(sub)
    audit.log(principal, "role.assigned", "user", prof["username"], {"roles": sorted(roles), "departments": sorted(depts)})
    return public_user(_profile(sub))


def set_status(principal: Principal, sub: str, status: str, expected_version: int) -> dict:
    prof = _profile(sub)
    require(principal, "user_account", "update", account_target(prof))
    if principal.sub == sub:
        raise Denied("You can't change your own account status.")
    if status not in ("active", "disabled"):
        raise ValidationError({"status": "must be active or disabled"})
    try:
        db.table().put({**prof, "status": status, "version": prof["version"] + 1}, C.version(expected_version))
    except ConditionFailed:
        raise Conflict("This account changed since you loaded it.") from None
    if settings().auth_mode == "cognito" and status == "disabled":
        import boto3
        c = boto3.client("cognito-idp", region_name=settings().region)
        c.admin_disable_user(UserPoolId=settings().cognito_pool_id, Username=prof["username"])
        c.admin_user_global_sign_out(UserPoolId=settings().cognito_pool_id, Username=prof["username"])
    clear_principal_cache(sub)
    audit.log(principal, f"user.{status}", "user", prof["username"])
    return public_user(_profile(sub))


# --------------------------------------------------------------------------- mentor and subject assignments
def assign_mentor(principal: Principal, ds: str, sid: str, mentor_sub: str | None, expected_version: int) -> dict:
    m = get_master(ds, sid)
    require(principal, "mentor_assignment", "assign", target(m))
    t = db.table()
    ops = []
    if mentor_sub:
        mp = _profile(mentor_sub)
        if "mentor" not in (mp.get("roles") or []) or mp.get("status") != "active":
            raise ValidationError({"mentor_sub": "the chosen account is not an active mentor"})
        ops.append(Put({"pk": f"USER#{mentor_sub}", "sk": f"MENTEE#{ds}#{sid}", "dataset": ds, "student_id": sid,
                        "assigned_by": principal.sub, "assigned_at": db.now()}))
    if m.get("mentor_sub") and m["mentor_sub"] != mentor_sub:
        ops.append(Delete(f"USER#{m['mentor_sub']}", f"MENTEE#{ds}#{sid}"))
    new = {**m, "mentor_sub": mentor_sub, "mentor_name": _profile(mentor_sub)["display_name"] if mentor_sub else None,
           "updated_at": db.now(), "updated_by": principal.sub, "version": m["version"] + 1}
    ops += [Put(new, C.version(expected_version)), *insights.stale_ops(ds, sid, "mentor assigned")]
    try:
        t.transact(ops)
    except ConditionFailed:
        raise Conflict("This student changed since you loaded it. Reload and try again.") from None
    for s in {mentor_sub, m.get("mentor_sub")} - {None}:
        clear_principal_cache(s)
    insights.recompute_safely(ds, sid)
    audit.log(principal, "mentor.assigned", "student", sid, {"mentor": new["mentor_name"]}, dataset=ds)
    return {k: v for k, v in new.items() if k not in ("pk", "sk")}


def assign_subject(principal: Principal, mentor_sub: str, department: str, year: int, subject: str, remove: bool = False) -> dict:
    subjects = curriculum()["departments"].get(department, {}).get("subjects", {}).get(str(year))
    if not subjects or subject not in subjects:
        raise ValidationError({"subject": f"{subject} is not taught to {department} year {year}"})
    require(principal, "mentor_assignment", "assign", {"department": department, "year": year, "dataset": "real",
                                                       "student_id": "*"})
    mp = _profile(mentor_sub)
    if "mentor" not in (mp.get("roles") or []):
        raise ValidationError({"mentor_sub": "the chosen account is not a mentor"})
    sk = f"SUBJ#{department}#{year}#{subject}"
    if remove:
        db.table().delete(f"USER#{mentor_sub}", sk)
    else:
        db.table().put({"pk": f"USER#{mentor_sub}", "sk": sk, "gsi1pk": f"SUBJECT#{department}#{year}#{subject}",
                        "gsi1sk": mentor_sub, "department": department, "year": year, "subject": subject,
                        "assigned_by": principal.sub, "assigned_at": db.now()})
    clear_principal_cache(mentor_sub)
    audit.log(principal, "subject.unassigned" if remove else "subject.assigned", "user", mp["username"],
              {"department": department, "year": year, "subject": subject})
    return {"mentor_sub": mentor_sub, "department": department, "year": year, "subject": subject, "assigned": not remove}


def assignments_for(principal: Principal, mentor_sub: str) -> dict:
    items, _ = db.table().query(f"USER#{mentor_sub}")
    return {"mentees": [{"dataset": i["dataset"], "student_id": i["student_id"]} for i in items if i["sk"].startswith("MENTEE#")],
            "subjects": [{"department": i["department"], "year": i["year"], "subject": i["subject"]}
                         for i in items if i["sk"].startswith("SUBJ#")]}
