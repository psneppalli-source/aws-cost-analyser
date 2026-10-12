"""Record categories: fields, validation rules and natural keys.

The same definitions drive manual entry forms, CSV/XLSX import templates,
seeding and the data dictionary, so all three validate identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PERIOD_RE = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
ID_RE = re.compile(r"^[A-Z]{2,5}\d{2}\d{3}$")  # e.g. CSE24007


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


@dataclass
class F:
    name: str
    kind: str  # str|int|float|enum|list
    required: bool = True
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    max_len: int = 200
    sensitive: bool = False
    help: str = ""


@dataclass
class Category:
    key: str
    label: str
    fields: list[F]
    subkey: list[str] = field(default_factory=list)  # fields forming the per-period natural key
    correction_required: bool = False                # changes to existing records go to HOD approval
    verification: bool = False                       # records carry pending/verified/rejected status
    description: str = ""

    def subkey_of(self, data: dict) -> str:
        if not self.subkey:
            return "-"
        return "|".join(re.sub(r"[^a-z0-9]+", "-", str(data[k]).lower()).strip("-") for k in self.subkey)


SUPPORT_CHOICES = ("academic", "financial", "health", "career", "personal", "none")

CATEGORIES: dict[str, Category] = {c.key: c for c in [
    Category("academic_result", "Academic results", [
        F("semester", "int", True, 1, 8),
        F("sgpa", "float", False, 0, 10),
        F("cgpa", "float", True, 0, 10),
        F("backlogs", "int", True, 0, 30),
    ], [], correction_required=True, description="Cumulative results as declared in the period."),
    Category("marks", "Subject marks", [
        F("subject", "str", True, max_len=80),
        F("assessment", "str", True, max_len=60, help="e.g. Internal test 1"),
        F("score", "float", True, 0, 500),
        F("max_score", "float", True, 1, 500),
    ], ["subject", "assessment"], correction_required=True, description="One assessment in one subject."),
    Category("attendance", "Subject attendance", [
        F("subject", "str", True, max_len=80),
        F("classes_held", "int", True, 1, 80),
        F("classes_attended", "int", True, 0, 80),
    ], ["subject"], correction_required=True, description="Classes held and attended in the month."),
    Category("lms", "LMS summary", [
        F("assignments_due", "int", True, 0, 60),
        F("assignments_submitted", "int", True, 0, 60),
        F("logins", "int", True, 0, 1000),
    ], [], description="Monthly LMS activity and assignment completion."),
    Category("engagement", "Events, clubs and projects", [
        F("activity_type", "enum", True, choices=("event", "club", "project")),
        F("name", "str", True, max_len=100),
        F("role", "str", False, max_len=60),
    ], ["activity_type", "name"], verification=True, description="Participation recorded by the activity coordinator."),
    Category("certification", "Certifications", [
        F("name", "str", True, max_len=100),
        F("issuer", "str", True, max_len=100),
        F("evidence_ref", "str", False, max_len=200, help="Certificate number or link"),
    ], ["name"], verification=True, description="Submitted by students; verified by the activity coordinator."),
    Category("placement_assessment", "Placement assessments", [
        F("assessment_type", "enum", True, choices=("aptitude", "coding", "mock_interview")),
        F("score", "float", True, 0, 100, help="0-100; mock interviews 1-5"),
        F("readiness_note", "str", False, max_len=300),
    ], ["assessment_type"], description="Latest result per assessment type in the period."),
    Category("skills", "Skills assessment", [
        F("technical", "float", True, 0, 100),
        F("communication", "float", True, 0, 100),
    ], [], description="Technical and communication skills (0-100)."),
    Category("feedback", "Student feedback", [
        F("satisfaction", "int", True, 1, 5),
        F("stress", "int", True, 1, 5),
        F("support_needed", "list", False, choices=SUPPORT_CHOICES),
        F("comment", "str", False, max_len=1000, sensitive=True),
    ], [], description="Context for support. Never changes the score."),
]}


def coerce(f: F, raw):
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if f.kind == "str":
        s = str(raw).strip()
        if len(s) > f.max_len:
            raise ValueError(f"must be at most {f.max_len} characters")
        return s
    if f.kind in ("int", "float"):
        try:
            x = float(str(raw).replace("%", "").strip())
        except ValueError:
            raise ValueError("must be a number") from None
        if f.kind == "int":
            if x != int(x):
                raise ValueError("must be a whole number")
            x = int(x)
        if (f.lo is not None and x < f.lo) or (f.hi is not None and x > f.hi):
            raise ValueError(f"must be between {f.lo:g} and {f.hi:g}")
        return x
    if f.kind == "enum":
        s = str(raw).strip().lower()
        if s not in f.choices:
            raise ValueError(f"must be one of {', '.join(f.choices)}")
        return s
    if f.kind == "list":
        vals = raw if isinstance(raw, list) else [v.strip() for v in str(raw).replace(";", ",").split(",")]
        vals = [v.lower() for v in vals if v]
        bad = [v for v in vals if v not in f.choices]
        if bad:
            raise ValueError(f"unknown value(s) {', '.join(bad)}")
        return vals
    raise ValueError(f"unknown kind {f.kind}")


def validate(category: str, data: dict) -> dict:
    cat = CATEGORIES.get(category)
    if not cat:
        raise ValidationError({"category": "unknown category"})
    out, errors = {}, {}
    for f in cat.fields:
        try:
            v = coerce(f, data.get(f.name))
        except ValueError as e:
            errors[f.name] = str(e)
            continue
        if v is None and f.required:
            errors[f.name] = "is required"
        out[f.name] = v
    if not errors:
        if category == "attendance" and out["classes_attended"] > out["classes_held"]:
            errors["classes_attended"] = "cannot be more than classes held"
        if category == "lms" and out["assignments_submitted"] > out["assignments_due"]:
            errors["assignments_submitted"] = "cannot be more than assignments due"
        if category == "marks" and out["score"] > out["max_score"]:
            errors["score"] = "cannot be more than the maximum score"
        if category == "placement_assessment" and out["assessment_type"] == "mock_interview" and not 1 <= out["score"] <= 5:
            errors["score"] = "mock interview ratings are 1-5"
    if errors:
        raise ValidationError(errors)
    return out


def validate_period(period: str) -> str:
    if not PERIOD_RE.match(period or ""):
        raise ValidationError({"period": "must be YYYY-MM"})
    return period


def template_csv(category: str) -> str:
    cat = CATEGORIES[category]
    cols = ["student_id", "period"] + [f.name for f in cat.fields]
    examples = {"student_id": "CSE24007", "period": "2026-09", "semester": "5", "sgpa": "7.4", "cgpa": "7.2", "backlogs": "0",
                "subject": "Operating Systems", "assessment": "Internal test 2", "score": "34", "max_score": "50",
                "classes_held": "18", "classes_attended": "16", "assignments_due": "4", "assignments_submitted": "4", "logins": "22",
                "activity_type": "event", "name": "Tech Fest volunteer", "role": "Volunteer", "issuer": "NPTEL",
                "evidence_ref": "NPTEL-2026-1234", "assessment_type": "coding", "readiness_note": "",
                "technical": "68", "communication": "61", "satisfaction": "4", "stress": "3", "support_needed": "career",
                "comment": ""}
    if category == "certification":
        examples["name"] = "Python for Data Science"
    return ",".join(cols) + "\n" + ",".join(examples.get(c, "") for c in cols) + "\n"


def describe() -> list[dict]:
    return [{"category": c.key, "label": c.label, "description": c.description, "natural_key": ["student_id", "period"] + c.subkey,
             "correction_required": c.correction_required, "verification": c.verification,
             "fields": [{"name": f.name, "type": f.kind, "required": f.required, "min": f.lo, "max": f.hi,
                         "choices": list(f.choices), "sensitive": f.sensitive, "help": f.help} for f in c.fields]}
            for c in CATEGORIES.values()]
