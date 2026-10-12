"""Student master records, data records, corrections and verification.

Every write:
  * is authorised against the role matrix for the specific student (and subject),
  * uses optimistic concurrency (`version`) so concurrent edits cannot silently overwrite,
  * marks the student stale in the same transaction, then recalculates,
  * records source, reporting period, timestamps and the responsible user,
  * is audited without sensitive values.
"""

from __future__ import annotations

import hashlib
import json

from . import audit, db, insights
from .categories import CATEGORIES, ID_RE, ValidationError, validate, validate_period
from .policy import Denied, Principal, decide, filter_fields, require
from .settings import curriculum
from .store import C, ConditionFailed, Put

DATASETS = ("real",)  # one dataset; records carry the key so a separate dataset can be added later


class Conflict(Exception):
    def __init__(self, message: str, current: dict | None = None):
        super().__init__(message)
        self.current = current


class NotFound(Exception):
    pass


def target(master: dict, subject: str | None = None) -> dict:
    t = {"dataset": master["dataset"], "student_id": master["student_id"], "department": master["department"],
         "year": int(master["year"])}
    if subject is not None:
        t["subject"] = subject
    return t


def get_master(ds: str, sid: str) -> dict:
    if ds not in DATASETS:
        raise NotFound("Unknown dataset")
    m = db.table().get(f"STU#{ds}#{sid}", "MASTER")
    if not m:
        raise NotFound("Student not found")
    return m


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk", "row_hash")}


# --------------------------------------------------------------------------- student master
MASTER_FIELDS = ("name", "department", "year", "programme", "email", "status")


def _validate_master(data: dict, creating: bool) -> dict:
    errors, out = {}, {}
    depts = curriculum()["departments"]
    if creating:
        sid = str(data.get("student_id", "")).strip().upper()
        if not ID_RE.match(sid):
            errors["student_id"] = "must look like CSE24007 (department, admission year, number)"
        out["student_id"] = sid
        ds = data.get("dataset", "real")
        if ds not in DATASETS:
            errors["dataset"] = "must be real"
        out["dataset"] = ds
    for f in MASTER_FIELDS:
        if f not in data and not creating:
            continue
        v = data.get(f)
        if f == "name":
            if not v or len(str(v).strip()) < 2 or len(str(v)) > 100:
                errors[f] = "is required (2-100 characters)"
            out[f] = str(v or "").strip()
        elif f == "department":
            if v not in depts:
                errors[f] = f"must be one of {', '.join(depts)}"
            out[f] = v
        elif f == "year":
            try:
                out[f] = int(v)
                if not 1 <= out[f] <= 4:
                    raise ValueError
            except (TypeError, ValueError):
                errors[f] = "must be 1-4"
        elif f == "programme":
            out[f] = v or curriculum()["programme"]
        elif f == "email":
            if v and ("@" not in str(v) or len(str(v)) > 120):
                errors[f] = "is not a valid email address"
            out[f] = v or None
        elif f == "status":
            if (v or "active") not in ("active", "inactive"):
                errors[f] = "must be active or inactive"
            out[f] = v or "active"
    if errors:
        raise ValidationError(errors)
    return out


def create_master(p: Principal, data: dict, source: str = "manual") -> dict:
    d = _validate_master(data, creating=True)
    t = {"dataset": d["dataset"], "student_id": d["student_id"], "department": d["department"], "year": d["year"]}
    require(p, "student_master", "create", t)
    ts = db.now()
    item = {"pk": f"STU#{d['dataset']}#{d['student_id']}", "sk": "MASTER", **d,
            "source": source, "created_at": ts, "created_by": p.sub, "updated_at": ts, "updated_by": p.sub, "version": 1}
    try:
        db.table().transact([Put(item, C.not_exists()), *insights.stale_ops(d["dataset"], d["student_id"], "created")])
    except ConditionFailed:
        raise Conflict(f"Student {d['student_id']} already exists") from None
    insights.recompute_safely(d["dataset"], d["student_id"])
    audit.log(p, "student.created", "student", d["student_id"], dataset=d["dataset"])
    return _public(item)


def update_master(p: Principal, ds: str, sid: str, data: dict, expected_version: int | None) -> dict:
    m = get_master(ds, sid)
    require(p, "student_master", "update", target(m))
    if expected_version is None:
        raise ValidationError({"version": "is required to update a record"})
    d = _validate_master(data, creating=False)
    new = {**m, **d, "updated_at": db.now(), "updated_by": p.sub, "version": m["version"] + 1}
    try:
        db.table().transact([Put(new, C.version(expected_version)), *insights.stale_ops(ds, sid, "master updated")])
    except ConditionFailed:
        raise Conflict("Someone else changed this student since you opened it. Reload and try again.",
                       _public(get_master(ds, sid))) from None
    insights.recompute_safely(ds, sid)
    audit.log(p, "student.updated", "student", sid, {"fields": sorted(d)}, dataset=ds)
    return _public(new)


# --------------------------------------------------------------------------- records
def record_key(category: str, period: str, data: dict) -> str:
    return f"REC#{category}#{period}#{CATEGORIES[category].subkey_of(data)}"


def row_hash(category: str, period: str, data: dict) -> str:
    return hashlib.sha256(json.dumps([category, period, data], sort_keys=True, default=str).encode()).hexdigest()[:24]


def _write_action(p: Principal, category: str, t: dict, existing: dict | None) -> str:
    """Pick the action the role matrix must allow: students 'submit', staff 'create'/'update'."""
    res = f"record.{category}"
    if decide(p, res, "submit", t) is not None:
        if existing and existing.get("verification") == "verified":
            raise Denied("Verified records can't be edited. Ask the activity coordinator or your mentor.")
        if existing and existing.get("created_by") != p.sub:
            raise Denied("You can only change your own submissions.")
        return "submit"
    action = "update" if existing else "create"
    if decide(p, res, action, t) is None:
        raise Denied(f"Your role can't {action} {CATEGORIES[category].label.lower()} for this student.")
    return action


def upsert(p: Principal, ds: str, sid: str, category: str, period: str, data: dict,
           expected_version: int | None = None, source: str = "manual", import_ctx: dict | None = None,
           recalc: bool = True) -> dict:
    if category not in CATEGORIES:
        raise ValidationError({"category": "unknown category"})
    validate_period(period)
    clean = validate(category, data)
    m = get_master(ds, sid)
    subject = clean.get("subject") if category in ("marks", "attendance") else None
    if subject is not None and subject not in curriculum()["departments"][m["department"]]["subjects"][str(m["year"])]:
        raise ValidationError({"subject": f"{subject} is not taught to {m['department']} year {m['year']}"})
    t = target(m, subject)
    sk = record_key(category, period, clean)
    table = db.table()
    existing = table.get(f"STU#{ds}#{sid}", sk)
    action = _write_action(p, category, t, existing)
    cat = CATEGORIES[category]
    h = row_hash(category, period, clean)
    if existing and {k: existing.get(k) for k in clean} == clean:
        return {"status": "unchanged", "record": _public(existing)}

    if existing:
        # Manual edits must name the version they started from; imports use the version seen at preview.
        base = expected_version if import_ctx is None else import_ctx.get("base_versions", {}).get(f"{sid}|{sk}")
        if import_ctx is None and base is None:
            raise ValidationError({"version": "is required to change an existing record"})
        if base is not None and base != existing["version"]:
            raise Conflict("This record changed since you loaded it. Reload and try again.", _public(existing))

    if existing and cat.correction_required and "college_admin" not in p.roles:
        return _request_correction(p, m, category, period, sk, clean, existing, source)

    ts = db.now()
    item = {"pk": f"STU#{ds}#{sid}", "sk": sk, "student_id": sid, "dataset": ds, "department": m["department"],
            "year": m["year"], "category": category, "period": period, "subkey": cat.subkey_of(clean), **clean,
            "source": source, "created_at": existing["created_at"] if existing else ts,
            "created_by": existing["created_by"] if existing else p.sub, "updated_at": ts, "updated_by": p.sub,
            "version": (existing["version"] + 1) if existing else 1, "row_hash": h}
    if cat.verification:
        item["verification"] = "pending" if action == "submit" else "verified"
        if item["verification"] == "verified":
            item["verified_by"], item["verified_at"] = p.sub, ts
        else:  # sparse index: only pending submissions appear in the verification queue
            item["gsi1pk"], item["gsi1sk"] = f"VERIFY#{ds}", f"{ts}#{sid}#{sk}"
    if import_ctx:
        item["import_id"] = import_ctx["import_id"]
    retry_ok = C.all(C.eq("import_id", import_ctx["import_id"]), C.eq("row_hash", h)) if import_ctx else None
    cond = C.not_exists() if not existing else C.version(existing["version"])
    if retry_ok is not None:
        cond = C.any(cond, retry_ok)
    try:
        table.transact([Put(item, cond), *insights.stale_ops(ds, sid, f"{category} {period}")])
    except ConditionFailed:
        raise Conflict("This record changed while you were saving. Reload and try again.",
                       _public(table.get(f"STU#{ds}#{sid}", sk) or {})) from None
    if recalc:
        insights.recompute_safely(ds, sid)
    audit.log(p, f"record.{'updated' if existing else 'created'}", category, f"{sid}/{period}",
              {"source": source, "fields": [f.name for f in cat.fields if not f.sensitive]}, dataset=ds)
    return {"status": "updated" if existing else "created", "record": _public(item)}


def _request_correction(p, m, category, period, sk, clean, existing, source) -> dict:
    cid = db.new_id("C")
    ts = db.now()
    item = {"pk": f"STU#{m['dataset']}#{m['student_id']}", "sk": f"CORR#{cid}", "correction_id": cid,
            "gsi1pk": f"DEPTCORR#{m['dataset']}#{m['department']}", "gsi1sk": f"pending#{ts}#{cid}",
            "student_id": m["student_id"], "student_name": m["name"], "dataset": m["dataset"], "department": m["department"],
            "year": m["year"], "category": category, "period": period, "record_sk": sk, "proposed": clean,
            "current": {k: existing.get(k) for k in clean}, "base_version": existing["version"], "status": "pending",
            "requested_by": p.sub, "requested_by_name": p.username, "requested_at": ts, "source": source, "version": 1}
    db.table().put(item, C.not_exists())
    audit.log(p, "correction.requested", category, f"{m['student_id']}/{period}", dataset=m["dataset"])
    return {"status": "pending_correction", "correction": _public(item)}


def list_corrections(p: Principal, ds: str, status: str = "pending") -> list[dict]:
    out = []
    for dept in curriculum()["departments"]:
        items, _ = db.table().query(f"DEPTCORR#{ds}#{dept}", f"{status}#", index="gsi1", limit=200)
        for i in items:
            t = {"dataset": ds, "student_id": i["student_id"], "department": i["department"], "year": i["year"]}
            if decide(p, "correction", "read", t) is not None or (decide(p, "correction", "read", {**t, "subject": i["proposed"].get("subject")}) is not None):
                out.append(_public(i))
    return out


def decide_correction(p: Principal, ds: str, sid: str, cid: str, approve: bool, reason: str) -> dict:
    t = db.table()
    pk = f"STU#{ds}#{sid}"
    c = t.get(pk, f"CORR#{cid}")
    if not c:
        raise NotFound("Correction not found")
    m = get_master(ds, sid)
    require(p, "correction", "approve", target(m))
    if c["requested_by"] == p.sub:
        raise Denied("You can't approve your own correction.")
    if c["status"] != "pending":
        raise Conflict(f"This correction is already {c['status']}.")
    ts = db.now()
    status = "approved" if approve else "rejected"
    upd = {**c, "status": status, "gsi1sk": f"{status}#{c['requested_at']}#{cid}", "decided_by": p.sub,
           "decided_by_name": p.username, "decided_at": ts, "decision_reason": reason, "version": c["version"] + 1}
    ops = [Put(upd, C.version(c["version"]))]
    if approve:
        rec = t.get(pk, c["record_sk"])
        if not rec or rec["version"] != c["base_version"]:
            upd.update(status="conflict", gsi1sk=f"conflict#{c['requested_at']}#{cid}")
            t.put(upd, C.version(c["version"]))
            raise Conflict("The record changed after this correction was requested. Ask for a fresh correction.")
        new = {**rec, **c["proposed"], "updated_at": ts, "updated_by": c["requested_by"], "approved_by": p.sub,
               "version": rec["version"] + 1, "source": f"correction:{cid}"}
        ops += [Put(new, C.version(rec["version"])), *insights.stale_ops(ds, sid, f"correction {cid}")]
    try:
        t.transact(ops)
    except ConditionFailed:
        raise Conflict("Something changed while deciding this correction. Reload and try again.") from None
    if approve:
        insights.recompute_safely(ds, sid)
    audit.log(p, f"correction.{status}", c["category"], f"{sid}/{c['period']}", {"correction": cid}, dataset=ds)
    return _public(upd)


def verify(p: Principal, ds: str, sid: str, category: str, sk: str, decision: str, expected_version: int) -> dict:
    if category not in ("certification", "engagement"):
        raise ValidationError({"category": "only certifications and engagement need verification"})
    if decision not in ("verified", "rejected"):
        raise ValidationError({"decision": "must be verified or rejected"})
    m = get_master(ds, sid)
    require(p, f"record.{category}", "verify", target(m))
    t = db.table()
    rec = t.get(f"STU#{ds}#{sid}", sk)
    if not rec or rec["category"] != category:
        raise NotFound("Record not found")
    new = {k: v for k, v in rec.items() if k not in ("gsi1pk", "gsi1sk")}
    new.update(verification=decision, verified_by=p.sub, verified_at=db.now(), updated_by=p.sub, updated_at=db.now(),
               version=rec["version"] + 1)
    try:
        t.transact([Put(new, C.version(expected_version)), *insights.stale_ops(ds, sid, f"{category} {decision}")])
    except ConditionFailed:
        raise Conflict("This submission changed since you loaded it.", _public(rec)) from None
    insights.recompute_safely(ds, sid)
    audit.log(p, f"record.{decision}", category, f"{sid}/{rec['period']}", dataset=ds)
    return _public(new)


def verification_queue(p: Principal, ds: str) -> list[dict]:
    """Pending student submissions this user may verify (sparse gsi1 VERIFY#{ds}; no table scan)."""
    items, _ = db.table().query(f"VERIFY#{ds}", index="gsi1", limit=200)
    out = []
    for i in items:
        t = {"dataset": ds, "student_id": i["student_id"], "department": i["department"], "year": i["year"]}
        if i.get("verification") == "pending" and decide(p, f"record.{i['category']}", "verify", t) is not None:
            out.append({**_public(i), "record_key": i["sk"]})
    return out


def list_records(p: Principal, ds: str, sid: str, category: str | None = None, period: str | None = None) -> list[dict]:
    m = get_master(ds, sid)
    if decide(p, "student_master", "read", target(m)) is None:
        raise Denied("You don't have access to this student.")
    prefix = "REC#" + (f"{category}#" if category else "") + (f"{period}#" if category and period else "")
    items, _ = db.table().query(f"STU#{ds}#{sid}", prefix)
    out = []
    for i in items:
        if period and i["period"] != period:
            continue
        t = target(m, i.get("subject")) if i["category"] in ("marks", "attendance") else target(m)
        f = decide(p, f"record.{i['category']}", "read", t)
        if f is None and i["category"] in ("marks", "attendance"):
            f = decide(p, f"record.{i['category']}", "read", target(m))
        if f is None:
            continue
        r = {**_public(i), "record_key": i["sk"]}
        if i["category"] == "feedback" and p.student != (ds, sid) and not ({"mentor", "hod", "college_admin"} & p.roles):
            r.pop("comment", None)
        out.append(filter_fields(r, f))
    return out
