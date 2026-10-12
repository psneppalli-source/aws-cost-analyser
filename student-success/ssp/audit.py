"""Append-only audit log: uploads, scoring changes, intervention updates, logins,
user management and profile views. Partitioned by month so reads stay cheap."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .storage import get_store


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(principal, action: str, entity: str = "", entity_id: str = "", details: dict | None = None,
        ip: str = "") -> None:
    ts = now_iso()
    entry = {
        "ts": ts,
        "username": getattr(principal, "username", principal or "system"),
        "role": getattr(principal, "role", "system"),
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "details": details or {},
        "ip": ip,
    }
    get_store().table.put(f"AUDIT#{ts[:7]}", f"{ts}#{uuid.uuid4().hex[:8]}", entry)


def recent(months: list[str], action: str = "", limit: int = 500) -> list[dict]:
    out = []
    for m in months:
        out += get_store().table.query(f"AUDIT#{m}", newest_first=True, limit=limit)
        if len(out) >= limit:
            break
    if action:
        out = [e for e in out if e["action"].startswith(action)]
    return out[:limit]
