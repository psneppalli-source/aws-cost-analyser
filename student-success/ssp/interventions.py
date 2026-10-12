"""Interventions: a suggested action becomes a tracked task with an owner,
due and review dates, status history, notes and an outcome. Progress is
measured against the score and risk levels recorded when it was opened."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from . import audit
from .audit import now_iso
from .storage import get_store

STATUSES = ["Open", "In Progress", "Completed"]
OUTCOMES = ["Improved", "No change", "Worse", "Not assessed"]


class InterventionError(Exception):
    pass


def _iso_date(v, name: str) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise InterventionError(f"{name} must be a date (YYYY-MM-DD)") from None


def decorate(item: dict, today: date | None = None) -> dict:
    today = today or date.today()
    open_ = item["status"] != "Completed"
    item = dict(item)
    item["overdue"] = open_ and item["due_date"] < today.isoformat()
    item["review_due"] = open_ and item["review_date"] <= today.isoformat()
    item["days_overdue"] = (today - date.fromisoformat(item["due_date"])).days if item["overdue"] else 0
    return item


def all_items() -> list[dict]:
    return [decorate(i) for i in get_store().table.query("INT")]


def get(iid: str) -> dict | None:
    i = get_store().table.get("INT", iid)
    return decorate(i) if i else None


def create(principal, student: dict, snap: dict, payload: dict, created_at: str | None = None) -> dict:
    title = (payload.get("title") or "").strip()
    if not title:
        raise InterventionError("Give the action a title.")
    today = date.fromisoformat(created_at[:10]) if created_at else date.today()
    due = _iso_date(payload.get("due_date") or (today + timedelta(days=int(payload.get("due_days", 14)))).isoformat(), "Due date")
    review = _iso_date(payload.get("review_date") or (today + timedelta(days=int(payload.get("review_days", 30)))).isoformat(), "Review date")
    if review < due:
        raise InterventionError("Review date can't be before the due date.")
    owner = (payload.get("owner") or "").strip().lower()
    if not owner:
        raise InterventionError("Choose an owner.")
    ts = created_at or now_iso()
    item = {
        "id": f"INT-{ts[:10].replace('-', '')}-{uuid.uuid4().hex[:6]}",
        "student_id": student["student_id"], "student_name": student["name"], "dept": student["department"],
        "action_id": payload.get("action_id") or "custom", "risk": payload.get("risk") or "general",
        "rules": payload.get("rules") or [], "title": title, "detail": (payload.get("detail") or "").strip(),
        "owner": owner, "owner_role": payload.get("owner_role") or "mentor",
        "due_date": due, "review_date": review, "status": "Open",
        "created_by": principal.username, "created_at": ts, "updated_at": ts, "completed_at": None,
        "outcome": None, "outcome_note": None,
        "baseline": {"period": snap.get("period"), "score": snap["score"]["score"],
                     "academic": snap["risk"]["academic"]["level"], "placement": snap["risk"]["placement"]["level"]},
        "notes": [],
    }
    if payload.get("note"):
        item["notes"].append({"at": ts, "by": principal.username, "text": payload["note"].strip()})
    get_store().table.put("INT", item["id"], item)
    audit.log(principal, "intervention.created", "intervention", item["id"],
              {"student": item["student_id"], "title": title, "owner": owner, "due": due})
    return decorate(item)


def update(principal, iid: str, payload: dict, level: str, at: str | None = None) -> dict:
    t = get_store().table
    item = t.get("INT", iid)
    if not item:
        raise InterventionError("Intervention not found.")
    ts = at or now_iso()
    changes = {}
    if level == "full":
        if "status" in payload and payload["status"] != item["status"]:
            if payload["status"] not in STATUSES:
                raise InterventionError(f"Status must be one of {', '.join(STATUSES)}.")
            if payload["status"] == "Completed" and not (payload.get("outcome") or item.get("outcome")):
                raise InterventionError("Record the outcome before marking the action Completed.")
            changes["status"] = [item["status"], payload["status"]]
            item["status"] = payload["status"]
            item["completed_at"] = ts if payload["status"] == "Completed" else None
        for k, name in (("due_date", "Due date"), ("review_date", "Review date")):
            if payload.get(k) and payload[k] != item[k]:
                changes[k] = [item[k], _iso_date(payload[k], name)]
                item[k] = changes[k][1]
        if item["review_date"] < item["due_date"]:
            raise InterventionError("Review date can't be before the due date.")
        if payload.get("owner") and payload["owner"].strip().lower() != item["owner"]:
            changes["owner"] = [item["owner"], payload["owner"].strip().lower()]
            item["owner"] = changes["owner"][1]
        if payload.get("outcome"):
            if payload["outcome"] not in OUTCOMES:
                raise InterventionError(f"Outcome must be one of {', '.join(OUTCOMES)}.")
            changes["outcome"] = [item.get("outcome"), payload["outcome"]]
            item["outcome"] = payload["outcome"]
            item["outcome_note"] = (payload.get("outcome_note") or "").strip() or item.get("outcome_note")
    elif any(k in payload for k in ("status", "due_date", "review_date", "owner", "outcome")):
        raise InterventionError("Your role can add notes to this action but not change it.")
    note = (payload.get("note") or "").strip()
    if note:
        item["notes"].append({"at": ts, "by": principal.username, "text": note,
                              **({"status": changes["status"]} if "status" in changes else {})})
    elif "status" in changes:
        item["notes"].append({"at": ts, "by": principal.username, "text": f"Status changed to {item['status']}",
                              "status": changes["status"]})
    if not changes and not note:
        raise InterventionError("Nothing to update.")
    item["updated_at"] = ts
    t.put("INT", iid, item)
    audit.log(principal, "intervention.updated", "intervention", iid,
              {"student": item["student_id"], "changes": changes, "note_added": bool(note)})
    return decorate(item)
