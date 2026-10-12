"""Clean the seven source systems and join them into one row per student.

Each source has its own key format and quality problems. Every fix is logged
to a data-quality report so administrators can see what was changed and why,
rather than trusting a black box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DEPT_ALIASES = {
    "computer science & engg": "CSE", "c.s.e": "CSE", "cse": "CSE", "computer science": "CSE",
    "information technology": "IT", "i.t.": "IT", "it": "IT",
    "electronics & communication": "ECE", "e.c.e": "ECE", "ece": "ECE",
    "mechanical engg": "MECH", "mechanical": "MECH", "mech": "MECH",
    "civil engg": "CIVIL", "civil": "CIVIL",
}
ID_RE = re.compile(r"^(\d{2})([A-Z]+)(\d{1,3})$")
CONCERN_KEYWORDS = {
    "Financial": ["financial", "part-time", "fees"],
    "Health": ["health", "illness"],
    "Commute": ["commute", "late for"],
    "Withdrawn": ["withdrawn", "avoids"],
    "Family": ["family"],
    "Workload": ["workload", "cope", "dropping"],
}
ATTENDANCE_RULE = 75.0  # minimum % for exam eligibility at most Indian universities


@dataclass
class QualityLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, source: str, issue: str, rows: int, action: str) -> None:
        if rows:
            self.entries.append({"source": source, "issue": issue, "rows": int(rows), "action": action})


def canonical_id(raw) -> str | None:
    """Map any of the observed roll-number spellings to e.g. '24CSE007'."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().upper()
    s = s.split("@")[0]
    s = re.sub(r"[\s\-_/]", "", s)
    m = ID_RE.match(s)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}{int(m.group(3)):03d}"


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).str.strip(), errors="coerce")


def _read(src: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(src / f"{name}.csv")


def integrate(src: Path) -> tuple[pd.DataFrame, QualityLog, dict]:
    log = QualityLog()
    lineage: dict[str, dict] = {}

    # ---- 1. Student Information System (master list) ------------------------
    sis = _read(src, "sis_academic_records")
    n0 = len(sis)
    sis["student_id"] = sis["Roll No"].map(canonical_id)
    sis = sis.drop_duplicates()
    log.add("SIS", "Exact duplicate rows from re-import", n0 - len(sis), "Dropped duplicates")
    sis = sis.drop_duplicates("student_id", keep="last")
    sis["dept"] = sis["Department"].str.strip().str.lower().map(DEPT_ALIASES)
    log.add("SIS", "Inconsistent department labels (e.g. 'C.S.E', 'Computer Science')",
            (sis["Department"].str.strip() != sis["dept"]).sum(), "Mapped to 5 standard codes")
    upper = sis["Student Name"].str.isupper().sum()
    sis["name"] = sis["Student Name"].str.title()
    log.add("SIS", "Names in ALL CAPS", upper, "Converted to title case")
    sis["cgpa"] = pd.to_numeric(sis["CGPA"], errors="coerce")
    sgpa_cols = [f"SGPA_S{i}" for i in range(1, 7)]
    missing_cgpa = sis["cgpa"].isna()
    sis.loc[missing_cgpa, "cgpa"] = sis.loc[missing_cgpa, sgpa_cols].mean(axis=1).round(2)
    log.add("SIS", "CGPA recorded as 'NA'", missing_cgpa.sum(), "Recomputed from semester SGPAs")
    sis = sis.rename(columns={"Active Backlogs": "backlogs", "Current Year": "year", "Gender": "gender"})
    sis["hosteller"] = sis["Hosteller"].eq("Y")

    def sgpa_list(row):
        return [float(v) for v in row[sgpa_cols] if pd.notna(v)]

    sis["sgpa_history"] = sis.apply(sgpa_list, axis=1)
    sis["sgpa_last"] = sis["sgpa_history"].map(lambda h: h[-1])
    sis["sgpa_trend"] = sis["sgpa_history"].map(lambda h: round(h[-1] - np.mean(h[:-1]), 2) if len(h) > 1 else 0.0)
    base = sis[["student_id", "name", "dept", "year", "gender", "hosteller", "cgpa", "backlogs",
                "sgpa_history", "sgpa_last", "sgpa_trend"]].set_index("student_id")
    master = set(base.index)
    lineage["SIS academic records"] = {"rows": n0, "students": len(base), "key": "Roll No"}

    def match_report(name: str, ids: pd.Series, raw_rows: int, key: str) -> None:
        uniq = set(ids.dropna())
        lineage[name] = {"rows": raw_rows, "students": len(uniq & master), "key": key,
                         "unmatched": len(uniq - master)}

    # ---- 2. Internal assessment marks ---------------------------------------
    marks = _read(src, "exam_internal_marks")
    marks["student_id"] = marks["roll_no"].map(canonical_id)
    marks["pct"] = marks["internal_marks"] / marks["max_marks"] * 100
    g = marks.groupby("student_id")
    weakest = marks.loc[g["pct"].idxmin(), ["student_id", "subject", "pct"]].set_index("student_id")
    acad = pd.DataFrame({
        "internal_pct": g["pct"].mean().round(1),
        "subjects_below_40": g["pct"].apply(lambda p: int((p < 40).sum())),
        "weakest_subject": weakest["subject"],
        "weakest_subject_pct": weakest["pct"].round(1),
    })
    match_report("Internal assessment marks", marks["student_id"], len(marks), "roll_no")

    # ---- 3. Biometric attendance --------------------------------------------
    att = _read(src, "biometric_attendance")
    att["student_id"] = att["RollNo"].map(canonical_id)
    log.add("Attendance", "Roll numbers in mixed formats ('24-cse-007', ' 24CSE007 ')",
            (att["RollNo"] != att["student_id"]).sum(), "Normalised to canonical roll number")
    over = att["Classes_Attended"] > att["Classes_Held"]
    att.loc[over, "Classes_Attended"] = att.loc[over, "Classes_Held"]
    log.add("Attendance", "Attended > held (biometric glitch)", over.sum(), "Capped at classes held")
    by_subj = att.groupby(["student_id", "Subject"])[["Classes_Held", "Classes_Attended"]].sum()
    by_subj["pct"] = by_subj["Classes_Attended"] / by_subj["Classes_Held"] * 100
    by_month = att.groupby(["student_id", "Month"])[["Classes_Held", "Classes_Attended"]].sum()
    by_month["pct"] = by_month["Classes_Attended"] / by_month["Classes_Held"] * 100
    tot = att.groupby("student_id")[["Classes_Held", "Classes_Attended"]].sum()
    subj_pct = by_subj["pct"].unstack()
    month_pct = by_month["pct"].unstack().sort_index(axis=1)
    attendance = pd.DataFrame({
        "attendance_pct": (tot["Classes_Attended"] / tot["Classes_Held"] * 100).round(1),
        "attendance_min_subject_pct": subj_pct.min(axis=1).round(1),
        "attendance_min_subject": subj_pct.idxmin(axis=1),
        "subjects_below_75_att": (subj_pct < ATTENDANCE_RULE).sum(axis=1),
        "attendance_trend": (month_pct.iloc[:, -1] - month_pct.iloc[:, 0]).round(1),
        "attendance_monthly": month_pct.round(1).apply(list, axis=1),
    })
    match_report("Biometric attendance", att["student_id"], len(att), "RollNo")

    # ---- 4. LMS -------------------------------------------------------------
    lms = _read(src, "lms_weekly_activity")
    lms["student_id"] = lms["user_email"].map(canonical_id)
    log.add("LMS", "Keyed by email, not roll number", lms["student_id"].nunique(), "Roll number parsed from email")
    no_quiz = lms["quiz_score"].isna().sum()
    log.add("LMS", "Weeks with no quiz attempt", no_quiz, "Excluded from quiz average (not scored as 0)")
    lms = lms.sort_values(["student_id", "week"])
    g = lms.groupby("student_id")
    weekly = lms.pivot(index="student_id", columns="week", values="logins")
    first4 = weekly[[1, 2, 3, 4]].mean(axis=1)
    last4 = weekly.iloc[:, -4:].mean(axis=1)
    lmsf = pd.DataFrame({
        "lms_logins_per_week": g["logins"].mean().round(2),
        "lms_completion_pct": (g["assignments_submitted"].sum() / g["assignments_due"].sum() * 100).round(1),
        "lms_quiz_avg": g["quiz_score"].mean().round(1),
        "lms_login_trend": (last4 / first4.clip(lower=0.5)).round(2).clip(upper=2.0),
        "lms_weekly_logins": weekly.apply(list, axis=1),
    })
    match_report("LMS weekly activity", lms["student_id"], len(lms), "user_email")

    # ---- 5. Engagement ------------------------------------------------------
    eng = _read(src, "engagement_activity_log")
    eng["student_id"] = eng["student_ref"].map(canonical_id)
    log.add("Engagement", "Un-padded roll numbers ('24CSE7')",
            (eng["student_ref"].str.strip().str.upper() != eng["student_id"]).sum(), "Zero-padded to canonical form")
    upper_types = (eng["activity_type"] != eng["activity_type"].str.lower()).sum()
    eng["activity_type"] = eng["activity_type"].str.lower()
    log.add("Engagement", "Inconsistent activity-type casing", upper_types, "Lower-cased")
    counts = eng.pivot_table(index="student_id", columns="activity_type", values="activity_name",
                             aggfunc="count", fill_value=0)
    engagement = counts.reindex(columns=["event", "club", "hackathon", "certification"], fill_value=0)
    engagement.columns = ["events", "clubs", "hackathons", "certifications"]
    match_report("Engagement activity log", eng["student_id"], len(eng), "student_ref")

    # ---- 6. Placement cell --------------------------------------------------
    pl = _read(src, "placement_cell_assessments")
    pl["student_id"] = pl["reg_no"].map(canonical_id)
    pl = pl.sort_values(["student_id", "attempt_date"])
    multi = pl.duplicated("student_id", keep="last").sum()
    attempts = pl.groupby("student_id").size()
    log.add("Placement", "Multiple test attempts per student", multi, "Kept most recent attempt")
    pl = pl.drop_duplicates("student_id", keep="last").set_index("student_id")
    resume_vals = pl["resume_reviewed"].fillna("").astype(str).str.strip().str.lower()
    log.add("Placement", "Resume flag as Yes/yes/Y/No/N/blank", (~resume_vals.isin(["yes", "no"])).sum(),
            "Standardised to boolean")
    placement = pd.DataFrame({
        "aptitude_score": pl["aptitude_score"],
        "coding_score": pl["coding_score"],
        "mock_interview_rating": pl["mock_interview_rating"],
        "resume_reviewed": resume_vals.isin(["yes", "y"]),
        "placement_attempts": attempts,
    })
    match_report("Placement cell assessments", pl.index.to_series(), len(pl) + multi, "reg_no")

    # ---- 7. Skills ----------------------------------------------------------
    sk = _read(src, "skills_assessment")
    sk["student_id"] = sk["roll_no"].map(canonical_id)
    skill_cols = ["technical_skill", "communication", "teamwork", "problem_solving"]
    pct_strings = sk[skill_cols].astype(str).apply(lambda c: c.str.contains("%")).any(axis=1).sum()
    for c in skill_cols:
        sk[c] = _to_number(sk[c])
    log.add("Skills", "Scores stored as text with '%'", pct_strings, "Parsed to numbers")
    skills = sk.set_index("student_id")[skill_cols]
    match_report("Skills assessment", sk["student_id"], len(sk), "roll_no")

    # ---- 8. Feedback --------------------------------------------------------
    fb = _read(src, "student_feedback_survey")
    fb["student_id"] = fb["roll"].map(canonical_id)
    fb = fb.set_index("student_id")

    def tags(note: str) -> list[str]:
        n = str(note).lower()
        return [t for t, kws in CONCERN_KEYWORDS.items() if any(k in n for k in kws)]

    feedback = pd.DataFrame({
        "satisfaction": fb["satisfaction_1to5"],
        "stress": fb["stress_1to5"],
        "mentor_rating": fb["mentor_rating_1to5"],
        "mentor_remark": fb["mentor_remark"],
        "concern_tags": fb["mentor_remark"].map(tags),
    })
    match_report("Feedback survey", fb.index.to_series(), len(fb), "roll")

    # ---- Join ---------------------------------------------------------------
    df = base.join([acad, attendance, lmsf, engagement, placement, skills, feedback], how="left")
    df.index.name = "student_id"

    for c in ["events", "clubs", "hackathons", "certifications"]:
        df[c] = df[c].fillna(0).astype(int)

    df["survey_responded"] = df["satisfaction"].notna()
    no_survey = (~df["survey_responded"]).sum()
    for c, neutral in (("satisfaction", 3), ("stress", 3)):
        df[c] = df[c].fillna(neutral)
    df["mentor_rating"] = df["mentor_rating"].fillna(df.groupby("dept")["mentor_rating"].transform("median"))
    df["mentor_remark"] = df["mentor_remark"].fillna("")
    df["concern_tags"] = df["concern_tags"].map(lambda t: t if isinstance(t, list) else [])
    log.add("Feedback", "Students who skipped the survey", no_survey,
            "Neutral value imputed; flagged as non-response")

    df["placement_assessed"] = df["aptitude_score"].notna()
    df["placement_eligible_year"] = df["year"] >= 3
    df["placement_skipped"] = df["placement_eligible_year"] & ~df["placement_assessed"]
    df["placement_attempts"] = df["placement_attempts"].fillna(0).astype(int)
    df["resume_reviewed"] = df["resume_reviewed"].fillna(False).astype(bool)
    skipped = (df["placement_eligible_year"] & ~df["placement_assessed"]).sum()
    log.add("Placement", "3rd/4th-year students who skipped all placement tests", skipped,
            "Imputed at the 10th percentile of their department and flagged")
    for c in ["aptitude_score", "coding_score", "mock_interview_rating"]:
        p10 = df[df["placement_assessed"]].groupby("dept")[c].quantile(0.10)
        miss = df["placement_eligible_year"] & df[c].isna()
        df.loc[miss, c] = df.loc[miss, "dept"].map(p10).round(1)

    sources = [acad["internal_pct"], attendance["attendance_pct"], lmsf["lms_completion_pct"],
               skills["technical_skill"]]
    df["sources_linked"] = 1 + sum(df.index.isin(s.index) for s in sources) \
        + df.index.isin(engagement.index).astype(int) + df["placement_assessed"].astype(int) \
        + df["survey_responded"].astype(int)
    df["attendance_shortage"] = df["attendance_pct"] < ATTENDANCE_RULE

    stats = {
        "lineage": lineage,
        "students": int(len(df)),
        "avg_sources_linked": round(float(df["sources_linked"].mean()), 2),
        "raw_rows_total": int(sum(v["rows"] for v in lineage.values())),
    }
    return df.reset_index(), log, stats
