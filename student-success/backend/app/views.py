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
        mates = [r for r in insights.listing(ds, ins["department"], int(ins["year"])) if r["student_id"] != sid]
        # class averages are a staff view; a student's own page is about their own progress only
        if ("components" in f or "*" in f) and len(mates) >= 5 and p.roles != {"student"}:  # averages only, and never over fewer than 5 classmates
            comp_keys = list((d.get("components") or {}).keys())
            out["cohort"] = {"label": f"{ins['department']} year {ins['year']}", "students": len(mates),
                             "score": _avg([r.get("score") for r in mates]),
                             "components": {c: _avg([(r.get("component_values") or {}).get(c) for r in mates]) for c in comp_keys}}
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


# --------------------------------------------------------------------------- analytics (Insights page)
def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 1) if xs else None


def analytics(p: Principal, ds: str, department: str | None, year: int | None) -> dict:
    """Aggregates for the Insights page from ONE scoped listing pass (no scans).

    Rows are already field-filtered for the user's role, so a figure a role may not see is simply absent
    (e.g. a Placement Officer gets no overall scores). Periods compare only scored values; missing data is
    excluded, never counted as zero.
    """
    rows = visible_rows(p, ds, department, year)
    per = insights.periods()
    cur = per[-1] if per else None
    comps = list(COMPONENT_LABELS)

    def bp(r, period):
        return (r.get("by_period") or {}).get(period) or {}

    scored = [r for r in rows if r.get("score") is not None]
    prev = per[-2] if len(per) > 1 else None
    prev_scores = [bp(r, prev).get("score") for r in rows] if prev else []

    # score distribution (10-point bins)
    bins = [{"from": b, "to": b + 10, "label": f"{b}–{b + 9}" if b < 90 else "90–100", "count": 0} for b in range(0, 100, 10)]
    for r in scored:
        bins[min(9, int(r["score"] // 10))]["count"] += 1

    # component averages, overall and by department
    comp_avg = [{"key": c, "label": COMPONENT_LABELS[c], "avg": _avg([(r.get("components") or {}).get(c) for r in rows]),
                 "n": sum((r.get("components") or {}).get(c) is not None for r in rows)} for c in comps]
    depts = sorted({r["department"] for r in rows})
    comp_dept = [{"department": d, "values": {c: _avg([(r.get("components") or {}).get(c) for r in rows if r["department"] == d])
                                              for c in comps}} for d in depts]

    # trends per department and per year (scored values only)
    dept_trend = [{"department": d, "values": [_avg([bp(r, x).get("score") for r in rows if r["department"] == d]) for x in per]}
                  for d in depts]
    year_avgs = [{"year": y, "avg": _avg([r.get("score") for r in rows if int(r["year"]) == y]),
                  "students": sum(int(r["year"]) == y for r in rows)} for y in sorted({int(r["year"]) for r in rows})]

    # data coverage over time
    coverage = []
    for x in per:
        c = Counter(bp(r, x).get("status") for r in rows if bp(r, x))
        coverage.append({"period": x, "complete": c.get("complete", 0), "provisional": c.get("provisional", 0),
                         "insufficient_data": c.get("insufficient_data", 0)})

    # academic x placement risk matrix
    order = ["high", "medium", "low", "insufficient_data", "not_applicable"]
    matrix = {a: {b: 0 for b in order} for a in order}
    for r in rows:
        a, b = _risk_level(r, "academic"), _risk_level(r, "placement")
        if a in matrix and b in matrix[a]:
            matrix[a][b] += 1

    # attendance vs academic (students with both)
    scatter = [{"student_id": r["student_id"], "name": r.get("name"), "department": r["department"], "year": r["year"],
                "attendance": (r.get("components") or {}).get("attendance"), "academic": (r.get("components") or {}).get("academic"),
                "score": r.get("score")}
               for r in rows if (r.get("components") or {}).get("attendance") is not None
               and (r.get("components") or {}).get("academic") is not None]

    # movers: first vs last scored period for each student (same profile and scoring version per student)
    movers = []
    for r in rows:
        series = [bp(r, x).get("score") for x in per]
        pts = [(i, v) for i, v in enumerate(series) if v is not None]
        if len(pts) >= 2 and pts[0][0] != pts[-1][0]:
            movers.append({"student_id": r["student_id"], "name": r.get("name"), "department": r["department"], "year": r["year"],
                           "from_period": per[pts[0][0]], "to_period": per[pts[-1][0]], "from": pts[0][1], "to": pts[-1][1],
                           "change": round(pts[-1][1] - pts[0][1], 1), "series": series})
    movers.sort(key=lambda m: m["change"])

    # interventions
    ivs, _ = interventions.listing(p, ds, dept=department) if decide_any(p, "intervention", "read") else ([], None)
    if year:
        ivs = [i for i in ivs if int(i["year"]) == int(year)]
    iv = {"total": len(ivs), "by_status": dict(Counter(i["status"] for i in ivs)),
          "by_outcome": dict(Counter((i.get("outcome") or {}).get("result") for i in ivs if i.get("outcome"))),
          "by_category": dict(Counter(i["category"] for i in ivs)), "overdue": sum(bool(i.get("overdue")) for i in ivs)}

    # risk mix per month (academic and placement), from the slim per-period map
    risk_trend = {k: [dict(Counter(bp(r, x).get(f"risk_{k}") for r in rows if bp(r, x).get(f"risk_{k}"))) for x in per]
                  for k in ("academic", "placement")}

    # band movement: previous month -> latest month (comparable scored periods only)
    band_names = [b["label"] for b in insights.active_config()["bands"]] + ["Not enough data"]
    flow = {a: {b: 0 for b in band_names} for a in band_names}
    if prev:
        for r in rows:
            a, b = bp(r, prev), bp(r, cur)
            if a and b:
                fa = a.get("band") or "Not enough data"
                fb = b.get("band") or "Not enough data"
                if fa in flow and fb in flow[fa]:
                    flow[fa][fb] += 1

    # early warning: a fresh drop this month, and no open support yet
    open_iv = {i["student_id"] for i in ivs if i["status"] != "Completed"}
    warn = []
    for r in rows:
        a, b = bp(r, prev) if prev else {}, bp(r, cur)
        reasons = []
        if a.get("score") is not None and b.get("score") is not None and b["score"] - a["score"] <= -5:
            reasons.append(f"Score fell {a['score'] - b['score']:.0f} points since last month")
        ac, bc = (a.get("component_values") or {}).get("attendance"), (b.get("component_values") or {}).get("attendance")
        if ac is not None and bc is not None and bc - ac <= -10:
            reasons.append(f"Attendance fell {ac - bc:.0f} points")
        if a.get("risk_academic") in ("low", "medium") and b.get("risk_academic") == "high":
            reasons.append("Academic risk rose to high")
        if reasons:
            warn.append({"student_id": r["student_id"], "name": r.get("name"), "department": r["department"], "year": r["year"],
                         "score": b.get("score"), "reasons": reasons, "has_open_intervention": r["student_id"] in open_iv})
    warn.sort(key=lambda w: (w["has_open_intervention"], -len(w["reasons"]), w["score"] if w["score"] is not None else 999))

    return {
        "dataset": ds, "period": cur, "periods": per, "students": len(rows), "scored": len(scored),
        "risk_trend": risk_trend, "band_flow": {"bands": band_names, "counts": flow, "from": prev, "to": cur},
        "early_warning": warn[:12], "early_warning_total": len(warn),
        "kpis": {"average_score": _avg([r["score"] for r in scored]), "previous_average": _avg(prev_scores),
                 "previous_period": prev,
                 "complete_pct": round(100 * sum(r.get("status") == "complete" for r in rows) / len(rows)) if rows else None,
                 "any_high_risk": sum("high" in (_risk_level(r, "academic"), _risk_level(r, "placement")) for r in rows),
                 "improved": sum(m["change"] >= 5 for m in movers), "declined": sum(m["change"] <= -5 for m in movers)},
        "distribution": bins if scored else [], "components": comp_avg, "components_by_department": comp_dept,
        "department_trend": dept_trend, "year_averages": year_avgs, "coverage": coverage,
        "risk_matrix": {"levels": order, "counts": matrix}, "scatter": scatter,
        "movers": {"up": [m for m in reversed(movers) if m["change"] > 0][:6], "down": [m for m in movers if m["change"] < 0][:6]},
        "interventions": iv,
    }


COMPONENT_LABELS = {"academic": "Academic", "attendance": "Attendance", "lms": "LMS activity",
                    "placement": "Placement readiness", "skills": "Skills", "engagement": "Engagement"}
