"""Policy engine over config/role-matrix.json.

`decide(principal, resource, action, target)` returns the allowed field list or
None. Scopes are evaluated only against trusted server-side assignments held
on the Principal (loaded from the database by the Cognito user ID).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .settings import role_matrix

SCOPES = ("college", "department", "assigned_subject", "assigned_students", "own_record", "system")


@dataclass
class Principal:
    sub: str
    username: str
    display_name: str
    roles: set[str] = field(default_factory=set)
    departments: set[str] = field(default_factory=set)          # HOD departments
    mentees: set[tuple[str, str]] = field(default_factory=set)   # (dataset, student_id)
    subjects: set[tuple[str, int, str]] = field(default_factory=set)  # (dept, year, subject)
    student: tuple[str, str] | None = None                      # (dataset, student_id) for student accounts
    datasets: tuple[str, ...] = ("real", "demo")

    def public(self) -> dict:
        m = role_matrix()
        return {
            "sub": self.sub, "username": self.username, "display_name": self.display_name,
            "roles": sorted(self.roles), "role_labels": [m["roles"][r]["label"] for r in sorted(self.roles)],
            "departments": sorted(self.departments), "mentee_count": len(self.mentees),
            "subjects": [{"department": d, "year": y, "subject": s} for d, y, s in sorted(self.subjects)],
            "student": {"dataset": self.student[0], "student_id": self.student[1]} if self.student else None,
        }


class Denied(Exception):
    def __init__(self, message: str = "You are not allowed to do this."):
        super().__init__(message)


def _fields(spec) -> list[str]:
    if isinstance(spec, list):
        return spec
    return role_matrix()["field_sets"][spec]


def grants(p: Principal, resource: str, action: str) -> list[dict]:
    out = []
    m = role_matrix()
    for role in p.roles:
        for g in m["roles"].get(role, {}).get("permissions", []):
            if g["resource"] == resource and g["action"] == action:
                out.append({**g, "role": role, "fields": _fields(g["fields"])})
    return out


def scope_holds(p: Principal, scope: str, t: dict | None) -> bool:
    if scope == "system":
        return t is None or not t.get("student_id")
    if t is None:
        return scope == "college"
    ds, sid = t.get("dataset"), t.get("student_id")
    if ds and ds not in p.datasets:
        return False
    if scope == "college":
        return True
    if scope == "department":
        return t.get("department") in p.departments
    if scope == "assigned_students":
        return (ds, sid) in p.mentees
    if scope == "assigned_subject":
        dept, year = t.get("department"), t.get("year")
        subj = t.get("subject")
        if subj is not None:
            return (dept, year, subj) in p.subjects
        return any(d == dept and y == year for d, y, _ in p.subjects)
    if scope == "own_record":
        return p.student is not None and (ds, sid) == p.student
    return False


def decide(p: Principal, resource: str, action: str, target: dict | None = None) -> list[str] | None:
    """Allowed fields (union over matching grants), or None if denied."""
    allowed: list[str] = []
    ok = False
    for g in grants(p, resource, action):
        if scope_holds(p, g["scope"], target):
            ok = True
            allowed += g["fields"]
    if not ok:
        return None
    return ["*"] if "*" in allowed else sorted(set(allowed))


def require(p: Principal, resource: str, action: str, target: dict | None = None) -> list[str]:
    f = decide(p, resource, action, target)
    if f is None:
        raise Denied()
    return f


def constraints(p: Principal, key: str) -> list | None:
    """Union of a constraint across roles; None means unconstrained by any role."""
    m = role_matrix()
    vals, unconstrained = [], False
    for role in p.roles:
        c = m["roles"].get(role, {}).get("constraints", {}).get(key)
        if c is None:
            unconstrained = True
        else:
            vals += c
    return None if unconstrained else vals


def filter_fields(obj: dict, fields: list[str]) -> dict:
    """Keep only allowed fields; dotted paths keep nested keys (e.g. components.placement)."""
    if "*" in fields:
        return obj
    out: dict = {}
    for f in fields:
        parts = f.split(".")
        src, dst = obj, out
        for i, part in enumerate(parts):
            if not isinstance(src, dict) or part not in src:
                break
            if i == len(parts) - 1:
                dst[part] = copy.deepcopy(src[part])
            else:
                src = src[part]
                dst = dst.setdefault(part, {})
    return out


def visibility(p: Principal, resource: str, action: str = "read") -> dict:
    """Which student sets a listing may include, derived from grants (no per-item checks needed)."""
    scopes = {g["scope"] for g in grants(p, resource, action)}
    return {
        "college": "college" in scopes,
        "departments": p.departments if "department" in scopes else set(),
        "mentees": p.mentees if "assigned_students" in scopes else set(),
        "subject_classes": {(d, y) for d, y, _ in p.subjects} if "assigned_subject" in scopes else set(),
        "own": p.student if "own_record" in scopes else None,
    }


def separation_violation(roles: set[str]) -> str | None:
    sod = role_matrix()["separation_of_duties"]
    if "system_admin" in roles and roles & set(sod["student_data_roles"]):
        return "An account cannot hold System Administrator together with a student-data role."
    return None
