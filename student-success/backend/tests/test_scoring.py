"""Score calculation, missing-data rules, independent risks, segments, feedback neutrality."""

import copy

import pytest

from app import scoring
from app.settings import default_scoring

CFG = default_scoring()
PERIODS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def rec(category, period, **d):
    return {"category": category, "period": period, **d}


def full_student(year=3, cgpa=8.0, att=(18, 17), coding=70.0, extras=()):
    rs = []
    for p in PERIODS:
        rs += [rec("attendance", p, subject="S1", classes_held=att[0], classes_attended=att[1]),
               rec("marks", p, subject="S1", assessment="T", score=35, max_score=50),
               rec("lms", p, assignments_due=4, assignments_submitted=4, logins=26)]
    rs += [rec("academic_result", "2026-04", semester=5, sgpa=cgpa, cgpa=cgpa, backlogs=0),
           rec("skills", "2026-05", technical=72, communication=66),
           rec("engagement", "2026-06", activity_type="event", name="Fest", verification="verified")]
    if year >= 3:
        rs += [rec("placement_assessment", "2026-05", assessment_type="aptitude", score=65),
               rec("placement_assessment", "2026-05", assessment_type="coding", score=coding),
               rec("placement_assessment", "2026-05", assessment_type="mock_interview", score=3.5)]
    return rs + list(extras)


def evaluate(records, year=3, cfg=CFG, ivs=()):
    return scoring.evaluate({"name": "Test Student", "year": year}, records, list(ivs), cfg, PERIODS, "2026-10-12T00:00:00+00:00")


def test_weighted_average_and_contributions_add_up():
    ins = evaluate(full_student())
    rows = {r["component"]: r for r in ins["score_rows"]}
    assert ins["status"] == "complete" and ins["coverage"] == 1.0
    assert abs(sum(r.get("applied_weight", 0) for r in rows.values()) - 1) < 1e-9
    assert ins["score"] == pytest.approx(sum(r.get("contribution", 0) for r in rows.values()), abs=0.06)
    # documented formula: attendance 17/18 = 94.4% (rounded to 0.1) -> (94.4-60)/(95-60)*100 = 98.3
    assert rows["attendance"]["value"] == pytest.approx(98.3, abs=0.05)
    assert rows["attendance"]["applied_weight"] == 0.2


def test_missing_component_is_not_zero_and_weights_renormalise():
    rs = [r for r in full_student() if r["category"] != "lms"]
    ins = evaluate(rs)
    rows = {r["component"]: r for r in ins["score_rows"]}
    assert rows["lms"]["status"] == "missing" and "contribution" not in rows["lms"]
    assert ins["coverage"] == pytest.approx(0.85)
    assert ins["status"] == "provisional"
    assert rows["academic"]["applied_weight"] == pytest.approx(0.30 / 0.85, abs=1e-4)
    full = evaluate(full_student())["score"]
    assert ins["score"] > full - 10  # missing LMS did not drag the score towards zero


def test_insufficient_data_below_threshold():
    rs = [r for r in full_student() if r["category"] not in ("lms", "skills", "engagement")]
    ins = evaluate(rs)
    assert ins["coverage"] == pytest.approx(0.65)
    assert ins["status"] == "insufficient_data" and ins["score"] is None and ins["indicative_score"] is not None
    assert any(s["key"] == "insufficient_data" for s in ins["segments"])


def test_placement_not_applicable_in_early_years():
    ins = evaluate(full_student(year=1), year=1)
    rows = {r["component"]: r for r in ins["score_rows"]}
    assert rows["placement"]["status"] == "not_applicable"
    assert ins["coverage"] == 1.0 and ins["status"] == "complete"
    assert ins["risks"]["placement"]["level"] == "not_applicable"


def test_feedback_never_changes_the_score():
    base = evaluate(full_student())
    unhappy = evaluate(full_student(extras=[rec("feedback", "2026-09", satisfaction=1, stress=5, support_needed=["financial"],
                                                comment="Very dissatisfied")]))
    assert unhappy["score"] == base["score"]
    assert unhappy["risks"] == base["risks"]
    assert any("satisfaction" in s.lower() for s in unhappy["support_needs"])


def test_risks_are_independent():
    weak_place = evaluate(full_student(coding=25.0))
    assert weak_place["risks"]["academic"]["level"] == "low"
    assert weak_place["risks"]["placement"]["level"] == "high"
    weak_acad = evaluate(full_student(cgpa=5.5, att=(18, 10)))
    assert weak_acad["risks"]["academic"]["level"] == "high"
    assert weak_acad["risks"]["placement"]["level"] in ("low", "medium")  # only the eligibility rules could apply


def test_missing_placement_data_is_not_poor_readiness():
    rs = [r for r in full_student() if r["category"] != "placement_assessment"]
    ins = evaluate(rs)
    pr = ins["risks"]["placement"]
    assert pr["level"] == "insufficient_data"
    assert "does not mean poor readiness" in pr["explanation"]
    assert pr["suggested_intervention"]["key"] == "collect_placement_data"


def test_flags_carry_evidence_rule_threshold_period_intervention_and_time():
    ins = evaluate(full_student(cgpa=5.5))
    f = ins["risks"]["academic"]["flags"][0]
    assert {"rule", "label", "observed", "operator", "threshold", "level", "observed_period", "suggested_intervention"} <= set(f)
    assert f["rule"] == "A1" and f["observed"] == 5.5 and f["threshold"] == 6.0 and f["observed_period"] == "2026-04"
    assert ins["risks"]["academic"]["calculated_at"] and "ASSUMPTIONS" in CFG["description"].upper()


def test_trends_only_compare_compatible_profiles():
    ins = evaluate(full_student())
    cfg2 = copy.deepcopy(CFG)
    cfg2["version"] = "2.0.0"
    a = {"profile": "placement_years", "scoring_version": "1.0.0", "score": 60}
    b = {"profile": "early_years", "scoring_version": "1.0.0", "score": 70}
    c = {"profile": "placement_years", "scoring_version": "2.0.0", "score": 70}
    assert not scoring.compatible(a, b) and not scoring.compatible(a, c)
    assert all(t["comparable_with_current"] for t in ins["trend"] if t["score"] is not None)


def test_segments_explainable():
    strong = evaluate(full_student(cgpa=9.0, coding=22.0))
    seg = {s["key"]: s for s in strong["segments"]}
    assert "strong_academics_low_placement" in seg and seg["strong_academics_low_placement"]["reasons"]


def test_improving_after_intervention_is_association_only():
    rs = full_student(cgpa=8.0)
    ins0 = evaluate(rs)
    iv = {"status": "Completed", "title": "Support plan", "baseline": {"period": "2026-05"}}
    low = [r if not (r["category"] == "marks" and r["period"] in PERIODS[:2]) else {**r, "score": 10} for r in rs]
    ins = evaluate(low, ivs=[iv])
    imp = [s for s in ins["segments"] if s["key"] == "improving_after_intervention"]
    assert imp and "not proof" in imp[0]["reasons"][1]
    assert ins0["score"] is not None


def test_score_sort_is_numeric_and_paginates(call):
    seen, cursor = [], None
    while True:
        r = call("admin.priya", "GET", "/api/students?dataset=real&sort=score&limit=40" + (f"&cursor={cursor}" if cursor else "")).json()
        seen += r["items"]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 150 and len({s["student_id"] for s in seen}) == 150
    scores = [s["score"] for s in seen if s["score"] is not None]
    assert scores == sorted(scores)
    assert all(s["score"] is None for s in seen[len(scores):])


def test_insufficient_data_student_profile_and_listing(call):
    rows = call("admin.priya", "GET", "/api/students?dataset=real&status=insufficient_data&limit=5").json()["items"]
    assert rows and all(r["score"] is None for r in rows)
    sid = rows[0]["student_id"]
    r = call("admin.priya", "GET", f"/api/students/real/{sid}")
    assert r.status_code == 200, r.text
    ins = r.json()["insight"]
    assert ins["score"] is None and ins["status"] == "insufficient_data" and ins["band"] is None
    for period in ("2026-04", "2026-09"):
        assert call("admin.priya", "GET", f"/api/students?dataset=real&period={period}&limit=200").status_code == 200


def test_prediction_model_is_disabled_by_default(client):
    from app.model_interface import get_model
    assert get_model() is None
    h = client.get("/api/health").json()
    assert h["prediction"]["enabled"] is False and h["prediction"]["method"] == "rules"


def test_failed_first_calculation_is_marked_and_repairable(call, monkeypatch):
    from app import db, insights
    t = db.table()
    t.put({"pk": "STU#real#MECH26900", "sk": "MASTER", "student_id": "MECH26900", "name": "Repair Case", "department": "MECH",
           "year": 1, "dataset": "real", "programme": "B.Tech", "status": "active", "version": 1})
    for sk in ("INSIGHT", "STALE"):
        t.delete("STU#real#MECH26900", sk)
    real = insights.recompute
    monkeypatch.setattr(insights, "recompute", lambda ds, sid: (_ for _ in ()).throw(RuntimeError("throttled")))
    assert insights.recompute_safely("real", "MECH26900") == "stale"
    assert t.get("STU#real#MECH26900", "STALE") is not None  # visible to repair even with no insight yet
    monkeypatch.setattr(insights, "recompute", real)
    insights.repair("real", budget_seconds=5)
    assert t.get("STU#real#MECH26900", "INSIGHT") is not None and t.get("STU#real#MECH26900", "STALE") is None
    t.delete("STU#real#MECH26900", "INSIGHT"); t.delete("STU#real#MECH26900", "INSIGHTD"); t.delete("STU#real#MECH26900", "MASTER")
    for i in t.query("STU#real#MECH26900")[0]:
        t.delete(i["pk"], i["sk"])
    insights.invalidate_listing()
