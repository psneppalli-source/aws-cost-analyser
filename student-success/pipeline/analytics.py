"""Segmentation, next-best-action recommendations and auto-generated insights."""

from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENTS = {
    "critical": {
        "label": "Critical support needed",
        "rule": "Success Score < 40, or high academic risk combined with an attendance shortage",
        "playbook": "Weekly mentor check-in, parent meeting, remedial classes and counsellor referral. HoD reviews fortnightly.",
        "owner": "Class mentor + HoD",
    },
    "disengaging": {
        "label": "Disengaging (early warning)",
        "rule": "LMS activity in the last 4 weeks < 60% of the first 4 weeks, or attendance down 10+ points since July",
        "playbook": "Mentor call within 7 days to find the cause before marks drop. Re-check LMS activity in two weeks.",
        "owner": "Class mentor",
    },
    "achiever_unready": {
        "label": "Academic achiever, placement-unready",
        "rule": "Academic pillar >= 65 but placement readiness (or skills for 2nd years) < 45",
        "playbook": "Fast-track to coding bootcamp and mock interviews. Strong grades make them easy wins for the placement cell.",
        "owner": "Training & Placement cell",
    },
    "jobready_atrisk": {
        "label": "Job-ready, academically at risk",
        "rule": "Placement readiness >= 55 but has backlogs or academic pillar < 50",
        "playbook": "Backlog-clearance plan before placement season. Most recruiters require zero active backlogs.",
        "owner": "Exam cell + T&P cell",
    },
    "thriving": {
        "label": "Thriving all-rounder",
        "rule": "Success Score >= 70",
        "playbook": "Stretch goals: research projects, competitive hackathons, and peer-mentor roles for at-risk juniors.",
        "owner": "Department",
    },
    "steady": {
        "label": "Steady middle",
        "rule": "Everyone else",
        "playbook": "Group nudges: monthly progress digest, optional skill workshops, and club participation drives.",
        "owner": "Department",
    },
}


def readiness(scores: pd.DataFrame) -> pd.Series:
    """Placement pillar where available; skills pillar as the 2nd-year proxy."""
    return scores["pillar_placement"].fillna(scores["pillar_skills"])


def segment(df: pd.DataFrame, scores: pd.DataFrame) -> pd.Series:
    ready = readiness(scores)
    acad = scores["pillar_academic"]
    seg = pd.Series("steady", index=df.index)
    rules = [
        ("thriving", scores["success_score"] >= 70),
        ("jobready_atrisk", (ready >= 55) & ((df["backlogs"] > 0) | (acad < 50))),
        ("achiever_unready", (acad >= 65) & (ready < 45)),
        ("disengaging", (df["lms_login_trend"] < 0.6) | (df["attendance_trend"] <= -10)),
        ("critical", (scores["success_score"] < 40) | ((scores["acad_tier"] == "High") & df["attendance_shortage"])),
    ]
    # Later rules take priority over earlier ones.
    for key, mask in rules:
        seg[mask] = key
    return seg


def actions(r: pd.Series) -> list[dict]:
    """Rule-based next-best actions for one student, highest priority first."""
    out = []

    def add(priority, text, owner):
        out.append({"priority": priority, "action": text, "owner": owner})

    if r["attendance_pct"] < 75:
        add(1, f"Attendance {r['attendance_pct']:.0f}% is below the 75% exam-eligibility rule. "
               "Call the student and notify parents; agree a recovery plan.", "Class mentor")
    if r["lms_login_trend"] < 0.6:
        add(1, f"LMS activity down {100 * (1 - r['lms_login_trend']):.0f}% in the last 4 weeks. "
               "Check in within 7 days.", "Class mentor")
    if r["backlogs"] > 0:
        add(2, f"{int(r['backlogs'])} active backlog(s): enrol in remedial classes for the supplementary exam.",
            "Exam cell")
    if r["weakest_subject_pct"] < 40:
        add(2, f"Remedial tutoring in {r['weakest_subject']} (internal marks {r['weakest_subject_pct']:.0f}%).",
            "Subject faculty")
    if r["lms_completion_pct"] < 60:
        add(2, f"Only {r['lms_completion_pct']:.0f}% of assignments submitted: set up a weekly submission plan.",
            "Subject faculty")
    tags = r["concern_tags"]
    if "Financial" in tags:
        add(1, "Mentor note flags financial difficulty: refer to the scholarship / fee-support cell.", "Student welfare")
    if "Health" in tags or "Withdrawn" in tags or "Workload" in tags or r["stress"] >= 5:
        add(1, "Wellbeing concern in mentor notes or survey: refer to the campus counsellor.", "Counsellor")
    if "Commute" in tags:
        add(3, "Long daily commute: explore hostel or transport support.", "Student welfare")
    if r["placement_eligible_year"]:
        if not r["placement_assessed"]:
            add(2, "Has not taken any placement test: register for the next mock drive.", "T&P cell")
        if r["coding_score"] < 40:
            add(2, f"Coding score {r['coding_score']:.0f}: enrol in the DSA practice bootcamp.", "T&P cell")
        if r["aptitude_score"] < 45:
            add(3, f"Aptitude score {r['aptitude_score']:.0f}: join the aptitude training batch.", "T&P cell")
        if r["mock_interview_rating"] < 2.5:
            add(3, "Weak mock interview: schedule two more mock interviews with feedback.", "T&P cell")
    if r["communication"] < 45:
        add(3, "Communication skills workshop (group discussion and presentation practice).", "Soft-skills trainer")
    if r["events"] + r["clubs"] == 0:
        add(3, "No campus engagement this year: nudge to join a club or peer-learning group.", "Class mentor")
    if not out:
        add(3, "On track. Consider for peer-mentor role or advanced project work.", "Department")
    out.sort(key=lambda a: a["priority"])
    return out[:5]


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def insights(df: pd.DataFrame) -> list[dict]:
    """Findings that only appear once the sources are joined."""
    res = []
    hi_acad = df["acad_tier"] == "High"

    short = df["attendance_shortage"]
    r1, r0 = hi_acad[short].mean(), hi_acad[~short].mean()
    res.append({
        "kind": "risk",
        "title": f"Attendance shortage multiplies academic risk by {r1 / max(r0, 1e-9):.1f}x",
        "detail": f"{_pct(r1)} of the {short.sum()} students below 75% attendance are high academic risk, "
                  f"vs {_pct(r0)} of everyone else. Attendance is the earliest lever faculty control.",
    })

    dis = df["segment"] == "disengaging"
    dis_all = (df["lms_login_trend"] < 0.6) | (df["attendance_trend"] <= -10)
    ok_cgpa = (df.loc[dis_all, "cgpa"] >= 7).mean()
    res.append({
        "kind": "early-warning",
        "title": f"{dis_all.sum()} students are quietly disengaging; {_pct(ok_cgpa)} still have CGPA 7+",
        "detail": "Their LMS logins or attendance have fallen sharply since July. A CGPA-only report would miss "
                  "most of them until end-semester results.",
    })

    au = df[df["segment"] == "achiever_unready"]
    elig = df[df["placement_eligible_year"] & df["placement_assessed"]]
    if len(au):
        au_e = au[au["placement_eligible_year"]]
        detail = f"Average CGPA {au['cgpa'].mean():.1f}."
        if len(au_e):
            detail += (f" Among 3rd/4th years in this group, coding score averages {au_e['coding_score'].mean():.0f} vs "
                       f"{elig['coding_score'].mean():.0f} campus-wide, and {_pct((~au_e['placement_assessed']).mean())} "
                       f"have skipped placement tests.")
        res.append({
            "kind": "segment",
            "title": f"{len(au)} high-CGPA students are not placement-ready",
            "detail": detail + " Targeted bootcamps here convert easily into placement offers.",
        })

    pe = df[df["placement_eligible_year"]]
    by_dept = pe.groupby("dept")["place_tier"].apply(lambda t: (t == "High").mean()).sort_values()
    worst = by_dept.index[-1]
    # Which readiness indicator lags most in that department (in campus SD units)?
    cols = {"aptitude_score": "aptitude", "coding_score": "coding", "mock_interview_rating": "mock-interview",
            "communication": "communication", "technical_skill": "technical-skill"}
    gaps = {c: (pe.loc[pe["dept"] == worst, c].mean() - pe[c].mean()) / pe[c].std() for c in cols}
    lag = min(gaps, key=gaps.get)
    res.append({
        "kind": "department",
        "title": f"{worst} has the highest placement risk: {_pct(by_dept.iloc[-1])} of 3rd/4th years",
        "detail": f"vs {_pct(by_dept.iloc[0])} in {by_dept.index[0]}. The biggest gap is in {cols[lag]} scores "
                  f"({pe.loc[pe['dept'] == worst, lag].mean():.0f} vs {pe[lag].mean():.0f} campus average), "
                  "so that is where a department-level programme should start.",
    })

    hk = elig["hackathons"] > 0
    if hk.any() and (~hk).any():
        res.append({
            "kind": "driver",
            "title": f"Hackathon participants score {elig[hk]['coding_score'].mean() - elig[~hk]['coding_score'].mean():.0f} "
                     "points higher in coding tests",
            "detail": f"Only {_pct(hk.mean())} of assessed 3rd/4th years have taken part in a hackathon. "
                      "Running internal hackathons is a cheap readiness lever.",
        })

    concern = df["concern_tags"].map(len) > 0
    fin = df["concern_tags"].map(lambda t: "Financial" in t)
    res.append({
        "kind": "wellbeing",
        "title": f"{concern.sum()} mentor notes flag a personal concern; {_pct(hi_acad[concern].mean())} of these students are high academic risk",
        "detail": f"{fin.sum()} mention financial difficulty. Mining free-text mentor remarks surfaces causes "
                  "that marks and attendance cannot explain.",
    })

    skipped = df["placement_skipped"]
    took = df["placement_eligible_year"] & ~skipped
    res.append({
        "kind": "placement",
        "title": f"{skipped.sum()} 3rd/4th-year students have never taken a placement test",
        "detail": f"{_pct((df.loc[skipped, 'place_tier'] == 'High').mean())} of them are high placement risk vs "
                  f"{_pct((df.loc[took, 'place_tier'] == 'High').mean())} of those who did. Avoiding tests is an early "
                  "signal; the T&P cell should reach out before the next drive.",
    })
    return res
