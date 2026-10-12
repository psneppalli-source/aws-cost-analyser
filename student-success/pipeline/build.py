"""End-to-end pipeline: raw sources -> unified view -> scores, risk, segments -> dashboard data.

Run: python -m pipeline.build   (add --regenerate to rebuild the synthetic raw data first)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import analytics, models, scoring
from .integrate import integrate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
HIST = RAW / "historical_batch_2022"
PROCESSED = ROOT / "data" / "processed"
DASHBOARD_DATA = ROOT / "dashboard" / "data.js"

ACAD_THRESHOLDS = {"high": 0.5, "medium": 0.25}
PLACE_THRESHOLDS = {"high": 0.6, "medium": 0.35}


def _r(x, nd=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd)


def train_models() -> tuple[models.LogisticModel, models.LogisticModel, dict]:
    hist, _, _ = integrate(HIST)
    outcomes = pd.read_csv(HIST / "graduation_outcomes.csv")
    hist = hist.merge(outcomes, left_on="student_id", right_on="roll_no")
    y_acad = hist["academic_outcome_poor"].to_numpy()
    y_place = 1 - hist["placed_within_6_months"].to_numpy()
    m_acad = models.fit("academic", hist, y_acad, models.ACADEMIC_FEATURES, **ACAD_THRESHOLDS)
    m_place = models.fit("placement", hist, y_place, models.PLACEMENT_FEATURES, **PLACE_THRESHOLDS)

    # Validate the (hand-weighted) Success Score against real outcomes too.
    s, _, _ = scoring.compute(hist)
    hist["band"] = s["score_band"]
    by_band = []
    for _cut, label in scoring.BANDS:
        g = hist[hist["band"] == label]
        by_band.append({"band": label, "students": int(len(g)),
                        "poor_academic_rate": _r(g["academic_outcome_poor"].mean(), 3) if len(g) else None,
                        "placed_rate": _r(g["placed_within_6_months"].mean(), 3) if len(g) else None})
    validation = {
        "historical_students": int(len(hist)),
        "score_auc_academic": round(models.auc(y_acad, -s["success_score"].to_numpy()), 3),
        "score_auc_placement": round(models.auc(y_place, -s["success_score"].to_numpy()), 3),
        "by_band": by_band,
    }
    return m_acad, m_place, validation


def build() -> dict:
    df, qlog, integ = integrate(RAW)
    m_acad, m_place, validation = train_models()

    scores, contrib, score_meta = scoring.compute(df)
    df = df.join(scores)
    df["acad_risk"] = m_acad.predict(df)
    df["acad_tier"] = [models.tier(p, m_acad) for p in df["acad_risk"]]
    df["place_risk"] = m_place.predict(df)
    df["place_tier"] = [models.tier(p, m_place) for p in df["place_risk"]]
    df["place_risk"] = df["place_risk"].where(df["placement_eligible_year"])
    df["place_tier"] = df["place_tier"].where(df["placement_eligible_year"], None).astype(object)
    df["segment"] = analytics.segment(df, df)
    df["readiness"] = analytics.readiness(df)
    acad_c = m_acad.contributions(df)
    place_c = m_place.contributions(df)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    list_cols = ["sgpa_history", "attendance_monthly", "lms_weekly_logins", "concern_tags"]
    flat = df.drop(columns=list_cols)
    flat.round(3).to_csv(PROCESSED / "unified_student_view.csv", index=False)

    students = []
    for i, r in df.iterrows():
        flags = []
        if r["acad_tier"] == "High":
            flags.append("Academic risk")
        if r["place_tier"] == "High":
            flags.append("Placement risk")
        if r["attendance_shortage"]:
            flags.append("Attendance < 75%")
        if r["lms_login_trend"] < 0.6:
            flags.append("LMS drop-off")
        if r["backlogs"] > 0:
            flags.append("Backlogs")
        if r["concern_tags"]:
            flags.append("Wellbeing concern")

        score_drivers = sorted(
            ({"col": c, "v": _r(contrib.at[i, c], 2)} for c in contrib.columns if abs(contrib.at[i, c]) >= 0.05),
            key=lambda d: d["v"])
        acad_drivers = sorted(({"col": c, "v": _r(acad_c.at[i, c], 2)} for c in acad_c.columns),
                              key=lambda d: -d["v"])
        place_drivers = (sorted(({"col": c, "v": _r(place_c.at[i, c], 2)} for c in place_c.columns),
                                key=lambda d: -d["v"]) if r["placement_eligible_year"] else [])
        students.append({
            "id": r["student_id"], "name": r["name"], "dept": r["dept"], "year": int(r["year"]),
            "gender": r["gender"], "hosteller": bool(r["hosteller"]),
            "score": _r(r["success_score"]), "band": r["score_band"], "baseline": _r(r["score_baseline"]),
            "pillars": {p: _r(r[f"pillar_{p}"]) for p in scoring.PILLARS},
            "readiness": _r(r["readiness"]),
            "acad_risk": _r(r["acad_risk"], 3), "acad_tier": r["acad_tier"],
            "place_risk": _r(r["place_risk"], 3),
            "place_tier": r["place_tier"] if isinstance(r["place_tier"], str) else None,
            "segment": r["segment"], "flags": flags,
            "actions": analytics.actions(r),
            "score_drivers": score_drivers, "acad_drivers": acad_drivers, "place_drivers": place_drivers,
            "raw": {
                "cgpa": _r(r["cgpa"], 2), "backlogs": int(r["backlogs"]), "sgpa_history": r["sgpa_history"],
                "sgpa_trend": _r(r["sgpa_trend"], 2), "internal_pct": _r(r["internal_pct"]),
                "weakest_subject": r["weakest_subject"], "weakest_subject_pct": _r(r["weakest_subject_pct"]),
                "attendance_pct": _r(r["attendance_pct"]), "attendance_monthly": r["attendance_monthly"],
                "attendance_min_subject": r["attendance_min_subject"],
                "attendance_min_subject_pct": _r(r["attendance_min_subject_pct"]),
                "attendance_trend": _r(r["attendance_trend"]),
                "lms_logins_per_week": _r(r["lms_logins_per_week"]),
                "lms_completion_pct": _r(r["lms_completion_pct"]), "lms_quiz_avg": _r(r["lms_quiz_avg"]),
                "lms_login_trend": _r(r["lms_login_trend"], 2),
                "lms_weekly_logins": [int(v) for v in r["lms_weekly_logins"]],
                "events": int(r["events"]), "clubs": int(r["clubs"]), "hackathons": int(r["hackathons"]),
                "certifications": int(r["certifications"]),
                "placement_assessed": bool(r["placement_assessed"]),
                "aptitude_score": _r(r["aptitude_score"]), "coding_score": _r(r["coding_score"]),
                "mock_interview_rating": _r(r["mock_interview_rating"]),
                "resume_reviewed": bool(r["resume_reviewed"]),
                "technical_skill": _r(r["technical_skill"]), "communication": _r(r["communication"]),
                "teamwork": _r(r["teamwork"]), "problem_solving": _r(r["problem_solving"]),
                "satisfaction": _r(r["satisfaction"]), "stress": _r(r["stress"]),
                "mentor_rating": _r(r["mentor_rating"]), "mentor_remark": r["mentor_remark"],
                "concern_tags": r["concern_tags"], "survey_responded": bool(r["survey_responded"]),
                "sources_linked": int(r["sources_linked"]),
            },
        })

    feature_labels = {**scoring.LABELS, **models.ACADEMIC_FEATURES, **models.PLACEMENT_FEATURES}
    payload = {
        "generated_on": date.today().isoformat(),
        "integration": {**integ, "quality_log": qlog.entries},
        "score": score_meta,
        "segments": [{"key": k, **v, "students": int((df["segment"] == k).sum())}
                     for k, v in analytics.SEGMENTS.items()],
        "models": {
            "academic": {"target": "Final CGPA < 6.0 or backlogs outstanding at graduation",
                         **m_acad.metrics, "importance": m_acad.importance()},
            "placement": {"target": "Not placed within 6 months of graduation",
                          **m_place.metrics, "importance": m_place.importance()},
        },
        "validation": validation,
        "feature_labels": feature_labels,
        "insights": analytics.insights(df),
        "students": students,
    }
    DASHBOARD_DATA.write_text(
        "// Generated by pipeline/build.py. Do not edit by hand.\n"
        "window.SSP_DATA = " + json.dumps(payload, separators=(",", ":"), default=_json_default, allow_nan=False) + ";\n"
    )
    return payload


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def main() -> None:
    if "--regenerate" in sys.argv:
        from . import generate_data
        generate_data.main()
    p = build()
    print(f"Students: {len(p['students'])}")
    print(f"Academic model AUC (holdout): {p['models']['academic']['auc_test']}")
    print(f"Placement model AUC (holdout): {p['models']['placement']['auc_test']}")
    print(f"Success Score AUC vs outcomes: academic {p['validation']['score_auc_academic']}, "
          f"placement {p['validation']['score_auc_placement']}")
    for s in p["segments"]:
        print(f"  {s['label']:<40} {s['students']}")
    for ins in p["insights"]:
        print(f"- {ins['title']}\n    {ins['detail']}")
    print(f"Wrote {DASHBOARD_DATA.relative_to(ROOT)} ({DASHBOARD_DATA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
