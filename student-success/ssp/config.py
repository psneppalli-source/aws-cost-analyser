"""Scoring configuration: versioned, validated, audited.

The active version lives in the item table; every version's full JSON is kept
in the blob store, so any past score can be reproduced from its version.
"""

from __future__ import annotations

import json

from . import audit, settings
from .audit import now_iso
from .storage import get_store

OPS = {"<", "<=", ">", ">=", "==", "!=", "between"}
_cache: dict = {"version": None, "cfg": None}


class ConfigError(Exception):
    pass


def validate(cfg: dict) -> list[str]:
    errs = []
    for k in ("version", "current_period", "review_periods", "pillars", "indicators", "risk", "actions", "segments", "features", "courses"):
        if k not in cfg:
            errs.append(f"missing '{k}'")
    if errs:
        return errs
    if abs(sum(p["weight"] for p in cfg["pillars"].values()) - 1) > 1e-6:
        errs.append("pillar weights must add up to 1")
    for p in cfg["pillars"]:
        w = sum(i["weight"] for i in cfg["indicators"] if i["pillar"] == p)
        if abs(w - 1) > 1e-6:
            errs.append(f"indicator weights in pillar '{p}' add up to {w:.2f}, not 1")
    for i in cfg["indicators"]:
        if i["pillar"] not in cfg["pillars"]:
            errs.append(f"indicator {i['id']}: unknown pillar {i['pillar']}")
        if i["id"] not in cfg["features"]:
            errs.append(f"indicator {i['id']}: not in the feature catalogue")
        if i["worst"] == i["best"]:
            errs.append(f"indicator {i['id']}: worst and best anchors are equal")
    if cfg["current_period"] not in {p["id"] for p in cfg["review_periods"]}:
        errs.append("current_period must be one of review_periods")
    levels = cfg["risk"].get("levels", [])
    if not levels or levels[-1]["min_points"] != 0:
        errs.append("risk levels must end with a level at min_points 0")
    for kind in ("academic", "placement"):
        for r in cfg["risk"].get(kind, {}).get("rules", []):
            if r["op"] not in OPS:
                errs.append(f"rule {r['id']}: unknown operator {r['op']}")
            if r["feature"] not in cfg["features"]:
                errs.append(f"rule {r['id']}: unknown feature {r['feature']}")
            if r.get("action") and r["action"] not in cfg["actions"]:
                errs.append(f"rule {r['id']}: unknown action {r['action']}")
    for a in cfg["actions"].values():
        if a.get("owner_role") not in ("mentor", "placement", "hod", "admin"):
            errs.append(f"action {a.get('title')}: owner_role must be mentor, placement, hod or admin")
    if not cfg["segments"] or cfg["segments"][-1]["when"] != {"all": []}:
        errs.append("the last segment must be a catch-all ({\"all\": []})")
    return errs


def active() -> dict:
    store = get_store()
    m = store.table.get("META", "config")
    if not m:
        cfg = json.loads(settings.DEFAULT_CONFIG.read_text())
        activate(cfg, "system", note="initial configuration")
        m = store.table.get("META", "config")
    if _cache["version"] != m["version"]:
        _cache["cfg"] = store.get_json(f"config/{m['version']}.json")
        _cache["version"] = m["version"]
    return _cache["cfg"]


def activate(cfg: dict, principal, note: str = "") -> dict:
    errs = validate(cfg)
    if errs:
        raise ConfigError("; ".join(errs))
    store = get_store()
    key = f"config/{cfg['version']}.json"
    existing = store.get_json(key)
    if existing is not None and existing != cfg:
        raise ConfigError(f"Version {cfg['version']} already exists with different rules. Give the new rules a new version number.")
    store.put_json(key, cfg)
    prev = store.table.get("META", "config")
    store.table.put("META", "config", {"version": cfg["version"], "activated_at": now_iso(),
                                       "activated_by": getattr(principal, "username", principal), "note": note})
    store.table.put("CONFIG", cfg["version"], {"version": cfg["version"], "created_at": now_iso(),
                                               "created_by": getattr(principal, "username", principal),
                                               "note": note, "description": cfg.get("description", "")})
    audit.log(principal, "scoring.config_activated", "config", cfg["version"],
              {"previous": prev["version"] if prev else None, "note": note})
    _cache["version"] = None
    return cfg


def versions() -> list[dict]:
    return get_store().table.query("CONFIG", newest_first=True)


def label(cfg: dict, feature: str) -> str:
    return cfg["features"].get(feature, {}).get("label", feature)
