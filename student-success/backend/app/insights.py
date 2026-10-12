"""Scoring configuration versions and student insight recalculation.

Every accepted change writes a STALE marker in the same transaction as the
data. Recalculation replaces the INSIGHT item and changed SCORE#{period}
items, then removes the marker. If recalculation fails, the marker stays, the
student shows "Recalculation pending" and the repair operation picks it up.
"""

from __future__ import annotations

import json
import time

from . import audit, db
from .settings import curriculum, default_scoring
from .store import C, Check, ConditionFailed, Delete, Put
from .scoring import evaluate

_cfg_cache: dict = {"at": 0.0, "cfg": None}
LIST_FIELDS = ["by_period", "student_id", "dataset", "name", "department", "year", "period", "score", "indicative_score", "status", "band",
               "coverage", "profile", "risk_academic", "risk_placement", "segment_keys", "component_values",
               "calculated_at", "recalc_status", "scoring_version", "mentor_sub", "mentor_name", "support_flag"]


def periods() -> list[str]:
    return curriculum()["reporting_periods"]


def current_period() -> str:
    return periods()[-1]


# --------------------------------------------------------------------------- scoring configuration
def active_config() -> dict:
    if _cfg_cache["cfg"] and time.time() - _cfg_cache["at"] < 30:
        return _cfg_cache["cfg"]
    t = db.table()
    ptr = t.get("CONFIG#SCORING", "ACTIVE")
    if not ptr:
        cfg = default_scoring()
        try:
            t.transact([Put({"pk": "CONFIG#SCORING", "sk": f"V#{cfg['version']}", "config": cfg, "status": "approved",
                             "proposed_by": "system", "approved_by": "system", "reason": "Initial configuration",
                             "created_at": db.now(), "version": 1}, C.not_exists()),
                        Put({"pk": "CONFIG#SCORING", "sk": "ACTIVE", "config_version": cfg["version"], "version": 1},
                            C.not_exists())])
        except ConditionFailed:
            pass  # another instance initialised it first
        ptr = t.get("CONFIG#SCORING", "ACTIVE")
    cfg = t.get("CONFIG#SCORING", f"V#{ptr['config_version']}")["config"]
    _cfg_cache.update(at=time.time(), cfg=cfg)
    return cfg


def reset_config_cache() -> None:
    _cfg_cache.update(at=0.0, cfg=None)


def validate_config(cfg: dict) -> list[str]:
    errs = []
    base = default_scoring()
    for key in ("version", "components", "cohort_profiles", "normalisation", "risk", "coverage_threshold", "segments", "interventions"):
        if key not in cfg:
            errs.append(f"missing '{key}'")
    if errs:
        return errs
    w = sum(c["weight"] for c in cfg["components"].values())
    if abs(w - 1) > 1e-6:
        errs.append(f"component weights add up to {w:.2f}, not 1.00")
    if set(cfg["components"]) != set(base["components"]):
        errs.append("components must be: " + ", ".join(base["components"]))
    if not 0.5 <= cfg["coverage_threshold"] <= 1:
        errs.append("coverage_threshold must be between 0.5 and 1")
    for comp, spec in cfg["normalisation"].items():
        for ind, s in spec["indicators"].items():
            if s["worst"] == s["best"]:
                errs.append(f"{comp}.{ind}: worst and best must differ")
    for kind in ("academic", "placement"):
        for r in cfg["risk"][kind]["rules"]:
            if r["level"] not in ("low", "medium", "high"):
                errs.append(f"rule {r['id']}: level must be low, medium or high")
            if r["op"] not in ("<", "<=", ">", ">="):
                errs.append(f"rule {r['id']}: unsupported operator")
            if r["intervention"] not in cfg["interventions"]:
                errs.append(f"rule {r['id']}: unknown intervention {r['intervention']}")
    return errs


def propose_config(principal, cfg: dict, reason: str) -> dict:
    errs = validate_config(cfg)
    if errs:
        from .categories import ValidationError
        raise ValidationError({"config": "; ".join(errs)})
    item = {"pk": "CONFIG#SCORING", "sk": f"V#{cfg['version']}", "config": cfg, "status": "draft",
            "proposed_by": principal.sub, "proposed_by_name": principal.username, "reason": reason,
            "created_at": db.now(), "version": 1}
    try:
        db.table().put(item, C.not_exists())
    except ConditionFailed:
        from .categories import ValidationError
        raise ValidationError({"version": f"version {cfg['version']} already exists; choose a new version number"}) from None
    audit.log(principal, "scoring.proposed", "scoring_config", cfg["version"], {"reason": reason})
    return {k: item[k] for k in ("status", "proposed_by_name", "reason", "created_at")} | {"config_version": cfg["version"]}


def activate_config(principal, version: str, reason: str, require_second_approver: bool) -> dict:
    t = db.table()
    item = t.get("CONFIG#SCORING", f"V#{version}")
    if not item:
        from .categories import ValidationError
        raise ValidationError({"version": "unknown configuration version"})
    if require_second_approver and item["proposed_by"] == principal.sub:
        from .policy import Denied
        raise Denied("A different administrator must approve this configuration.")
    ptr = t.get("CONFIG#SCORING", "ACTIVE")
    t.transact([
        Put({**item, "status": "approved", "approved_by": principal.sub, "approved_by_name": principal.username,
             "approved_at": db.now(), "approval_reason": reason, "version": item["version"] + 1}, C.version(item["version"])),
        Put({"pk": "CONFIG#SCORING", "sk": "ACTIVE", "config_version": version, "previous": ptr["config_version"] if ptr else None,
             "version": (ptr["version"] + 1) if ptr else 1}, C.version(ptr["version"]) if ptr else C.not_exists()),
    ])
    reset_config_cache()
    audit.log(principal, "scoring.activated", "scoring_config", version, {"reason": reason,
                                                                           "previous": ptr["config_version"] if ptr else None})
    return {"active": version}


def config_versions() -> list[dict]:
    items, _ = db.table().query("CONFIG#SCORING", "V#")
    return [{"config_version": i["config"]["version"], "status": i["status"], "reason": i.get("reason"),
             "proposed_by": i.get("proposed_by_name", i.get("proposed_by")), "approved_by": i.get("approved_by_name"),
             "created_at": i.get("created_at"), "approved_at": i.get("approved_at"), "description": i["config"].get("description")}
            for i in items]


# --------------------------------------------------------------------------- staleness
def stale_ops(ds: str, sid: str, reason: str) -> list:
    """Operations to include in a data-changing transaction."""
    return [Put({"pk": f"STU#{ds}#{sid}", "sk": "STALE", "gsi2pk": f"STALE#{ds}", "gsi2sk": sid,
                 "reason": reason, "marked_at": db.now()})]


def is_stale(ds: str, sid: str) -> bool:
    return db.table().get(f"STU#{ds}#{sid}", "STALE") is not None


# --------------------------------------------------------------------------- recalculation
def _slim(ins: dict) -> dict:
    return {
        "risk_academic": ins["risks"]["academic"]["level"], "risk_placement": ins["risks"]["placement"]["level"],
        "segment_keys": [s["key"] for s in ins["segments"]],
        "component_values": {c: v["value"] for c, v in ins["components"].items()},
        "support_flag": bool(ins["support_needs"]),
    }


def recompute(ds: str, sid: str, actor="system") -> dict:
    t = db.table()
    pk = f"STU#{ds}#{sid}"
    items, _ = t.query(pk)
    master = next((i for i in items if i["sk"] == "MASTER"), None)
    if not master:
        raise KeyError(f"Unknown student {sid}")
    records = [i for i in items if i["sk"].startswith("REC#")]
    ivs = [i for i in items if i["sk"].startswith("INT#")]
    cfg = active_config()
    ts = db.now()
    ins = evaluate(master, records, ivs, cfg, periods(), ts)
    old_scores = {i["sk"]: i for i in items if i["sk"].startswith("SCORE#")}
    ops = []
    for h in ins["history"]:
        sk = f"SCORE#{h['period']}"
        body = {k: h[k] for k in ("period", "score", "indicative_score", "status", "band", "coverage", "profile", "rows",
                                   "components", "indicators", "sources", "scoring_version", "missing", "risks", "segments")}
        old = old_scores.get(sk)
        if old and json.dumps({k: old.get(k) for k in body}, sort_keys=True, default=str) == json.dumps(body, sort_keys=True, default=str):
            continue  # unchanged: avoid spending write capacity
        ops.append(Put({"pk": pk, "sk": sk, **body, "calculated_at": ts}))
    detail = {k: ins[k] for k in ("score_rows", "components", "indicators", "sources", "risks", "segments", "support_needs",
                                   "eligibility", "trend", "summary", "indicative_score")}
    insight = {"pk": pk, "sk": "INSIGHT", "gsi1pk": f"DEPT#{ds}#{master['department']}",
               "gsi1sk": f"Y{master['year']}#{sid}", "student_id": sid, "dataset": ds, "name": master["name"],
               "department": master["department"], "year": master["year"], "mentor_sub": master.get("mentor_sub"),
               "mentor_name": master.get("mentor_name"), "period": ins["period"], "score": ins["score"],
               "indicative_score": ins["indicative_score"], "status": ins["status"], "band": ins["band"],
               "coverage": ins["coverage"], "profile": ins["profile"], "scoring_version": ins["scoring_version"],
               "calculated_at": ts, "recalc_status": "current", **_slim(ins), "by_period": ins["by_period"]}
    stale = next((i for i in items if i["sk"] == "STALE"), None)
    # Detail lives in its own item (no index keys) so the listed INSIGHT item stays small.
    ops.append(Put({"pk": pk, "sk": "INSIGHTD", "calculated_at": ts, "scoring_version": ins["scoring_version"], **detail}))
    ops.append(Put(insight))
    if stale:
        # Only clear the marker we read; a newer change re-marks it and wins.
        ops.append(Delete(pk, "STALE", C.eq("marked_at", stale["marked_at"])))
    for i in range(0, len(ops), 25):
        try:
            t.transact(ops[i:i + 25])
        except ConditionFailed:
            # A concurrent change re-marked the student; its own recalculation will follow.
            t.transact([o for o in ops[i:i + 25] if not isinstance(o, Delete)])
    invalidate_listing()
    return insight


def mark_failed(ds: str, sid: str) -> None:
    """Keep a failed recalculation visible and repairable: always (re)write the STALE marker that repair() reads,
    and flag the existing insight if there is one. A student whose first calculation failed must not vanish."""
    t = db.table()
    t.put({"pk": f"STU#{ds}#{sid}", "sk": "STALE", "gsi2pk": f"STALE#{ds}", "gsi2sk": sid,
           "reason": "recalculation failed", "marked_at": db.now()})
    ins = t.get(f"STU#{ds}#{sid}", "INSIGHT")
    if ins:
        t.put({**ins, "recalc_status": "stale"})


def recompute_safely(ds: str, sid: str) -> str:
    try:
        recompute(ds, sid)
        return "current"
    except Exception:  # keep the marker; surface as stale
        try:
            mark_failed(ds, sid)
        except Exception:
            pass
        return "stale"


def repair(ds: str, budget_seconds: float = 12.0, everyone: bool = False) -> dict:
    """Recompute stale students (or all, after a configuration change) within a time budget."""
    t = db.table()
    start = time.time()
    if everyone:
        ids = [i["student_id"] for d in curriculum()["departments"] for i in t.query(f"DEPT#{ds}#{d}", index="gsi1")[0]]
        for sid in ids:
            t.put({"pk": f"STU#{ds}#{sid}", "sk": "STALE", "gsi2pk": f"STALE#{ds}", "gsi2sk": sid,
                   "reason": "configuration change", "marked_at": db.now()})
    done, failed = 0, 0
    while time.time() - start < budget_seconds:
        batch, _ = t.query(f"STALE#{ds}", index="gsi2", limit=20)
        if not batch:
            break
        for m in batch:
            if time.time() - start >= budget_seconds:
                break
            if recompute_safely(ds, m["gsi2sk"]) == "current":
                done += 1
            else:
                failed += 1
        if failed and failed >= done:
            break
    remaining = len(t.query(f"STALE#{ds}", index="gsi2", limit=500)[0])
    return {"recomputed": done, "failed": failed, "remaining": remaining}


_list_cache: dict = {}
_generation = [0]


def listing(ds: str, dept: str, year: int | None = None) -> list[dict]:
    """Slim insight rows for a department (served from the GSI's projected attributes).

    Cached per container for a few seconds to protect provisioned read capacity;
    any recalculation in this container invalidates the cache immediately."""
    from .settings import settings
    key = (ds, dept, year, _generation[0])
    hit = _list_cache.get(key)
    if hit and time.time() - hit[0] < settings().cache_seconds:
        return hit[1]
    items, _ = db.table().query(f"DEPT#{ds}#{dept}", f"Y{year}#" if year else "", index="gsi1")
    rows = [{k: i.get(k) for k in LIST_FIELDS} for i in items]
    if len(_list_cache) > 64:
        _list_cache.clear()
    _list_cache[key] = (time.time(), rows)
    return rows


def invalidate_listing() -> None:
    _generation[0] += 1
