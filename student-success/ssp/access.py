"""Server-side authorisation: which students a user may see, which fields, and
what they may change. Every API handler goes through these functions.

| Role              | Students visible                        | Sensitive feedback | Interventions                     |
|-------------------|-----------------------------------------|--------------------|-----------------------------------|
| Administrator     | all                                     | yes                | create / update any               |
| HOD               | own department                          | yes                | view + add notes (monitoring)     |
| Faculty / Mentor  | students assigned to them               | yes                | create / update for their mentees |
| Placement Officer | students in placement years             | no                 | create / update placement actions |
| Student           | themselves                              | no                 | view their own                    |
"""

from __future__ import annotations

from .auth import Principal

SENSITIVE_ROLES = {"admin", "hod", "mentor"}


class Forbidden(Exception):
    pass


def visible_ids(p: Principal, roster: dict[str, dict], current: dict[str, dict]) -> set[str]:
    if p.role == "admin":
        return set(roster)
    if p.role == "hod":
        return {sid for sid, s in roster.items() if s["department"] == p.dept}
    if p.role == "mentor":
        return {sid for sid, s in roster.items() if (s.get("mentor_username") or "").lower() == p.username}
    if p.role == "placement":
        return {sid for sid, snap in current.items() if snap.get("placement_year")}
    if p.role == "student":
        return {p.student_id} if p.student_id in roster else set()
    return set()


def require_view(p: Principal, sid: str, roster: dict, current: dict) -> None:
    if sid not in visible_ids(p, roster, current):
        raise Forbidden("You don't have access to this student.")


def require_role(p: Principal, *roles: str) -> None:
    if p.role not in roles:
        raise Forbidden("Your role doesn't allow this action.")


def sees_sensitive(p: Principal) -> bool:
    return p.role in SENSITIVE_ROLES


def redact_snapshot(p: Principal, snap: dict) -> dict:
    """Remove wellbeing details for roles that must not see them."""
    if sees_sensitive(p):
        return snap
    s = {**snap, "detail": {k: v for k, v in snap.get("detail", {}).items() if k not in ("faculty_remark", "concern_tags")}}
    s["features"] = {**snap["features"], "stress": None, "wellbeing_concern": None}
    s["risk"] = {k: {**r, "evidence": [e if not e.get("sensitive") else
                                       {**e, "value": None, "why": "Wellbeing concern noted (details visible to mentor only)"}
                                       for e in r["evidence"]]} for k, r in snap["risk"].items()}
    if p.role == "student":
        s["actions"] = []
    return s


def can_create_intervention(p: Principal, student: dict, owner_role: str) -> bool:
    if p.role == "admin":
        return True
    if p.role == "mentor":
        return (student.get("mentor_username") or "").lower() == p.username
    if p.role == "placement":
        return owner_role == "placement"
    return False


def can_update_intervention(p: Principal, item: dict, student: dict) -> str:
    """Return 'full', 'note' or '' (none)."""
    if p.role == "admin":
        return "full"
    if p.role == "mentor" and ((student.get("mentor_username") or "").lower() == p.username or item["owner"] == p.username):
        return "full"
    if p.role == "placement" and (item["owner_role"] == "placement" or item["owner"] == p.username):
        return "full"
    if p.role == "hod" and student.get("department") == p.dept:
        return "note"
    return ""
