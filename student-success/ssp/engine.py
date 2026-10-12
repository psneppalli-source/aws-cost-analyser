"""Success Score, risk flags, segments and suggested actions.

Score      : each applicable indicator is normalised to 0-100 between fixed
             anchors, weighted (pillar weight x weight within pillar), and the
             weights are re-scaled over the indicators that have data. Missing
             indicators are listed, never zero-filled. Coverage below the
             configured thresholds makes the score provisional or withholds it.
Risk       : academic and placement risk are separate, rule-based and
             configurable. Each triggered rule is kept as evidence (value,
             threshold, source). Missing required evidence gives
             "Insufficient data", which is not the same as "Low".
Snapshots  : one per review period per scoring version, so earlier scores stay
             reproducible after rules change.
"""

from __future__ import annotations

import uuid
from datetime import date

from . import audit, config, records
from .audit import now_iso
from .features import Index, compute
from .storage import get_store

INSUFFICIENT = "Insufficient data"
NOT_APPLICABLE = "Not applicable"


def _applies(rule_or_ind: dict, f: dict) -> bool:
    a = rule_or_ind.get("applies")
    return not (a == "placement_years" and not f.get("placement_year"))


def compare(value, op: str, target) -> bool:
    if value is None:
        return False
    if op == "between":
        return target[0] <= value < target[1]
    return {"<": value < target, "<=": value <= target, ">": value > target, ">=": value >= target,
            "==": value == target, "!=": value != target}[op]


def band(cfg: dict, score: float | None) -> str:
    if score is None:
        return INSUFFICIENT
    for b in cfg["bands"]:
        if score >= b["min"]:
            return b["label"]
    return cfg["bands"][-1]["label"]


# --------------------------------------------------------------------------- score
def success_score(f: dict, cfg: dict) -> dict:
    inds, avail_w, total_w = [], 0.0, 0.0
    for ind in cfg["indicators"]:
        w = cfg["pillars"][ind["pillar"]]["weight"] * ind["weight"]
        entry = {"id": ind["id"], "label": config.label(cfg, ind["id"]), "pillar": ind["pillar"],
                 "value": f.get(ind["id"]), "worst": ind["worst"], "best": ind["best"], "weight": round(w, 4)}
        if not _applies(ind, f):
            entry["status"] = "not_applicable"
        elif f.get(ind["id"]) is None:
            entry["status"] = "missing"
            total_w += w
        else:
            v = float(f[ind["id"]])
            entry["indicator_score"] = round(max(0.0, min(100.0, (v - ind["worst"]) / (ind["best"] - ind["worst"]) * 100)), 1)
            entry["status"] = "used"
            avail_w += w
            total_w += w
        inds.append(entry)
    coverage = avail_w / total_w if total_w else 0.0
    score = None
    for e in inds:
        if e["status"] == "used":
            e["weight_share"] = round(e["weight"] / avail_w, 4)
            e["points"] = round(e["weight"] / avail_w * e["indicator_score"], 2)
            e["max_points"] = round(e["weight"] / avail_w * 100, 2)
    pillars = {}
    for p in cfg["pillars"]:
        used = [e for e in inds if e["pillar"] == p and e["status"] == "used"]
        pw = sum(e["weight"] for e in used)
        pillars[p] = round(sum(e["weight"] * e["indicator_score"] for e in used) / pw, 1) if pw else None
    status = "ok"
    if coverage < cfg["coverage"]["insufficient_below"]:
        status = "insufficient"
    else:
        score = round(sum(e["points"] for e in inds if e["status"] == "used"), 1)
        if coverage < cfg["coverage"]["provisional_below"] or pillars.get("academic") is None or pillars.get("attendance") is None:
            status = "provisional"
    return {"score": score, "band": band(cfg, score), "status": status, "coverage": round(coverage, 3),
            "pillars": pillars, "indicators": inds,
            "missing": [e["label"] for e in inds if e["status"] == "missing"]}


# --------------------------------------------------------------------------- risk
def assess_risk(kind: str, f: dict, sources: dict, cfg: dict) -> dict:
    spec = cfg["risk"][kind]
    if not _applies(spec, f):
        return {"level": NOT_APPLICABLE, "points": 0, "evidence": [], "missing": [], "actions": []}
    evidence, points = [], 0
    for r in spec["rules"]:
        v = f.get(r["feature"])
        if compare(v, r["op"], r["value"]):
            points += r["points"]
            meta = cfg["features"].get(r["feature"], {})
            evidence.append({"rule": r["id"], "why": r["why"], "feature": r["feature"], "label": meta.get("label", r["feature"]),
                             "value": v, "op": r["op"], "threshold": r["value"], "points": r["points"],
                             "unit": meta.get("unit", ""), "source": sources.get(meta.get("source")), "action": r.get("action"),
                             "sensitive": r.get("sensitive", False)})
    missing = [config.label(cfg, x) for x in spec.get("required_all", []) if f.get(x) is None]
    any_req = spec.get("required_any")
    if any_req and all(f.get(x) is None for x in any_req):
        missing.append(" or ".join(config.label(cfg, x) for x in any_req))
    level = next(lv["name"] for lv in cfg["risk"]["levels"] if points >= lv["min_points"])
    top = cfg["risk"]["levels"][0]["name"]
    if missing and level != top:
        level = INSUFFICIENT  # cannot call it Low (or Medium) without the core evidence
    actions = [e["action"] for e in sorted(evidence, key=lambda e: -e["points"]) if e.get("action")]
    if missing and spec.get("missing_action"):
        actions.insert(0, spec["missing_action"])
    return {"level": level, "points": points, "evidence": evidence, "missing": missing,
            "actions": list(dict.fromkeys(actions))}


# --------------------------------------------------------------------------- segments
def _eval(cond: dict, ctx: dict, cfg: dict, reasons: list) -> bool:
    if "all" in cond:
        sub = []
        ok = all(_eval(c, ctx, cfg, sub) for c in cond["all"])
        if ok:
            reasons += sub
        return ok
    if "any" in cond:
        for c in cond["any"]:
            sub = []
            if _eval(c, ctx, cfg, sub):
                reasons += sub
                return True
        return False
    v = ctx.get(cond["feature"])
    ok = compare(v, cond["op"], cond["value"])
    if ok and cond["feature"] != "placement_year":
        meta = cfg["features"].get(cond["feature"], {})
        shown = v if not isinstance(v, float) else round(v, 2)
        reasons.append(f"{meta.get('label', cond['feature'])} is {shown}{meta.get('unit', '') if isinstance(v, (int, float)) and not isinstance(v, bool) else ''}"
                       f" ({cond['op']} {cond['value']})")
    return ok


def segment(ctx: dict, cfg: dict) -> dict:
    if ctx.get("score") is None:
        return {"id": "insufficient", "label": "Not enough data to segment", "reasons": ["Success Score withheld (data coverage too low)"]}
    for s in cfg["segments"]:
        reasons: list = []
        if _eval(s["when"], ctx, cfg, reasons):
            return {"id": s["id"], "label": s["label"], "reasons": reasons or ["Does not meet any other segment's criteria"]}
    return {"id": "steady", "label": "Steady", "reasons": []}


# --------------------------------------------------------------------------- actions
def suggested_actions(f: dict, risks: dict, cfg: dict) -> list[dict]:
    out, seen = [], set()
    for kind in ("academic", "placement"):
        for aid in risks[kind]["actions"]:
            if aid in seen:
                continue
            seen.add(aid)
            a = cfg["actions"][aid]
            fill = {k: ("" if v is None else v) for k, v in f.items()}
            rules = [e["rule"] for e in risks[kind]["evidence"] if e.get("action") == aid]
            out.append({"action_id": aid, "risk": kind, "title": a["title"].format_map(_Safe(fill)),
                        "detail": a["detail"].format_map(_Safe(fill)), "owner_role": a["owner_role"],
                        "due_days": a["due_days"], "review_days": a["review_days"],
                        "rules": rules or ["missing evidence"]})
    return out


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


# --------------------------------------------------------------------------- recalculation
def recalculate(principal, reason: str = "") -> dict:
    store = get_store()
    cfg = config.active()
    with store.lock("scoring", ttl=300):
        idx = Index()
        students = list(records.roster().values())
        run_id = now_iso().replace(":", "").replace("-", "") + "-" + uuid.uuid4().hex[:6]
        prev_ctx: dict[str, dict] = {}
        counts = {}
        for period in sorted(cfg["review_periods"], key=lambda p: p["start"]):
            snap = {}
            for st in students:
                feat = compute(idx, st, period, cfg)
                if feat is None:
                    continue
                f = feat["features"]
                sc = success_score(f, cfg)
                risks = {k: assess_risk(k, f, feat["sources"], cfg) for k in ("academic", "placement")}
                prev = prev_ctx.get(st["student_id"])
                ctx = {**f, "score": sc["score"], "academic_level": risks["academic"]["level"],
                       **{f"pillar_{k}": v for k, v in sc["pillars"].items()},
                       "attendance_change": _delta(f.get("attendance_pct"), prev and prev.get("attendance_pct")),
                       "internal_change": _delta(f.get("internal_pct"), prev and prev.get("internal_pct")),
                       "score_change": _delta(sc["score"], prev and prev.get("score"))}
                seg = segment(ctx, cfg)
                snap[st["student_id"]] = {
                    "student_id": st["student_id"], "year": f["year"], "placement_year": f["placement_year"],
                    "score": sc, "risk": risks, "segment": seg, "features": f, "sources": feat["sources"],
                    "series": feat["series"], "detail": feat["detail"],
                    "changes": {k: ctx[k] for k in ("attendance_change", "internal_change", "score_change")},
                    "actions": suggested_actions(f, risks, cfg),
                }
                prev_ctx[st["student_id"]] = ctx
            store.put_json(f"snapshots/{cfg['version']}/{period['id']}.json.gz",
                           {"period": period["id"], "version": cfg["version"], "run_id": run_id,
                            "computed_at": now_iso(), "data_version": records.meta()["version"], "students": snap})
            counts[period["id"]] = len(snap)
        run = {"run_id": run_id, "version": cfg["version"], "computed_at": now_iso(), "reason": reason,
               "by": getattr(principal, "username", principal), "data_version": records.meta()["version"],
               "students": counts}
        store.table.put("RUN", run_id, run)
        store.table.put("META", "scoring", run)
    audit.log(principal, "scoring.recalculated", "scoring", run_id, {"version": cfg["version"], "reason": reason, "students": counts})
    _snap_cache.clear()
    return run


def _delta(a, b):
    return None if a is None or b is None else round(a - b, 1)


_snap_cache: dict = {}


def scoring_meta() -> dict | None:
    return get_store().table.get("META", "scoring")


def snapshot(period: str, version: str | None = None) -> dict:
    m = scoring_meta()
    if not m:
        return {"students": {}}
    version = version or m["version"]
    key = (version, period, m["run_id"])
    if key not in _snap_cache:
        _snap_cache.clear() if len(_snap_cache) > 8 else None
        _snap_cache[key] = get_store().get_json(f"snapshots/{version}/{period}.json.gz") or {"students": {}}
    return _snap_cache[key]


def today() -> date:
    return date.today()
