"""Audit log. Entries record who did what to which object, never tokens,
passwords, feedback comments or full student payloads."""

from __future__ import annotations

from . import db

TECHNICAL = {"user", "role", "system", "auth", "mfa", "registration"}


def log(actor, action: str, entity: str, entity_id: str = "", details: dict | None = None, dataset: str = "") -> None:
    ts = db.now()
    category = "technical" if action.split(".")[0] in TECHNICAL else "academic"
    eid = db.new_id()
    db.table().put({
        "pk": f"AUDIT#{ts[:10]}", "sk": f"{ts}#{eid}", "gsi2pk": f"AUDITCAT#{category}", "gsi2sk": f"{ts}#{eid}",
        "ts": ts, "actor": getattr(actor, "sub", actor or "system"), "actor_name": getattr(actor, "username", actor or "system"),
        "action": action, "entity": entity, "entity_id": entity_id, "dataset": dataset,
        "category": category, "details": details or {},
    })


def list_entries(category: str, limit: int = 50, cursor: str | None = None):
    return db.table().query(f"AUDITCAT#{category}", index="gsi2", limit=limit, cursor=cursor, reverse=True)
