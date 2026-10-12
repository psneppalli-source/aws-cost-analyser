"""Read models for listings, dashboards and profiles, always scoped and field-filtered."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from . import db, insights, interventions, recordsvc
from .policy import Principal, decide, filter_fields, visibility
from .settings import curriculum


def _canon(r: dict, period: str | None) -> dict:
    """Slim list row -> canonical insight shape used by field filtering, optionally for another period."""
    row = {"student_id": r["student_id"], "dataset": r["dataset"], "name": r["name"], "department": r["department"],
           "year": r["year"], "period": r["period"], "score": r.get("score"), "indicative_score": r.get("indicative_score"),
           "status": r.get("status"), "band": r.get("band"), "coverage": r.get("coverage"), "profile": r.get("profile"),
           "components": dict(r.get("component_values") or {}),
           "risks": {"academic": {"level": r.get("risk_academic")}, "placement": {"level": r.get("risk_placement")}},
           "segments": list(r.get("segment_keys") or []), "by_period": r.get("by_period"),
           "calculated_at": r.get("calculated_at"), "recalc_status": r.get("recalc_status"), "scoring_version": r.get("scoring_version"),
           "mentor_name": r.get("mentor_name"), "support_flag": r.get("support_flag")}
    bp = (r.get("by_period") or {}).get(period) if period and period != r["period"] else None
    if bp:
        row.update(period=period, score=bp.get("score"), indicative_score=bp.get("indicative_score"), status=bp.get("status"),
                   band=bp.get("band"), coverage=bp.get("coverage"), components=dict(bp.get("component_values") or {}),
                   risks={"academic": {"level": bp.get("risk_academic")}, "placement": {"level": bp.get("risk_placement")}},
                   segments=list(bp.get("segment_keys") or []))
    return row


def visible_rows(p: Principal, ds: str, department: str | None = None, year: int | None = None,
                 period: str | None = None) -> list[dict]:
    vis = visibility(p, "student_insight")
    depts = list(curriculum()["departments"])
    wanted_depts = set()
    if vis["college"]:
        wanted_depts = set(depts)
    wanted_depts |= set(vis["departments"])
    extra = {sid for d, sid in vis["mentees"] if d == ds}
    if vis["own"] and vis["own"][0] == ds:
        extra.add(vis["own"][1])
    out = []
    for dept in depts:
        if department and dept != department:
            continue
        if dept not in wanted_depts and not extra:
            continue
        for r in insights.listing(ds, dept, year):
            if dept not in wanted_depts and r["student_id"] not in extra:
                continue
            t = {"dataset": ds, "student_id": r["student_id"], "department": r["department"], "year": int(r["year"])}
            f = decide(p, "student_insight", "read", t)
            if f is None:
                continue
            out.append(filter_fields(_canon(r, period), f))
    return out


def _risk_level(row: dict, kind: str) -> str | None:
    return ((row.get("risks") or {}).get(kind) or {}).get("level")


def apply_filters(rows: list[dict], q: dict) -> list[dict]:
    out = []
    term = (q.get("q") or "").strip().lower()
    for r in rows:
        if q.get("risk"):
            kind, _, level = q["risk"].partition(":")
            if kind == "any":
                if level not in (_risk_level(r, "academic"), _risk_level(r, "placement")):
                    continue
            elif _risk_level(r, kind) != level:
                continue
        if q.get("segment") and q["segment"] not in (r.get("segments") or []):
            continue
        if q.get("status") and r.get("status") != q["status"]:
            continue
        if term and term not in r.get("name", "").lower() and term not in r["student_id"].lower():
            continue
        out.append(r)
    return out


def _sort_value(r: dict, key: str) -> str:
    v = r.get(key)
    if key == "score":  # numeric order as text; students without a score last
        return "~" if v is None else f"{float(v):07.2f}"
    return str(v)


def paginate(rows: list[dict], limit: int, cursor: str | None, key: str = "student_id") -> tuple[list[dict], str | None]:
    rows = sorted(rows, key=lambda r: (_sort_value(r, key), r["student_id"]))
    if cursor:
        rows = [r for r in rows if (_sort_value(r, key), r["student_id"]) > tuple(cursor.split("|", 1))]
    page = rows[:limit]
    nxt = f"{_sort_value(page[-1], key)}|{page[-1]['student_id']}" if len(rows) > limit else None
    return page, nxt


def dashboard(p: Principal, ds: str, department: str | None, year: int | None, period: str | None) -> dict:
    rows = visible_rows(p, ds, department, year, period)
    scored = [r["score"] for r in rows if r.get("score") is not None]
    per = insights.periods()
    trend = []
    for pp in per:
        prow = visible_rows(p, ds, department, year, pp)
        vals = [r["score"] for r in prow if r.get("score") is not None and r.get("profile") is not None]
        trend.append({"period": pp, "average_score": round(mean(vals), 1) if vals else None, "students_scored": len(vals),
                      "high_academic_risk": sum(_risk_level(r, "academic") == "high" for r in prow),
                      "high_placement_risk": sum(_risk_level(r, "placement") == "high" for r in prow)})
    by_dept = defaultdict(lambda: {"academic": Counter(), "placement": Counter(), "students": 0})
    for r in rows:
        d = by_dept[r["department"]]
        d["students"] += 1
        for k in ("academic", "placement"):
            lv = _risk_level(r, k)
            if lv:
                d[k][lv] += 1
    ivs, _ = interventions.listing(p, ds, dept=department) if decide_any(p, "intervention", "read") else ([], None)
    open_by = defaultdict(set)
    for i in ivs:
        if i["status"] != "Completed":
            open_by[i["student_id"]].add(i.get("category"))
    review = []
    for r in rows:
        reasons = []
        if _risk_level(r, "academic") == "high" and not open_by.get(r["student_id"]):
            reasons.append("High academic risk with no open intervention")
        if _risk_level(r, "placement") == "high" and "placement_training" not in open_by.get(r["student_id"], set()):
            reasons.append("High placement risk with no placement training")
        if r.get("recalc_status") == "stale":
            reasons.append("Recalculation pending")
        if "declining_attendance_results" in (r.get("segments") or []):
            reasons.append("Declining attendance and results")
        if reasons:
            review.append({"student_id": r["student_id"], "name": r.get("name"), "department": r["department"],
                           "year": r["year"], "score": r.get("score"), "status": r.get("status"), "reasons": reasons})
    review.sort(key=lambda x: (-len(x["reasons"]), x["score"] if x["score"] is not None else 999))
    overdue = [i for i in ivs if i.get("overdue")]
    calc = [r.get("calculated_at") for r in rows if r.get("calculated_at")]
    return {
        "dataset": ds, "period": period or insights.current_period(), "periods": per, "students": len(rows),
        "kpis": {"average_score": round(mean(scored), 1) if scored else None,
                 "status": dict(Counter(r.get("status") for r in rows)),
                 "academic_risk": dict(Counter(_risk_level(r, "academic") for r in rows if _risk_level(r, "academic"))),
                 "placement_risk": dict(Counter(_risk_level(r, "placement") for r in rows if _risk_level(r, "placement"))),
                 "needs_review": len(review), "open_interventions": sum(1 for i in ivs if i["status"] != "Completed"),
                 "overdue_interventions": len(overdue), "stale": sum(r.get("recalc_status") == "stale" for r in rows)},
        "score_distribution": scored,
        "bands": dict(Counter(r.get("band") or "Insufficient data" for r in rows)),
        "risk_by_department": [{"department": d, "students": v["students"], "academic": dict(v["academic"]),
                                "placement": dict(v["placement"])} for d, v in sorted(by_dept.items())],
        "segments": dict(Counter(s for r in rows for s in (r.get("segments") or []))),
        "trend": trend, "needs_review": review[:40],
        "last_calculated_at": max(calc) if calc else None,
    }


def decide_any(p: Principal, resource: str, action: str) -> bool:
    from .policy import grants
    return bool(grants(p, resource, action))


def profile(p: Principal, ds: str, sid: str) -> dict:
    m = recordsvc.get_master(ds, sid)
    t = recordsvc.target(m)
    mf = decide(p, "student_master", "read", t)  # covers subject-class scope as well
    if mf is None:
        from .policy import Denied
        raise Denied("You don't have access to this student.")
    tbl = db.table()
    ins = tbl.get(f"STU#{ds}#{sid}", "INSIGHT") or {}
    stale = insights.is_stale(ds, sid)
    out = {"student": filter_fields({k: v for k, v in m.items() if k not in ("pk", "sk")}, mf), "insight": None,
           "history": [], "recommendations": [], "interventions": [], "notes": [], "corrections": []}
    f = decide(p, "student_insight", "read", t)
    if f is not None and ins:
        d = tbl.get(f"STU#{ds}#{sid}", "INSIGHTD") or {}
        canon = {"student_id": sid, "dataset": ds, "name": ins["name"], "department": ins["department"], "year": ins["year"],
                 "period": ins["period"], "score": ins.get("score"), "indicative_score": ins.get("indicative_score"),
                 "status": ins.get("status"), "band": ins.get("band"), "coverage": ins.get("coverage"), "profile": ins.get("profile"),
                 "components": d.get("components"), "risks": d.get("risks"), "segments": d.get("segments"),
                 "support_needs": d.get("support_needs"), "eligibility": d.get("eligibility"), "trend": d.get("trend"),
                 "by_period": ins.get("by_period"), "score_rows": d.get("score_rows"), "indicators": d.get("indicators"),
                 "sources": d.get("sources"), "summary": d.get("summary"), "scoring_version": ins.get("scoring_version"),
                 "calculated_at": ins.get("calculated_at"), "recalc_status": "stale" if stale else ins.get("recalc_status"),
                 "mentor_name": ins.get("mentor_name")}
        out["insight"] = filter_fields(canon, f)
        if "by_period" in f or "*" in f:
            hist, _ = tbl.query(f"STU#{ds}#{sid}", "SCORE#")
            out["history"] = [{k: h.get(k) for k in ("period", "score", "indicative_score", "status", "band", "coverage",
                                                     "profile", "rows", "scoring_version", "missing")} for h in hist]
        if decide(p, "intervention", "create", t) is not None:
            out["recommendations"] = recommendations(p, d.get("risks") or {})
    out["interventions"] = interventions.for_student(p, ds, sid)
    out["notes"] = interventions.notes(p, ds, sid)
    if decide(p, "correction", "read", t) is not None:
        items, _ = tbl.query(f"STU#{ds}#{sid}", "CORR#")
        out["corrections"] = [{k: v for k, v in i.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk")} for i in items]
    out["permissions"] = {
        "edit_master": decide(p, "student_master", "update", t) is not None,
        "assign_mentor": decide(p, "mentor_assignment", "assign", t) is not None,
        "create_intervention": decide(p, "intervention", "create", t) is not None,
        "update_intervention": decide(p, "intervention", "update", t) is not None,
        "staff_note": decide(p, "note.staff", "create", t) is not None,
        "confidential_note": decide(p, "note.confidential", "create", t) is not None,
        "approve_corrections": decide(p, "correction", "approve", t) is not None,
        "verify": decide(p, "record.certification", "verify", t) is not None,
        "submit_feedback": decide(p, "record.feedback", "submit", t) is not None,
        "submit_certification": decide(p, "record.certification", "submit", t) is not None,
    }
    return out


def recommendations(p: Principal, risks: dict) -> list[dict]:
    from .policy import constraints
    allowed = constraints(p, "intervention_categories")
    out, seen = [], set()
    for kind in ("academic", "placement"):
        r = risks.get(kind) or {}
        for f in r.get("flags", []):
            iv = f["suggested_intervention"]
            if iv["key"] in seen or (allowed is not None and iv["category"] not in allowed):
                continue
            seen.add(iv["key"])
            ev = [x for x in r["flags"] if x["suggested_intervention"]["key"] == iv["key"]]
            out.append({"key": iv["key"], "title": iv["title"], "category": iv["category"], "owner_role": iv["owner_role"],
                        "risk": kind, "level": f["level"],
                        "evidence": [{"rule": x["rule"], "label": x["label"], "observed": x["observed"], "threshold": x["threshold"],
                                      "operator": x["operator"], "period": x["observed_period"]} for x in ev]})
        si = r.get("suggested_intervention")
        if si and si["key"] not in seen and (allowed is None or si["category"] in allowed):
            seen.add(si["key"])
            out.append({"key": si["key"], "title": si["title"], "category": si["category"], "owner_role": si["owner_role"],
                        "risk": kind, "level": r["level"], "evidence": [{"rule": "missing", "label": r.get("explanation"),
                                                                        "observed": None, "threshold": None, "operator": None,
                                                                        "period": r.get("period")}]})
    return out
