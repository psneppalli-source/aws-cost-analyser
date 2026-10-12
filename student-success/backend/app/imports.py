"""Bulk import: preview, then commit in small retryable batches.

preview  parses CSV/XLSX, maps headers, validates every row with the same rules
         and permissions as manual entry, detects duplicates in the file and
         against stored records, and stores the parsed rows in 25-row batches.
commit   applies batches in order within a time budget. Each row is written
         through recordsvc.upsert with the import ID, so a retried batch is
         recognised and never writes twice. Progress (next batch, counts,
         per-row outcomes) is stored, so a partial import resumes cleanly.
"""

from __future__ import annotations

import csv
import io
import re
import time

from . import audit, db, insights, recordsvc
from .categories import CATEGORIES, ValidationError, validate, validate_period
from .policy import Denied, Principal, decide, grants
from .settings import curriculum
from .store import C, ConditionFailed, Put

BATCH = 25
MAX_ROWS = 2000
MASTER = "student_master"
MASTER_FIELDS = ["student_id", "name", "department", "year", "email", "date_of_birth"]


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def read_rows(filename: str, raw: bytes) -> list[list]:
    if raw[:4] == b"PK\x03\x04" or filename.lower().endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            raise ValidationError({"file": "Excel import is not available; upload CSV"}) from None
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        rows = [["" if c is None else c for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
        wb.close()
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    return [r for r in rows if any(str(c).strip() for c in r)]


def _fields(category: str) -> list[str]:
    if category == MASTER:
        return MASTER_FIELDS
    return ["student_id", "period"] + [f.name for f in CATEGORIES[category].fields]


def template(category: str) -> str:
    if category == MASTER:
        return ",".join(MASTER_FIELDS) + "\nCSE24007,Ananya Rao,CSE,3,ananya@example.edu,2005-08-14\n"
    from .categories import template_csv
    return template_csv(category)


def preview(p: Principal, category: str, dataset: str, filename: str, raw: bytes) -> dict:
    if category != MASTER and category not in CATEGORIES:
        raise ValidationError({"category": "unknown category"})
    if dataset not in recordsvc.DATASETS:
        raise ValidationError({"dataset": "must be real"})
    if not grants(p, "import", "create"):
        raise Denied("Your role can't import data.")
    table = read_rows(filename, raw)
    if not table:
        raise ValidationError({"file": "the file is empty"})
    if len(table) - 1 > MAX_ROWS:
        raise ValidationError({"file": f"at most {MAX_ROWS} rows per import; split the file"})
    expected = _fields(category)
    lookup = {_norm(f): f for f in expected}
    mapping = {i: lookup[_norm(h)] for i, h in enumerate(table[0]) if _norm(h) in lookup}
    missing = [f for f in expected if f not in mapping.values() and (f in ("student_id", "period") or
               (category != MASTER and next(x for x in CATEGORIES[category].fields if x.name == f).required) or
               (category == MASTER and f not in ("email", "date_of_birth")))]
    if missing:
        raise ValidationError({"columns": f"missing required column(s): {', '.join(missing)}"})
    ignored = [str(h) for i, h in enumerate(table[0]) if i not in mapping and str(h).strip()]
    rows, seen = [], {}
    base_versions = {}
    for n, cells in enumerate(table[1:], start=2):
        raw_row = {f: (cells[i] if i < len(cells) else "") for i, f in mapping.items()}
        r = {"row": n, "status": "accepted", "errors": [], "action": None, "data": None}
        sid = str(raw_row.get("student_id", "")).strip().upper()
        r["student_id"] = sid
        try:
            if category == MASTER:
                d = recordsvc._validate_master({**raw_row, "student_id": sid, "dataset": dataset}, creating=True)
                key = sid
                existing = db.table().get(f"STU#{dataset}#{sid}", "MASTER")
                t = {"dataset": dataset, "student_id": sid, "department": d["department"], "year": d["year"]}
                if decide(p, "student_master", "update" if existing else "create", t) is None:
                    raise ValidationError({"permission": "your role can't create or change this student"})
                if existing and all(existing.get(k) == d.get(k) for k in ("name", "department", "year")):
                    r["action"] = "unchanged"
                elif existing:
                    raise ValidationError({"student_id": "already exists; edit the student record instead"})
                else:
                    r["action"] = "create"
                r["data"] = {k: d.get(k) for k in MASTER_FIELDS}
            else:
                period = validate_period(str(raw_row.get("period", "")).strip())
                d = validate(category, raw_row)
                m = db.table().get(f"STU#{dataset}#{sid}", "MASTER")
                if not m:
                    raise ValidationError({"student_id": f"{sid or '(blank)'} is not a known student in the {dataset} dataset"})
                subject = d.get("subject") if category in ("marks", "attendance") else None
                if subject and subject not in curriculum()["departments"][m["department"]]["subjects"][str(m["year"])]:
                    raise ValidationError({"subject": f"{subject} is not taught to {m['department']} year {m['year']}"})
                t = recordsvc.target(m, subject)
                sk = recordsvc.record_key(category, period, d)
                existing = db.table().get(f"STU#{dataset}#{sid}", sk)
                action = "update" if existing else "create"
                if decide(p, f"record.{category}", action, t) is None:
                    raise ValidationError({"permission": f"your role can't {action} this {CATEGORIES[category].label.lower()} record"})
                if existing and {k: existing.get(k) for k in d} == d:
                    action = "unchanged"
                elif existing and CATEGORIES[category].correction_required and "college_admin" not in p.roles:
                    raise ValidationError({"record": "a verified record already exists; request a correction instead"})
                if existing:
                    base_versions[f"{sid}|{sk}"] = existing["version"]
                key = f"{sid}|{sk}"
                r["action"] = action
                r["data"] = {"period": period, **d}
            if key in seen:
                first = rows[seen[key]]
                if first["data"] == r["data"]:
                    r.update(status="duplicate", errors=[f"exact duplicate of row {first['row']}; ignored"])
                else:
                    r.update(status="rejected", errors=[f"conflicts with row {first['row']} (same key, different values)"])
                    if first["status"] == "accepted":
                        first.update(status="rejected", errors=[f"conflicts with row {n} (same key, different values)"])
            else:
                seen[key] = len(rows)
        except ValidationError as e:
            r.update(status="rejected", errors=[f"{k}: {v}" for k, v in e.errors.items()])
        rows.append(r)

    iid = db.new_id("IMP")
    ts = db.now()
    accepted = [r for r in rows if r["status"] == "accepted"]
    batches = [accepted[i:i + BATCH] for i in range(0, len(accepted), BATCH)]
    meta = {"pk": f"IMPORT#{iid}", "sk": "META", "gsi2pk": "IMPORTS", "gsi2sk": f"{ts}#{iid}", "import_id": iid,
            "category": category, "dataset": dataset, "filename": filename[:120], "created_by": p.sub,
            "created_by_name": p.username, "created_at": ts, "status": "previewed" if accepted else "rejected",
            "total_rows": len(rows), "accepted": len(accepted), "rejected": sum(r["status"] == "rejected" for r in rows),
            "duplicates": sum(r["status"] == "duplicate" for r in rows),
            "planned": {a: sum(r["action"] == a for r in accepted) for a in ("create", "update", "unchanged")},
            "batches_total": len(batches), "next_batch": 0, "written": 0, "unchanged": 0, "failed": 0,
            "ignored_columns": ignored, "mapping": {str(table[0][i]): f for i, f in mapping.items()}, "version": 1}
    ops = [Put(meta, C.not_exists())]
    for b, chunk in enumerate(batches):
        keys = {f"{r['student_id']}|" for r in chunk}
        ops.append(Put({"pk": f"IMPORT#{iid}", "sk": f"BATCH#{b:04d}", "rows": chunk, "state": "pending",
                        "base_versions": {k: v for k, v in base_versions.items() if k.split("|", 1)[0] + "|" in keys}}))
    problems = [r for r in rows if r["status"] != "accepted"]
    ops.append(Put({"pk": f"IMPORT#{iid}", "sk": "PROBLEMS", "rows": problems[:500]}))
    for i in range(0, len(ops), 25):
        db.table().transact(ops[i:i + 25])
    audit.log(p, "import.previewed", category, iid, {"rows": len(rows), "accepted": len(accepted)}, dataset=dataset)
    return get(p, iid)


def _meta(iid: str) -> dict:
    m = db.table().get(f"IMPORT#{iid}", "META")
    if not m:
        raise recordsvc.NotFound("Import not found")
    return m


def get(p: Principal, iid: str) -> dict:
    m = _meta(iid)
    if m["created_by"] != p.sub and decide(p, "import", "read", None) is None:
        raise Denied()
    probs = db.table().get(f"IMPORT#{iid}", "PROBLEMS") or {"rows": []}
    return {k: v for k, v in m.items() if k not in ("pk", "sk", "gsi2pk", "gsi2sk")} | {"problems": probs["rows"]}


def commit(p: Principal, iid: str, budget_seconds: float = 10.0) -> dict:
    start = time.time()
    tbl = db.table()
    m = _meta(iid)
    if m["created_by"] != p.sub:
        raise Denied("Only the person who previewed this import can apply it.")
    if m["status"] not in ("previewed", "partial", "processing"):
        raise recordsvc.Conflict(f"This import is {m['status']}.")
    while m["next_batch"] < m["batches_total"] and time.time() - start < budget_seconds:
        b = m["next_batch"]
        batch = tbl.get(f"IMPORT#{iid}", f"BATCH#{b:04d}")
        ctx = {"import_id": iid, "base_versions": batch.get("base_versions", {})}
        touched, written, unchanged, failed = set(), 0, 0, 0
        for r in batch["rows"]:
            try:
                if m["category"] == MASTER:
                    if r["action"] == "unchanged":
                        res = {"status": "unchanged"}
                    else:
                        try:
                            res = {"status": "created", "record": recordsvc.create_master(p, {**r["data"], "dataset": m["dataset"]},
                                                                                          source=f"import:{iid}")}
                        except recordsvc.Conflict:
                            res = {"status": "unchanged"}  # created by an earlier attempt of this batch
                else:
                    d = dict(r["data"])
                    period = d.pop("period")
                    res = recordsvc.upsert(p, m["dataset"], r["student_id"], m["category"], period, d,
                                           source=f"import:{iid}", import_ctx=ctx, recalc=False)
                    touched.add(r["student_id"])
                r["outcome"] = res["status"]
                if res["status"] == "unchanged":
                    unchanged += 1
                else:
                    written += 1
            except (recordsvc.Conflict, Denied, ValidationError, recordsvc.NotFound) as e:
                r["outcome"], r["error"] = "failed", str(e)
                failed += 1
        for sid in touched:
            insights.recompute_safely(m["dataset"], sid)
        new = {**m, "next_batch": b + 1, "written": m["written"] + written, "unchanged": m["unchanged"] + unchanged,
               "failed": m["failed"] + failed, "status": "processing", "version": m["version"] + 1, "updated_at": db.now()}
        try:
            tbl.transact([Put({**batch, "rows": batch["rows"], "state": "done"}), Put(new, C.version(m["version"]))])
        except ConditionFailed:
            raise recordsvc.Conflict("This import is being applied in another window.") from None
        m = new
    final = "completed" if m["next_batch"] >= m["batches_total"] else "partial"
    if m["status"] != final:
        new = {**m, "status": final, "version": m["version"] + 1}
        tbl.put(new, C.version(m["version"]))
        m = new
    if final == "completed":
        audit.log(p, "import.completed", m["category"], iid, {"written": m["written"], "unchanged": m["unchanged"],
                                                              "failed": m["failed"]}, dataset=m["dataset"])
    return get(p, iid)


def listing(p: Principal, limit: int = 50) -> list[dict]:
    items, _ = db.table().query("IMPORTS", index="gsi2", limit=limit, reverse=True)
    allowed = decide(p, "import", "read", None) is not None
    return [{k: v for k, v in i.items() if k not in ("pk", "sk", "gsi2pk", "gsi2sk")}
            for i in items if allowed or i["created_by"] == p.sub]
