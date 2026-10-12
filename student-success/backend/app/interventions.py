"""Interventions and staff notes.

* Recommendations come from risk flags with their evidence; staff must confirm
  they reviewed the recommendation before it can be assigned.
* Owners, due and review dates, Open / In Progress / Completed, outcomes.
* Notes have visibility 'staff' or 'confidential'; students never see notes.
* Before/after trends compare the baseline captured at creation with the
  latest comparable score. An increase is reported as an association only.
"""

from __future__ import annotations

from datetime import date

from . import audit, db, insights
from .categories import ValidationError
from .policy import Denied, Principal, constraints, decide, filter_fields, require
from .recordsvc import Conflict, NotFound, get_master, target
from .settings import curriculum
from .store import C, ConditionFailed, Put

STATUSES = ("Open", "In Progress", "Completed")
OUTCOMES = ("improved", "no_change", "declined", "not_assessed")
VISIBILITY = ("staff", "confidential")


def _iso(v, name) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise ValidationError({name: "must be a date (YYYY-MM-DD)"}) from None


def _decorate(i: dict, today: date | None = None) -> dict:
    today = today or date.today()
    out = {k: v for k, v in i.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")}
    open_ = i["status"] != "Completed"
    out["overdue"] = open_ and i["due_date"] < today.isoformat()
    out["review_due"] = open_ and i["review_date"] <= today.isoformat()
    out["days_overdue"] = (today - date.fromisoformat(i["due_date"])).days if out["overdue"] else 0
    return out


def _keys(i: dict) -> dict:
    return {"gsi1pk": f"DEPTINT#{i['dataset']}#{i['department']}", "gsi1sk": f"{i['status']}#{i['due_date']}#{i['intervention_id']}",
            "gsi2pk": f"OWNER#{i['owner_sub']}", "gsi2sk": f"{i['status']}#{i['due_date']}#{i['intervention_id']}"}


def _owner_can_act(owner_sub: str, t: dict) -> dict:
    from .auth import load_principal
    try:
        owner = load_principal(owner_sub)
    except Exception:
        raise ValidationError({"owner_sub": "the owner account is not active"}) from None
    if decide(owner, "intervention", "update", t) is None:
        raise ValidationError({"owner_sub": "the owner is not responsible for this student"})
    return {"owner_sub": owner.sub, "owner_name": owner.display_name}


def _check_category(p: Principal, category: str) -> None:
    allowed = constraints(p, "intervention_categories")
    if allowed is not None and category not in allowed:
        raise Denied("Your role can only manage placement training actions.")


def create(p: Principal, ds: str, sid: str, body: dict) -> dict:
    m = get_master(ds, sid)
    t = target(m)
    require(p, "intervention", "create", t)
    if body.get("reviewed") is not True:
        raise ValidationError({"reviewed": "confirm you reviewed the recommendation and its evidence before assigning it"})
    title = (body.get("title") or "").strip()
    if not 3 <= len(title) <= 120:
        raise ValidationError({"title": "is required (3-120 characters)"})
    category = body.get("category") or "academic"
    if category not in ("academic", "attendance", "wellbeing", "placement_training", "other"):
        raise ValidationError({"category": "unknown category"})
    _check_category(p, category)
    due, review = _iso(body.get("due_date"), "due_date"), _iso(body.get("review_date"), "review_date")
    if review < due:
        raise ValidationError({"review_date": "can't be before the due date"})
    owner = _owner_can_act(body.get("owner_sub") or p.sub, t)
    ins = db.table().get(f"STU#{ds}#{sid}", "INSIGHT") or {}
    iid = db.new_id("I")
    ts = db.now()
    item = {"pk": f"STU#{ds}#{sid}", "sk": f"INT#{iid}", "intervention_id": iid, "student_id": sid, "student_name": m["name"],
            "dataset": ds, "department": m["department"], "year": m["year"], "title": title, "category": category,
            "recommendation_key": body.get("recommendation_key"), "evidence": body.get("evidence") or [],
            "detail": (body.get("detail") or "").strip()[:1000], **owner, "due_date": due, "review_date": review,
            "status": "Open", "outcome": None, "reviewed_by": p.sub, "created_by": p.sub, "created_by_name": p.username,
            "created_at": ts, "updated_at": ts, "updated_by": p.sub, "version": 1,
            "baseline": {"period": ins.get("period"), "score": ins.get("score"), "status": ins.get("status"),
                         "profile": ins.get("profile"), "scoring_version": ins.get("scoring_version"),
                         "academic": ins.get("risk_academic"), "placement": ins.get("risk_placement")}}
    item.update(_keys(item))
    db.table().transact([Put(item, C.not_exists()), *insights.stale_ops(ds, sid, "intervention created")])
    insights.recompute_safely(ds, sid)
    audit.log(p, "intervention.created", "intervention", iid, {"student": sid, "owner": owner["owner_name"]}, dataset=ds)
    return _decorate(item)


def update(p: Principal, ds: str, sid: str, iid: str, body: dict) -> dict:
    m = get_master(ds, sid)
    t = target(m)
    require(p, "intervention", "update", t)
    tbl = db.table()
    cur = tbl.get(f"STU#{ds}#{sid}", f"INT#{iid}")
    if not cur:
        raise NotFound("Intervention not found")
    _check_category(p, cur["category"])
    if body.get("version") != cur["version"]:
        raise Conflict("This intervention changed since you loaded it. Reload and try again.", _decorate(cur))
    new = dict(cur)
    changes = []
    if "status" in body and body["status"] != cur["status"]:
        if body["status"] not in STATUSES:
            raise ValidationError({"status": f"must be one of {', '.join(STATUSES)}"})
        new["status"] = body["status"]
        changes.append("status")
    for k in ("due_date", "review_date"):
        if body.get(k) and body[k] != cur[k]:
            new[k] = _iso(body[k], k)
            changes.append(k)
    if new["review_date"] < new["due_date"]:
        raise ValidationError({"review_date": "can't be before the due date"})
    if body.get("owner_sub") and body["owner_sub"] != cur["owner_sub"]:
        new.update(_owner_can_act(body["owner_sub"], t))
        changes.append("owner")
    if body.get("outcome"):
        o = body["outcome"]
        if o.get("result") not in OUTCOMES:
            raise ValidationError({"outcome": f"result must be one of {', '.join(OUTCOMES)}"})
        ins = tbl.get(f"STU#{ds}#{sid}", "INSIGHT") or {}
        new["outcome"] = {"result": o["result"], "note": (o.get("note") or "").strip()[:1000], "recorded_by": p.sub,
                          "recorded_at": db.now(), "after": {"period": ins.get("period"), "score": ins.get("score"),
                                                             "status": ins.get("status"), "profile": ins.get("profile"),
                                                             "scoring_version": ins.get("scoring_version"),
                                                             "academic": ins.get("risk_academic"),
                                                             "placement": ins.get("risk_placement")}}
        changes.append("outcome")
    if new["status"] == "Completed" and not new.get("outcome"):
        raise ValidationError({"outcome": "record the outcome before completing the intervention"})
    if not changes:
        raise ValidationError({"body": "nothing to change"})
    new.update(updated_at=db.now(), updated_by=p.sub, version=cur["version"] + 1, **_keys(new))
    try:
        tbl.transact([Put(new, C.version(cur["version"])), *insights.stale_ops(ds, sid, "intervention updated")])
    except ConditionFailed:
        raise Conflict("This intervention changed while you were saving. Reload and try again.") from None
    insights.recompute_safely(ds, sid)
    audit.log(p, "intervention.updated", "intervention", iid, {"student": sid, "changed": changes}, dataset=ds)
    return _decorate(new)


def comparison(i: dict, ins: dict) -> dict:
    """Before/after view. Compatible profiles only; never presented as causal."""
    b = i.get("baseline") or {}
    after = (i.get("outcome") or {}).get("after") or {"period": ins.get("period"), "score": ins.get("score"),
                                                          "profile": ins.get("profile"), "scoring_version": ins.get("scoring_version")}
    ok = (b.get("score") is not None and after.get("score") is not None and b.get("profile") == after.get("profile")
          and b.get("scoring_version") == after.get("scoring_version"))
    return {"before": b, "after": after, "comparable": ok, "change": round(after["score"] - b["score"], 1) if ok else None,
            "note": "Scores before and after are shown for context. A change is an association, not proof the intervention caused it."
            if ok else "Not comparable: the score is missing or was calculated under a different profile or scoring version."}


def _visible(p: Principal, i: dict) -> dict | None:
    t = {"dataset": i["dataset"], "student_id": i["student_id"], "department": i["department"], "year": i["year"]}
    f = decide(p, "intervention", "read", t)
    if f is None:
        return None
    allowed = constraints(p, "intervention_categories")
    if allowed is not None and i["category"] not in allowed and i["owner_sub"] != p.sub:
        return None
    return filter_fields(_decorate(i), f)


def for_student(p: Principal, ds: str, sid: str) -> list[dict]:
    items, _ = db.table().query(f"STU#{ds}#{sid}", "INT#")
    ins = db.table().get(f"STU#{ds}#{sid}", "INSIGHT") or {}
    out = []
    for i in items:
        v = _visible(p, i)
        if v is not None:
            if "baseline" in v:
                v["comparison"] = comparison(i, ins)
            out.append(v)
    return sorted(out, key=lambda x: (x["status"] == "Completed", x["due_date"]))


def listing(p: Principal, ds: str, owner: str | None = None, status: str | None = None, dept: str | None = None,
            overdue_only: bool = False, limit: int = 100, cursor: str | None = None) -> tuple[list[dict], str | None]:
    tbl = db.table()
    prefix = f"{status}#" if status else ""
    if owner:
        items, nxt = tbl.query(f"OWNER#{owner}", prefix, index="gsi2", limit=limit, cursor=cursor)
    else:
        depts = [dept] if dept else list(curriculum()["departments"])
        items, nxt = [], None
        for d in depts:
            got, _ = tbl.query(f"DEPTINT#{ds}#{d}", prefix, index="gsi1", limit=500)
            items += got
    out = [v for v in (_visible(p, i) for i in items if i["dataset"] == ds) if v is not None]
    if overdue_only:
        out = [i for i in out if i.get("overdue")]
    out.sort(key=lambda x: (x["status"] == "Completed", not x.get("overdue"), x["due_date"]))
    return out, nxt


# --------------------------------------------------------------------------- notes
def add_note(p: Principal, ds: str, sid: str, iid: str, text: str, visibility: str) -> dict:
    if visibility not in VISIBILITY:
        raise ValidationError({"visibility": "must be staff or confidential"})
    m = get_master(ds, sid)
    require(p, f"note.{visibility}", "create", target(m))
    if not db.table().get(f"STU#{ds}#{sid}", f"INT#{iid}"):
        raise NotFound("Intervention not found")
    text = (text or "").strip()
    if not 1 <= len(text) <= 2000:
        raise ValidationError({"text": "is required (up to 2000 characters)"})
    ts = db.now()
    nid = db.new_id("N")
    item = {"pk": f"STU#{ds}#{sid}", "sk": f"NOTE#{iid}#{ts}#{nid}", "note_id": nid, "intervention_id": iid,
            "visibility": visibility, "text": text, "author_sub": p.sub, "author_name": p.display_name, "created_at": ts}
    db.table().put(item, C.not_exists())
    audit.log(p, "note.added", "intervention", iid, {"visibility": visibility}, dataset=ds)
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}


def notes(p: Principal, ds: str, sid: str, iid: str | None = None) -> list[dict]:
    m = get_master(ds, sid)
    t = target(m)
    can = {v for v in VISIBILITY if decide(p, f"note.{v}", "read", t) is not None}
    if not can:
        return []
    items, _ = db.table().query(f"STU#{ds}#{sid}", f"NOTE#{iid}#" if iid else "NOTE#")
    return [{k: v for k, v in i.items() if k not in ("pk", "sk")} for i in items if i["visibility"] in can]
