"""Canonical records: one gzipped JSON object per category, keyed by natural key.

Each row carries provenance: the upload that last changed it, the reporting
period declared for that upload, the source file name and the time it changed.
A single metadata item records the data version, which caches key off.
"""

from __future__ import annotations

from .storage import get_store

_cache: dict = {"version": None, "data": {}}


def _key(category: str) -> str:
    return f"records/{category}.json.gz"


def meta() -> dict:
    return get_store().table.get("META", "data") or {"version": 0, "updated_at": None, "categories": {}}


def load(category: str) -> dict[str, dict]:
    m = meta()
    if _cache["version"] != m["version"]:
        _cache["version"], _cache["data"] = m["version"], {}
    if category not in _cache["data"]:
        _cache["data"][category] = get_store().get_json(_key(category)) or {}
    return _cache["data"][category]


def save(category: str, rows: dict[str, dict], upload: dict, stats: dict) -> None:
    """Write a category and bump the data version. Caller must hold the records lock."""
    s = get_store()
    s.put_json(_key(category), rows)  # single-object write: readers see old or new, never partial
    m = meta()
    m["version"] = m.get("version", 0) + 1
    m["updated_at"] = upload["committed_at"]
    m.setdefault("categories", {})[category] = {
        "updated_at": upload["committed_at"], "upload_id": upload["id"], "file": upload["filename"],
        "period": upload["reporting_period"], "rows": len(rows), **stats,
    }
    s.table.put("META", "data", m)
    _cache["version"], _cache["data"] = None, {}


def roster() -> dict[str, dict]:
    return {r["student_id"]: r for r in load("students").values()}
