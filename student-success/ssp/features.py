"""Turn canonical records into per-student, per-review-period indicators.

Missing data stays missing (None). It is never silently turned into a zero:
the scoring engine excludes it, reports it, and lowers data coverage.
Every indicator remembers the source, period, file and upload it came from.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from . import records

CONCERN_KEYWORDS = {
    "Financial": ["financial", "part-time", "fees"],
    "Health": ["health", "illness", "hospital"],
    "Commute": ["commute", "late for"],
    "Withdrawn": ["withdrawn", "avoids", "isolated"],
    "Family": ["family"],
    "Workload": ["workload", "cope", "dropping a subject"],
}


def term_key(term: str) -> tuple[int, int]:
    y, half = term.split("-")
    return int(y), (0 if half == "EVEN" else 1)  # EVEN (Jan-May) comes before ODD (Jul-Nov) in a year


def year_of_study(admission_year: int, period: str) -> int:
    y, half = period.split("-")
    academic_year_start = int(y) if half == "ODD" else int(y) - 1
    return academic_year_start - admission_year + 1


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


class Index:
    """Records grouped by student once per recalculation."""

    CATEGORIES = ["students", "academic", "internal_marks", "attendance", "lms", "engagement", "placement", "skills", "feedback"]

    def __init__(self):
        self.by = {c: defaultdict(list) for c in self.CATEGORIES}
        self.loaded = set()
        meta = records.meta().get("categories", {})
        self.meta = meta
        for c in self.CATEGORIES:
            rows = records.load(c)
            if c in meta:
                self.loaded.add(c)
            for r in rows.values():
                self.by[c][r["student_id"]].append(r)

    def rows(self, category: str, sid: str) -> list[dict]:
        return self.by[category].get(sid, [])


def _src(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    latest = max(rows, key=lambda r: r.get("_updated", ""))
    return {"upload": latest.get("_upload"), "file": latest.get("_file"), "period": latest.get("_period"),
            "updated": latest.get("_updated")}


def compute(idx: Index, student: dict, period: dict, cfg: dict) -> dict | None:
    """Indicators for one student in one review period, or None if not enrolled then."""
    sid = student["student_id"]
    course = cfg["courses"].get(student["course"], {"years": 4, "placement_from_year": 3})
    year = year_of_study(student["admission_year"], period["id"])
    if year < 1 or year > course["years"]:
        return None
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    f: dict = {"year": year, "placement_year": year >= course["placement_from_year"]}
    src: dict = {}
    series: dict = {}
    detail: dict = {}

    # Academic results declared before this term
    acad = sorted((r for r in idx.rows("academic", sid) if term_key(r["term"]) < term_key(period["id"])),
                  key=lambda r: term_key(r["term"]))
    if acad:
        last = acad[-1]
        f["cgpa"], f["backlogs"] = last["cgpa"], last["backlogs"]
        sg = [r["sgpa"] for r in acad if r.get("sgpa") is not None]
        f["sgpa_trend"] = _r(sg[-1] - mean(sg[:-1]), 2) if len(sg) >= 2 else None
        series["sgpa"] = [{"term": r["term"], "sgpa": r.get("sgpa"), "cgpa": r["cgpa"]} for r in acad]
        src["academic"] = _src(acad) | {"as_of_term": last["term"]}
    else:
        f["cgpa"] = f["backlogs"] = f["sgpa_trend"] = None

    # Internal marks this term
    im = [r for r in idx.rows("internal_marks", sid) if r["term"] == period["id"]]
    if im:
        pcts = {r["subject"]: r["marks"] / r["max_marks"] * 100 for r in im}
        weakest = min(pcts, key=pcts.get)
        f["internal_pct"] = _r(mean(pcts.values()))
        f["weakest_subject"], f["weakest_subject_pct"] = weakest, _r(pcts[weakest])
        detail["subjects"] = {k: _r(v) for k, v in sorted(pcts.items())}
        src["internal_marks"] = _src(im)
    else:
        f["internal_pct"] = f["weakest_subject_pct"] = f["weakest_subject"] = None

    # Attendance within the review window
    att = [r for r in idx.rows("attendance", sid) if start.isoformat()[:7] <= r["month"] <= end.isoformat()[:7]]
    if att:
        held = sum(r["classes_held"] for r in att)
        f["attendance_pct"] = _r(sum(r["classes_attended"] for r in att) / held * 100)
        subj, mon = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for r in att:
            subj[r["subject"]][0] += r["classes_attended"]
            subj[r["subject"]][1] += r["classes_held"]
            mon[r["month"]][0] += r["classes_attended"]
            mon[r["month"]][1] += r["classes_held"]
        sp = {k: v[0] / v[1] * 100 for k, v in subj.items()}
        mp = {k: v[0] / v[1] * 100 for k, v in sorted(mon.items())}
        low = min(sp, key=sp.get)
        f["attendance_min_subject"], f["attendance_min_subject_pct"] = low, _r(sp[low])
        f["subjects_below_75"] = sum(1 for v in sp.values() if v < 75)
        months = list(mp)
        f["attendance_trend"] = _r(mp[months[-1]] - mp[months[0]]) if len(months) >= 2 else None
        series["attendance"] = [{"month": k, "pct": _r(v)} for k, v in mp.items()]
        detail["attendance_by_subject"] = {k: _r(v) for k, v in sorted(sp.items())}
        src["attendance"] = _src(att) | {"latest_month": months[-1]}
    else:
        for k in ("attendance_pct", "attendance_min_subject_pct", "attendance_min_subject", "attendance_trend", "subjects_below_75"):
            f[k] = None

    # LMS within the review window
    lms = sorted((r for r in idx.rows("lms", sid) if start.isoformat() <= r["week_start"] <= end.isoformat()),
                 key=lambda r: r["week_start"])
    if lms:
        due = sum(r["assignments_due"] for r in lms)
        f["lms_completion_pct"] = _r(sum(r["assignments_submitted"] for r in lms) / due * 100) if due else None
        f["lms_logins_per_week"] = _r(mean(r["logins"] for r in lms), 2)
        q = [r["quiz_score"] for r in lms if r.get("quiz_score") is not None]
        f["lms_quiz_avg"] = _r(mean(q)) if q else None
        logins = [r["logins"] for r in lms]
        f["lms_login_trend"] = _r(min(2.0, mean(logins[-4:]) / max(mean(logins[:4]), 0.5)), 2) if len(logins) >= 8 else None
        series["lms"] = [{"week": r["week_start"], "logins": r["logins"]} for r in lms]
        src["lms"] = _src(lms) | {"latest_week": lms[-1]["week_start"]}
    else:
        for k in ("lms_completion_pct", "lms_logins_per_week", "lms_quiz_avg", "lms_login_trend"):
            f[k] = None

    # Engagement: an activity log, so "no rows" means zero once the log has been loaded at all
    lb = timedelta(days=cfg["lookback_days"]["engagement"])
    if "engagement" in idx.loaded:
        eng = [r for r in idx.rows("engagement", sid) if end - lb < date.fromisoformat(r["activity_date"]) <= end]
        f["events"] = sum(r["activity_type"] == "event" for r in eng)
        f["clubs"] = len({r["activity_name"].lower() for r in eng if r["activity_type"] == "club"})
        f["projects_hackathons"] = sum(r["activity_type"] in ("project", "hackathon") for r in eng)
        f["certifications"] = sum(r["activity_type"] == "certification" for r in eng)
        f["portfolio_items"] = f["projects_hackathons"] + f["certifications"]
        detail["activities"] = sorted(({"date": r["activity_date"], "type": r["activity_type"], "name": r["activity_name"]}
                                       for r in eng), key=lambda a: a["date"], reverse=True)[:12]
        m = idx.meta.get("engagement", {})
        src["engagement"] = _src(idx.rows("engagement", sid)) or {
            "file": m.get("file"), "period": m.get("period"), "upload": m.get("upload_id"), "updated": m.get("updated_at"),
            "note": "no activities recorded for this student"}
    else:
        for k in ("events", "clubs", "projects_hackathons", "certifications", "portfolio_items"):
            f[k] = None

    # Placement: latest attempt (per field) within the look-back window
    f["aptitude_score"] = f["coding_score"] = f["mock_interview_rating"] = None
    f["resume_reviewed"], f["placement_tests"] = None, 0
    if f["placement_year"]:
        lb = timedelta(days=cfg["lookback_days"]["placement"])
        pl = sorted((r for r in idx.rows("placement", sid) if end - lb < date.fromisoformat(r["assessment_date"]) <= end),
                    key=lambda r: r["assessment_date"])
        f["placement_tests"] = len(pl)
        for k in ("aptitude_score", "coding_score", "mock_interview_rating", "resume_reviewed"):
            vals = [r[k] for r in pl if r.get(k) is not None]
            f[k] = vals[-1] if vals else None
        if pl:
            series["placement"] = [{"date": r["assessment_date"], "aptitude": r.get("aptitude_score"),
                                    "coding": r.get("coding_score"), "mock": r.get("mock_interview_rating")} for r in pl]
            src["placement"] = _src([pl[-1]]) | {"latest_test": pl[-1]["assessment_date"]}  # the attempt the scores came from

    # Skills: latest assessment within the look-back window
    lb = timedelta(days=cfg["lookback_days"]["skills"])
    sk = sorted((r for r in idx.rows("skills", sid) if end - lb < date.fromisoformat(r["assessed_on"]) <= end),
                key=lambda r: r["assessed_on"])
    for k in ("technical", "communication", "teamwork", "problem_solving"):
        f[k] = sk[-1].get(k) if sk else None
    if sk:
        src["skills"] = _src([sk[-1]]) | {"assessed_on": sk[-1]["assessed_on"]}

    # Feedback this term
    fb = [r for r in idx.rows("feedback", sid) if r["term"] == period["id"]]
    if fb:
        r = fb[-1]
        f["satisfaction"], f["stress"], f["faculty_rating"] = r.get("satisfaction"), r.get("stress"), r.get("faculty_rating")
        remark = r.get("faculty_remark") or ""
        tags = [t for t, kws in CONCERN_KEYWORDS.items() if any(k in remark.lower() for k in kws)]
        detail["faculty_remark"], detail["concern_tags"] = remark, tags
        f["wellbeing_concern"] = bool(tags) or (f["stress"] or 0) >= 4 or (f["satisfaction"] or 5) <= 2
        src["feedback"] = _src(fb)
    else:
        f["satisfaction"] = f["stress"] = f["faculty_rating"] = f["wellbeing_concern"] = None

    return {"features": f, "sources": src, "series": series, "detail": detail}
