"""Student Success Score: a transparent, weighted composite of 7 pillars.

Each raw indicator is mapped to 0-100 with fixed, documented anchors (not
percentiles), so a student's score means the same thing every semester and
does not move just because classmates improved. Indicators are averaged into
pillars, and pillars are combined with fixed weights.

Explainability: every student's score is decomposed into per-indicator
contributions relative to the campus-average student, so

    score = baseline + sum(contributions)

and the dashboard can show exactly which indicators lift or drag the score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# indicator -> (pillar, label, raw column, worst anchor, best anchor, weight within pillar)
INDICATORS = [
    ("academic", "CGPA", "cgpa", 5.0, 9.0, 0.45),
    ("academic", "Active backlogs", "backlogs", 4, 0, 0.25),
    ("academic", "Current internal marks", "internal_pct", 35, 85, 0.15),
    ("academic", "SGPA trend (last sem vs earlier)", "sgpa_trend", -1.0, 0.5, 0.15),
    ("attendance", "Overall attendance", "attendance_pct", 60, 95, 0.6),
    ("attendance", "Weakest-subject attendance", "attendance_min_subject_pct", 50, 90, 0.2),
    ("attendance", "Attendance trend (Sep vs Jul)", "attendance_trend", -15, 5, 0.2),
    ("lms", "Assignment completion", "lms_completion_pct", 40, 100, 0.4),
    ("lms", "LMS logins per week", "lms_logins_per_week", 1, 7, 0.2),
    ("lms", "Quiz average", "lms_quiz_avg", 40, 85, 0.2),
    ("lms", "LMS activity trend (last 4 wks vs first 4)", "lms_login_trend", 0.4, 1.1, 0.2),
    ("engagement", "Events attended", "events", 0, 6, 0.3),
    ("engagement", "Clubs", "clubs", 0, 2, 0.2),
    ("engagement", "Hackathons", "hackathons", 0, 2, 0.25),
    ("engagement", "Certifications", "certifications", 0, 3, 0.25),
    ("placement", "Aptitude score", "aptitude_score", 30, 85, 0.35),
    ("placement", "Coding score", "coding_score", 20, 80, 0.4),
    ("placement", "Mock interview rating", "mock_interview_rating", 1.5, 4.5, 0.25),
    ("skills", "Technical skill", "technical_skill", 30, 90, 0.5),
    ("skills", "Communication", "communication", 30, 90, 0.25),
    ("skills", "Problem solving", "problem_solving", 30, 90, 0.25),
    ("feedback", "Student satisfaction", "satisfaction", 1, 5, 0.5),
    ("feedback", "Mentor rating", "mentor_rating", 1, 5, 0.5),
]

PILLARS = {
    "academic": ("Academic", 0.30),
    "attendance": ("Attendance", 0.15),
    "lms": ("LMS", 0.15),
    "placement": ("Placement readiness", 0.15),
    "skills": ("Skills", 0.10),
    "engagement": ("Engagement", 0.10),
    "feedback": ("Feedback & wellbeing", 0.05),
}

BANDS = [(70, "Thriving"), (55, "On track"), (40, "Needs attention"), (0, "Critical")]


def indicator_score(values: pd.Series, worst: float, best: float) -> pd.Series:
    return ((values - worst) / (best - worst) * 100).clip(0, 100)


def band(score: float) -> str:
    for cut, label in BANDS:
        if score >= cut:
            return label
    return BANDS[-1][1]


def effective_weights(df: pd.DataFrame) -> pd.DataFrame:
    """Per-student indicator weights summing to 1.

    2nd-year students have no placement data yet; their placement pillar
    weight is redistributed proportionally across the other pillars rather
    than scoring them as zero.
    """
    w = pd.DataFrame(index=df.index)
    for pillar, _label, col, _lo, _hi, wi in INDICATORS:
        w[col] = PILLARS[pillar][1] * wi
    no_place = ~df["placement_eligible_year"]
    place_cols = [i[2] for i in INDICATORS if i[0] == "placement"]
    w.loc[no_place, place_cols] = 0.0
    return w.div(w.sum(axis=1), axis=0)


def compute(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (scores, contributions, metadata)."""
    ind = pd.DataFrame(index=df.index)
    for _p, _l, col, lo, hi, _w in INDICATORS:
        ind[col] = indicator_score(df[col].astype(float), lo, hi)
    ind = ind.fillna(0)

    out = pd.DataFrame(index=df.index)
    for pillar in PILLARS:
        cols = [(c, w) for p, _l, c, _lo, _hi, w in INDICATORS if p == pillar]
        total = sum(w for _c, w in cols)
        out[f"pillar_{pillar}"] = sum(ind[c] * w for c, w in cols) / total
    out.loc[~df["placement_eligible_year"], "pillar_placement"] = np.nan

    w = effective_weights(df)
    out["success_score"] = (ind * w).sum(axis=1).round(1)
    out["score_band"] = out["success_score"].map(band)

    # Contributions vs. the campus-average student (per indicator).
    mean_ind = ind.mean()
    contrib = (ind - mean_ind) * w
    out["score_baseline"] = (w * mean_ind).sum(axis=1).round(1)

    meta = {
        "indicators": [
            {"pillar": p, "pillar_label": PILLARS[p][0], "label": l, "column": c,
             "worst": lo, "best": hi, "weight_in_pillar": wi,
             "weight_overall": round(PILLARS[p][1] * wi, 4)}
            for p, l, c, lo, hi, wi in INDICATORS
        ],
        "pillars": [{"key": k, "label": v[0], "weight": v[1]} for k, v in PILLARS.items()],
        "bands": [{"min": c, "label": l} for c, l in BANDS],
    }
    return out, contrib, meta


LABELS = {c: l for _p, l, c, *_ in INDICATORS}
PILLAR_OF = {c: p for p, _l, c, *_ in INDICATORS}
