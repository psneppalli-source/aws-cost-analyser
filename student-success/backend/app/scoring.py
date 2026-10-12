"""Student Success Score, risks and segments as pure functions.

Inputs are a student's master record, their records and interventions, the
active scoring configuration and the ordered reporting periods. Nothing here
touches storage, so every calculation is directly testable.

Per period p (see docs/scoring-methodology.md):
  academic    cgpa/backlogs from the latest academic result <= p; marks % from p's marks
  attendance  attended / held across p's subjects (change = p minus two periods earlier)
  lms         submitted / due in p; logins per week = logins / 4.33
  placement   latest score per assessment type within the look-back window (<= p)
  skills      latest skills assessment <= p
  engagement  events, clubs, projects and VERIFIED certifications within the look-back window
Feedback never enters the score; it produces support needs.
"""

from __future__ import annotations

from statistics import mean

WEEKS_PER_MONTH = 4.33
LEVELS = {"low": 0, "medium": 1, "high": 2}


def clip100(v: float, worst: float, best: float) -> float:
    return max(0.0, min(100.0, (v - worst) / (best - worst) * 100))


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def profile_for(year: int, cfg: dict) -> str:
    for pid, p in cfg["cohort_profiles"].items():
        if year in p["applies_to_years"]:
            return pid
    return next(iter(cfg["cohort_profiles"]))


def _by(records: list[dict], category: str) -> list[dict]:
    return [r for r in records if r["category"] == category]


def indicators(records: list[dict], periods: list[str], i: int, cfg: dict) -> tuple[dict, dict]:
    """Raw indicator values for period index i, plus the period each value came from."""
    p = periods[i]
    lb_a = set(periods[max(0, i - cfg["windows"]["assessment_lookback_periods"] + 1): i + 1])
    lb_e = set(periods[max(0, i - cfg["windows"]["engagement_lookback_periods"] + 1): i + 1])
    v: dict = {}
    src: dict = {}

    acad = sorted((r for r in _by(records, "academic_result") if r["period"] <= p), key=lambda r: r["period"])
    if acad:
        v["cgpa"], v["backlogs"] = acad[-1]["cgpa"], acad[-1]["backlogs"]
        src["cgpa"] = src["backlogs"] = acad[-1]["period"]
    marks = [r for r in _by(records, "marks") if r["period"] == p]
    if marks:
        v["marks_pct"] = _r(mean(r["score"] / r["max_score"] * 100 for r in marks))
        src["marks_pct"] = p

    def att(period):
        rs = [r for r in _by(records, "attendance") if r["period"] == period]
        held = sum(r["classes_held"] for r in rs)
        return (sum(r["classes_attended"] for r in rs) / held * 100) if held else None

    a = att(p)
    if a is not None:
        v["attendance_pct"] = _r(a)
        src["attendance_pct"] = p
        if i >= 2:
            a0 = att(periods[i - 2])
            if a0 is not None:
                v["attendance_change"] = _r(a - a0)
                src["attendance_change"] = f"{periods[i - 2]}..{p}"

    lms = [r for r in _by(records, "lms") if r["period"] == p]
    if lms:
        due = sum(r["assignments_due"] for r in lms)
        if due:
            v["assignment_completion_pct"] = _r(sum(r["assignments_submitted"] for r in lms) / due * 100)
            src["assignment_completion_pct"] = p
        v["logins_per_week"] = _r(sum(r["logins"] for r in lms) / WEEKS_PER_MONTH, 2)
        src["logins_per_week"] = p

    for t in ("aptitude", "coding", "mock_interview"):
        rs = sorted((r for r in _by(records, "placement_assessment") if r["assessment_type"] == t and r["period"] in lb_a),
                    key=lambda r: r["period"])
        if rs:
            v[t], src[t] = rs[-1]["score"], rs[-1]["period"]
    sk = sorted((r for r in _by(records, "skills") if r["period"] <= p and r["period"] in lb_a), key=lambda r: r["period"])
    if sk:
        v["technical"], v["communication"] = sk[-1]["technical"], sk[-1]["communication"]
        src["technical"] = src["communication"] = sk[-1]["period"]

    eng = [r for r in _by(records, "engagement") if r["period"] in lb_e and r.get("verification", "verified") != "rejected"]
    certs = [r for r in _by(records, "certification") if r["period"] in lb_e and r.get("verification") == "verified"]
    if eng or certs or any(r["category"] in ("engagement", "certification") for r in records):
        v["events"] = sum(r["activity_type"] == "event" for r in eng)
        v["clubs"] = len({r["name"].lower() for r in eng if r["activity_type"] == "club"})
        v["projects"] = sum(r["activity_type"] == "project" for r in eng)
        v["certifications"] = len(certs)
        for k in ("events", "clubs", "projects", "certifications"):
            src[k] = f"{periods[max(0, i - cfg['windows']['engagement_lookback_periods'] + 1)]}..{p}"
    return v, src


def components(v: dict, cfg: dict) -> dict:
    out = {}
    for comp, spec in cfg["normalisation"].items():
        parts = []
        for ind, s in spec["indicators"].items():
            if v.get(ind) is not None:
                parts.append((s["weight"], clip100(float(v[ind]), s["worst"], s["best"]), ind))
        if parts:
            w = sum(x[0] for x in parts)
            out[comp] = {"value": _r(sum(x[0] * x[1] for x in parts) / w), "indicators": {x[2]: _r(x[1]) for x in parts},
                         "indicator_coverage": _r(w, 2)}
    return out


def score(comps: dict, profile: str, cfg: dict) -> dict:
    applicable = cfg["cohort_profiles"][profile]["components"]
    weights = {c: cfg["components"][c]["weight"] for c in applicable}
    total = sum(weights.values())
    avail = {c: w for c, w in weights.items() if c in comps}
    coverage = sum(avail.values()) / total if total else 0.0
    rows = []
    aw = sum(avail.values())
    for c in cfg["components"]:
        row = {"component": c, "label": cfg["components"][c]["label"], "configured_weight": cfg["components"][c]["weight"]}
        if c not in weights:
            row.update(status="not_applicable")
        elif c not in comps:
            row.update(status="missing")
        else:
            applied = weights[c] / aw
            row.update(status="included", value=comps[c]["value"], applied_weight=round(applied, 4),
                       contribution=round(applied * comps[c]["value"], 2))
        rows.append(row)
    final = round(sum(r.get("contribution", 0) for r in rows), 1) if avail else None
    if coverage < cfg["coverage_threshold"]:
        status = "insufficient_data"
    elif coverage < 0.9999:
        status = "provisional"
    else:
        status = "complete"
    return {"score": final if status != "insufficient_data" else None,
            "indicative_score": final if status == "insufficient_data" else None,
            "status": status, "coverage": round(coverage, 3), "profile": profile, "rows": rows,
            "missing": [r["label"] for r in rows if r["status"] == "missing"]}


def band(value: float | None, cfg: dict) -> str | None:
    if value is None:
        return None
    return next(b["label"] for b in cfg["bands"] if value >= b["min"])


def _cmp(v, op, t) -> bool:
    return {"<": v < t, "<=": v <= t, ">": v > t, ">=": v >= t}[op]


def risk(kind: str, v: dict, src: dict, profile: str, cfg: dict, calculated_at: str, period: str) -> dict:
    spec = cfg["risk"][kind]
    base = {"kind": kind, "calculated_at": calculated_at, "period": period,
            "assumption_notice": cfg["risk"]["assumption_notice"]}
    if "applies_to_profiles" in spec and profile not in spec["applies_to_profiles"]:
        return {**base, "level": "not_applicable", "flags": [], "missing": [],
                "explanation": "Placement indicators do not apply to this year of study yet."}
    flags, seen = [], set()
    for r in spec["rules"]:
        val = v.get(r["indicator"])
        if val is None or not _cmp(val, r["op"], r["value"]):
            continue
        if r["indicator"] in seen:  # the strictest triggered rule per indicator is listed first; skip weaker duplicates
            continue
        seen.add(r["indicator"])
        iv = cfg["interventions"][r["intervention"]]
        flags.append({"rule": r["id"], "label": r["label"], "indicator": r["indicator"], "observed": val,
                      "operator": r["op"], "threshold": r["value"], "level": r["level"],
                      "observed_period": src.get(r["indicator"], period),
                      "suggested_intervention": {"key": r["intervention"], **iv}})
    missing = [x for x in spec.get("required", []) if v.get(x) is None]
    if spec.get("required_any") and all(v.get(x) is None for x in spec["required_any"]):
        missing.append(" or ".join(spec["required_any"]))
    level = max((f["level"] for f in flags), key=lambda l: LEVELS[l], default="low")
    if missing and level != "high":
        if kind == "placement":
            iv = cfg["interventions"]["collect_placement_data"]
            return {**base, "level": "insufficient_data", "flags": flags, "missing": missing,
                    "explanation": "No placement assessments on record. Missing data does not mean poor readiness.",
                    "suggested_intervention": {"key": "collect_placement_data", **iv}}
        return {**base, "level": "insufficient_data", "flags": flags, "missing": missing,
                "explanation": f"Required evidence missing: {', '.join(missing)}."}
    flags.sort(key=lambda f: -LEVELS[f["level"]])
    return {**base, "level": level, "flags": flags, "missing": missing,
            "explanation": "No rule triggered." if not flags else f"{len(flags)} rule(s) triggered."}


def support_needs(records: list[dict], period: str, cfg: dict) -> list[str]:
    fb = sorted((r for r in _by(records, "feedback") if r["period"] <= period), key=lambda r: r["period"])
    if not fb:
        return []
    f, rules = fb[-1], cfg["feedback_support_needs"]
    out = []
    if f["stress"] >= rules["stress_at_least"]:
        out.append(f"High stress reported ({f['stress']}/5) in {f['period']}")
    if f["satisfaction"] <= rules["satisfaction_at_most"]:
        out.append(f"Low satisfaction reported ({f['satisfaction']}/5) in {f['period']}; ask what support would help")
    for s in f.get("support_needed") or []:
        if s != "none":
            out.append(f"Asked for {s} support in {f['period']}")
    return out


def compatible(a: dict, b: dict) -> bool:
    return (a.get("profile") == b.get("profile") and a.get("scoring_version") == b.get("scoring_version")
            and a.get("score") is not None and b.get("score") is not None)


def segments(hist: list[dict], risks: dict, interventions: list[dict], cfg: dict) -> list[dict]:
    seg, cur = cfg["segments"], hist[-1]
    out = []
    comps = {r["component"]: r.get("value") for r in cur["rows"] if r["status"] == "included"}
    if cur["status"] == "insufficient_data":
        out.append({"key": "insufficient_data", "label": seg["insufficient_data"]["label"],
                    "reasons": [f"Data coverage {cur['coverage']:.0%} is below the {cfg['coverage_threshold']:.0%} threshold",
                                *[f"Missing: {m}" for m in cur["missing"]]]})
    a, pl = comps.get("academic"), comps.get("placement")
    s = seg["strong_academics_low_placement"]
    if a is not None and pl is not None and a >= s["academic_min"] and pl < s["placement_max"]:
        out.append({"key": "strong_academics_low_placement", "label": s["label"],
                    "reasons": [f"Academic component {a:.0f} (>= {s['academic_min']})", f"Placement component {pl:.0f} (< {s['placement_max']})"]})
    s = seg["declining_attendance_results"]
    if len(hist) >= 3:
        old = hist[-3]
        oc = {r["component"]: r.get("value") for r in old["rows"] if r["status"] == "included"}
        ac_drop = oc["academic"] - a if oc.get("academic") is not None and a is not None else None
        raw_att = cur["indicators"].get("attendance_change")
        if raw_att is not None and raw_att <= -s["attendance_drop"] and ac_drop is not None and ac_drop >= s["academic_drop"]:
            out.append({"key": "declining_attendance_results", "label": s["label"],
                        "reasons": [f"Attendance changed {raw_att:+.0f} points since {old['period']}",
                                    f"Academic component fell {ac_drop:.0f} points since {old['period']}"]})
    s = seg["strong_skills_academic_support"]
    sk = comps.get("skills")
    if sk is not None and sk >= s["skills_min"] and risks["academic"]["level"] in ("medium", "high"):
        out.append({"key": "strong_skills_academic_support", "label": s["label"],
                    "reasons": [f"Skills component {sk:.0f} (>= {s['skills_min']})", f"Academic risk is {risks['academic']['level']}"]})
    s = seg["improving_after_intervention"]
    for iv in interventions:
        if iv.get("status") not in ("In Progress", "Completed"):
            continue
        base = next((h for h in hist if h["period"] == (iv.get("baseline") or {}).get("period")), None)
        if base and compatible(base, cur) and cur["score"] - base["score"] >= s["score_gain"]:
            out.append({"key": "improving_after_intervention", "label": s["label"],
                        "reasons": [f"Score {base['score']:.0f} → {cur['score']:.0f} since '{iv['title']}' began in {base['period']}",
                                    "This shows association with the intervention, not proof that it caused the change"]})
            break
    s = seg["consistently_performing_well"]
    last = hist[-3:]
    if (len(last) == 3 and all(h["score"] is not None and h["score"] >= s["score_min"] for h in last)
            and risks["academic"]["level"] == "low" and risks["placement"]["level"] in ("low", "not_applicable")):
        out.append({"key": "consistently_performing_well", "label": s["label"],
                    "reasons": [f"Score at least {s['score_min']} in each of {', '.join(h['period'] for h in last)}",
                                "Academic and placement risk low"]})
    return out


def summary(master: dict, cur: dict, risks: dict, segs: list[dict], needs: list[str], trend: list[dict]) -> str:
    """Template-generated, rules-based summary. Every sentence comes from a computed value."""
    name = master["name"].split()[0]
    parts = []
    if cur["score"] is None:
        parts.append(f"{name}'s score is not shown: only {cur['coverage']:.0%} of the applicable data is available"
                     f" (missing {', '.join(cur['missing']) or 'some components'}).")
    else:
        q = "provisional " if cur["status"] == "provisional" else ""
        parts.append(f"{name} has a {q}Success Score of {cur['score']:.0f} for {cur['period']} ({cur['band']}).")
        comparable = [t for t in trend[:-1] if t.get("comparable_with_current")]
        if comparable:
            d = cur["score"] - comparable[0]["score"]
            parts.append(f"That is {'up' if d > 0 else 'down'} {abs(d):.0f} points since {comparable[0]['period']}." if abs(d) >= 1
                         else f"It is stable since {comparable[0]['period']}.")
    for kind, label in (("academic", "Academic"), ("placement", "Placement")):
        r = risks[kind]
        if r["level"] in ("high", "medium"):
            parts.append(f"{label} risk is {r['level']}: " + "; ".join(f["label"].lower() for f in r["flags"][:3]) + ".")
        elif r["level"] == "insufficient_data":
            parts.append(f"{label} risk cannot be assessed yet ({r['explanation'].rstrip('.')}).")
    if segs:
        parts.append("Segments: " + ", ".join(s["label"] for s in segs) + ".")
    if needs:
        parts.append("Support needs from feedback: " + "; ".join(needs[:2]) + ".")
    parts.append("This summary is generated by rules from recorded data; it is not a prediction.")
    return " ".join(parts)


def evaluate(master: dict, records: list[dict], interventions: list[dict], cfg: dict, periods: list[str],
             calculated_at: str) -> dict:
    """Full insight for a student: per-period history plus current risks, segments and summary."""
    profile = profile_for(int(master["year"]), cfg)
    hist = []
    for i, p in enumerate(periods):
        v, src = indicators(records, periods, i, cfg)
        comps = components(v, cfg)
        sc = score(comps, profile, cfg)
        hist.append({"period": p, **sc, "band": band(sc["score"], cfg), "components": comps, "indicators": v,
                     "sources": src, "scoring_version": cfg["version"]})
    for h in hist:
        h["comparable_with_current"] = compatible(h, hist[-1]) and h is not hist[-1]
    by_period = {}
    for i, h in enumerate(hist):
        r_i = {k: risk(k, h["indicators"], h["sources"], profile, cfg, calculated_at, h["period"]) for k in ("academic", "placement")}
        ivs_i = [iv for iv in interventions if (iv.get("baseline") or {}).get("period", "9999") <= h["period"]]
        s_i = segments(hist[: i + 1], r_i, ivs_i, cfg)
        h["risks"], h["segments"] = r_i, s_i
        by_period[h["period"]] = {"score": h["score"], "indicative_score": h["indicative_score"], "status": h["status"],
                                  "band": h["band"], "coverage": h["coverage"], "risk_academic": r_i["academic"]["level"],
                                  "risk_placement": r_i["placement"]["level"], "segment_keys": [x["key"] for x in s_i],
                                  "component_values": {c: x["value"] for c, x in h["components"].items()}}
    cur = hist[-1]
    v, src = cur["indicators"], cur["sources"]
    risks, segs = cur["risks"], cur["segments"]
    trend = [{"period": h["period"], "score": h["score"], "status": h["status"], "profile": h["profile"],
              "comparable_with_current": h["comparable_with_current"] or h is cur} for h in hist]
    needs = support_needs(records, cur["period"], cfg)
    comps_view = {c: {"value": x["value"], "indicators": x["indicators"]} for c, x in cur["components"].items()}
    eligibility = {"cgpa": v.get("cgpa"), "backlogs": v.get("backlogs")}
    return {
        "period": cur["period"], "score": cur["score"], "indicative_score": cur["indicative_score"], "status": cur["status"],
        "band": cur["band"], "coverage": cur["coverage"], "profile": profile, "score_rows": cur["rows"],
        "components": comps_view, "indicators": v, "sources": src, "risks": risks, "segments": segs,
        "support_needs": needs, "eligibility": eligibility, "trend": trend, "history": hist, "by_period": by_period,
        "summary": summary(master, cur, risks, segs, needs, trend),
        "scoring_version": cfg["version"], "calculated_at": calculated_at,
    }
