"""Upload templates: one schema per data category.

Each field declares its type, whether it is required, allowed values or range,
and the header spellings accepted from real exports. `key` is the natural key:
re-uploading a row with the same key updates it instead of duplicating it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

ID_RE = re.compile(r"^(\d{2})([A-Z]{2,5})(\d{1,3})$")
TERM_RE = re.compile(r"^(20\d{2})-(ODD|EVEN)$")
MONTH_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")

DEPARTMENTS = {
    "CSE": ["cse", "c.s.e", "computer science", "computer science & engg", "computer science and engineering"],
    "IT": ["it", "i.t.", "information technology"],
    "ECE": ["ece", "e.c.e", "electronics & communication", "electronics and communication"],
    "MECH": ["mech", "mechanical", "mechanical engg", "mechanical engineering"],
    "CIVIL": ["civil", "civil engg", "civil engineering"],
    "MCA": ["mca", "computer applications", "master of computer applications"],
}
COURSES = {"B.Tech": ["b.tech", "btech", "b tech", "be", "b.e"], "MCA": ["mca"]}
ACTIVITY_TYPES = ["event", "club", "project", "hackathon", "certification"]
TRUE = {"y", "yes", "true", "1"}
FALSE = {"n", "no", "false", "0", ""}


def canonical_id(raw) -> str | None:
    """'24-cse-007', ' 24CSE7 ', '24cse007@campus.edu.in' -> '24CSE007'."""
    if raw is None:
        return None
    s = str(raw).strip().upper().split("@")[0]
    s = re.sub(r"[\s\-_/]", "", s)
    m = ID_RE.match(s)
    return f"{m.group(1)}{m.group(2)}{int(m.group(3)):03d}" if m else None


def _alias_map(d: dict[str, list[str]]) -> dict[str, str]:
    out = {}
    for canon, aliases in d.items():
        out[canon.lower()] = canon
        for a in aliases:
            out[a.lower()] = canon
    return out


DEPT_ALIAS = _alias_map(DEPARTMENTS)
COURSE_ALIAS = _alias_map(COURSES)


@dataclass
class Field:
    name: str
    kind: str  # id | str | int | float | date | month | term | enum | bool | dept | course
    required: bool = False
    lo: float | None = None
    hi: float | None = None
    allowed: list[str] | None = None
    aliases: list[str] = field(default_factory=list)
    help: str = ""


@dataclass
class Schema:
    category: str
    label: str
    fields: list[Field]
    key: list[str]
    description: str
    example: dict

    def field(self, name: str) -> Field:
        return next(f for f in self.fields if f.name == name)


SID = Field("student_id", "id", True, aliases=["roll no", "roll_no", "rollno", "reg_no", "registration no", "student id",
                                               "roll", "user_email", "email", "student_ref", "usn"],
            help="College roll number, e.g. 24CSE007. Emails like 24cse007@college.edu are accepted.")

SCHEMAS: dict[str, Schema] = {s.category: s for s in [
    Schema("students", "Student roster", [
        SID,
        Field("name", "str", True, aliases=["student name", "full name"]),
        Field("department", "dept", True, aliases=["dept", "branch"], help="CSE, IT, ECE, MECH, CIVIL or MCA"),
        Field("course", "course", True, aliases=["programme", "program"], help="B.Tech or MCA"),
        Field("admission_year", "int", True, 2015, 2030, aliases=["batch", "year of admission"]),
        Field("mentor_username", "str", False, aliases=["mentor", "mentor id"], help="Username of the assigned mentor"),
        Field("gender", "enum", False, allowed=["F", "M", "Other"]),
        Field("hosteller", "bool", False, aliases=["hostel"]),
    ], ["student_id"], "Master list. Upload this first: every other file is matched against it.",
        {"student_id": "24CSE007", "name": "Ananya Rao", "department": "CSE", "course": "B.Tech",
         "admission_year": 2024, "mentor_username": "mentor.cse1", "gender": "F", "hosteller": "Y"}),

    Schema("academic", "Semester results", [
        SID,
        Field("term", "term", True, help="Semester the result belongs to: YYYY-ODD (Jul-Nov) or YYYY-EVEN (Jan-May)"),
        Field("semester", "int", True, 1, 8),
        Field("sgpa", "float", False, 0, 10),
        Field("cgpa", "float", True, 0, 10),
        Field("backlogs", "int", True, 0, 60, aliases=["active backlogs", "arrears"]),
    ], ["student_id", "term"], "One row per student per declared semester result.",
        {"student_id": "24CSE007", "term": "2026-EVEN", "semester": 4, "sgpa": 7.8, "cgpa": 7.65, "backlogs": 0}),

    Schema("internal_marks", "Internal assessment marks", [
        SID,
        Field("term", "term", True),
        Field("subject", "str", True),
        Field("marks", "float", True, 0, 200, aliases=["internal_marks", "marks obtained"]),
        Field("max_marks", "float", True, 1, 200),
    ], ["student_id", "term", "subject"], "Subject-wise internal marks for the current term.",
        {"student_id": "24CSE007", "term": "2026-ODD", "subject": "Operating Systems", "marks": 31, "max_marks": 40}),

    Schema("attendance", "Attendance", [
        SID,
        Field("month", "month", True, help="YYYY-MM"),
        Field("subject", "str", True),
        Field("classes_held", "int", True, 1, 100, aliases=["held"]),
        Field("classes_attended", "int", True, 0, 100, aliases=["attended"]),
    ], ["student_id", "month", "subject"], "Subject-wise classes held and attended per month.",
        {"student_id": "24CSE007", "month": "2026-08", "subject": "Operating Systems", "classes_held": 16, "classes_attended": 14}),

    Schema("lms", "LMS activity", [
        SID,
        Field("week_start", "date", True, help="Monday of the week, YYYY-MM-DD"),
        Field("logins", "int", True, 0, 200),
        Field("assignments_due", "int", True, 0, 30),
        Field("assignments_submitted", "int", True, 0, 30),
        Field("quiz_score", "float", False, 0, 100, help="Average quiz %, blank if no quiz attempted"),
    ], ["student_id", "week_start"], "Weekly LMS export.",
        {"student_id": "24CSE007", "week_start": "2026-08-03", "logins": 5, "assignments_due": 2,
         "assignments_submitted": 2, "quiz_score": 72.5}),

    Schema("engagement", "Events, clubs, projects & certifications", [
        SID,
        Field("activity_date", "date", True, aliases=["date"]),
        Field("activity_type", "enum", True, allowed=ACTIVITY_TYPES, aliases=["type"]),
        Field("activity_name", "str", True, aliases=["name", "activity"]),
    ], ["student_id", "activity_date", "activity_type", "activity_name"], "One row per activity.",
        {"student_id": "24CSE007", "activity_date": "2026-08-20", "activity_type": "hackathon",
         "activity_name": "Smart India Hackathon"}),

    Schema("placement", "Placement assessments", [
        SID,
        Field("assessment_date", "date", True, aliases=["attempt_date", "test date"]),
        Field("aptitude_score", "float", False, 0, 100),
        Field("coding_score", "float", False, 0, 100),
        Field("mock_interview_rating", "float", False, 1, 5, help="1-5"),
        Field("resume_reviewed", "bool", False),
    ], ["student_id", "assessment_date"], "Training & Placement cell test results; one row per attempt.",
        {"student_id": "24CSE007", "assessment_date": "2026-08-15", "aptitude_score": 64, "coding_score": 58,
         "mock_interview_rating": 3.4, "resume_reviewed": "Y"}),

    Schema("skills", "Skills assessments", [
        SID,
        Field("assessed_on", "date", True),
        Field("technical", "float", True, 0, 100, aliases=["technical_skill"]),
        Field("communication", "float", False, 0, 100),
        Field("teamwork", "float", False, 0, 100),
        Field("problem_solving", "float", False, 0, 100),
    ], ["student_id", "assessed_on"], "Technical and soft-skill assessment scores (0-100; '72%' accepted).",
        {"student_id": "24CSE007", "assessed_on": "2026-08-20", "technical": 68, "communication": 61,
         "teamwork": 70, "problem_solving": 64}),

    Schema("feedback", "Student & faculty feedback", [
        SID,
        Field("term", "term", True),
        Field("satisfaction", "int", False, 1, 5, aliases=["satisfaction_1to5"]),
        Field("stress", "int", False, 1, 5, aliases=["stress_1to5"]),
        Field("faculty_rating", "float", False, 1, 5, aliases=["mentor_rating", "mentor_rating_1to5"]),
        Field("faculty_remark", "str", False, aliases=["mentor_remark", "remark"]),
    ], ["student_id", "term"], "Student survey (satisfaction, stress) and mentor rating/remark per term.",
        {"student_id": "24CSE007", "term": "2026-ODD", "satisfaction": 4, "stress": 3, "faculty_rating": 3.8,
         "faculty_remark": "Regular in mentoring sessions."}),
]}


def parse_date(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if re.fullmatch(r"\d{5}(\.0)?", s):  # Excel serial day number
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"'{s}' is not a date (use YYYY-MM-DD)")


def coerce(f: Field, raw):
    """Return the normalised value, None for blank, or raise ValueError with a readable message."""
    if raw is None or (isinstance(raw, str) and raw.strip() == "") or (isinstance(raw, float) and raw != raw):
        return None
    s = str(raw).strip()
    k = f.kind
    if k == "id":
        v = canonical_id(s)
        if not v:
            raise ValueError(f"'{s}' is not a valid roll number")
        return v
    if k == "str":
        return s
    if k in ("int", "float"):
        try:
            x = float(s.replace("%", "").replace(",", ""))
        except ValueError:
            raise ValueError(f"'{s}' is not a number") from None
        if k == "int":
            if x != int(x):
                raise ValueError(f"'{s}' must be a whole number")
            x = int(x)
        if f.lo is not None and x < f.lo or f.hi is not None and x > f.hi:
            raise ValueError(f"{s} is outside the allowed range {f.lo:g}-{f.hi:g}")
        return x
    if k == "date":
        return parse_date(raw)
    if k == "month":
        if isinstance(raw, (date, datetime)):
            return raw.strftime("%Y-%m")
        if not MONTH_RE.match(s):
            raise ValueError(f"'{s}' is not a month (use YYYY-MM)")
        return s
    if k == "term":
        t = s.upper().replace(" ", "-")
        if not TERM_RE.match(t):
            raise ValueError(f"'{s}' is not a term (use e.g. 2026-ODD or 2026-EVEN)")
        return t
    if k == "enum":
        for a in f.allowed:
            if a.lower() == s.lower():
                return a
        raise ValueError(f"'{s}' is not one of: {', '.join(f.allowed)}")
    if k == "bool":
        if s.lower() in TRUE:
            return True
        if s.lower() in FALSE:
            return False
        raise ValueError(f"'{s}' must be Yes or No")
    if k == "dept":
        v = DEPT_ALIAS.get(s.lower())
        if not v:
            raise ValueError(f"'{s}' is not a known department ({', '.join(DEPARTMENTS)})")
        return v
    if k == "course":
        v = COURSE_ALIAS.get(s.lower())
        if not v:
            raise ValueError(f"'{s}' is not a known course ({', '.join(COURSES)})")
        return v
    raise ValueError(f"unknown field kind {k}")


def cross_checks(category: str, row: dict) -> list[str]:
    errs = []
    if category == "attendance" and row.get("classes_attended") is not None and row.get("classes_held") is not None:
        if row["classes_attended"] > row["classes_held"]:
            errs.append(f"classes_attended ({row['classes_attended']}) is more than classes_held ({row['classes_held']})")
    if category == "lms" and row.get("assignments_submitted") is not None and row.get("assignments_due") is not None:
        if row["assignments_submitted"] > row["assignments_due"]:
            errs.append("assignments_submitted is more than assignments_due")
    if category == "internal_marks" and row.get("marks") is not None and row.get("max_marks") is not None:
        if row["marks"] > row["max_marks"]:
            errs.append(f"marks ({row['marks']}) are more than max_marks ({row['max_marks']})")
    if category == "placement" and all(row.get(k) is None for k in ("aptitude_score", "coding_score", "mock_interview_rating")):
        errs.append("at least one of aptitude_score, coding_score or mock_interview_rating is required")
    return errs


def row_key(category: str, row: dict) -> str:
    parts = []
    for k in SCHEMAS[category].key:
        v = row.get(k)
        parts.append(str(v).lower() if k == "activity_name" else str(v))
    return "|".join(parts)


def template_csv(category: str) -> str:
    s = SCHEMAS[category]
    cols = [f.name for f in s.fields]
    return ",".join(cols) + "\n" + ",".join(str(s.example.get(c, "")) for c in cols) + "\n"


def describe() -> list[dict]:
    return [{
        "category": s.category, "label": s.label, "description": s.description, "key": s.key,
        "fields": [{"name": f.name, "type": f.kind, "required": f.required, "min": f.lo, "max": f.hi,
                    "allowed": f.allowed, "help": f.help} for f in s.fields],
    } for s in SCHEMAS.values()]
