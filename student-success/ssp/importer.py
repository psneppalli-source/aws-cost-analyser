"""Two-step data import: validate (stage + summary), then commit.

validate  parses CSV or Excel, maps headers (with aliases), checks every field's
          type, format and range plus cross-field rules, flags duplicate rows
          within the file, student IDs missing from the roster, and blank
          optional values. Nothing is written to the records yet.
commit    applies the accepted rows as upserts on the natural key under the
          records lock. Re-uploading the same rows is a no-op ("unchanged").
          A failure before the single canonical write leaves records untouched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections import Counter

from . import audit, records
from .audit import now_iso
from .schemas import SCHEMAS, coerce, cross_checks, row_key
from .storage import Conflict, get_store

MAX_ERRORS_IN_SUMMARY = 200


class ImportError_(Exception):
    pass


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def read_table(filename: str, raw: bytes) -> list[list]:
    if raw[:4] == b"PK\x03\x04" or filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise ImportError_("Excel support is not installed on the server") from exc
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as exc:
            raise ImportError_(f"Could not open the Excel file: {exc}") from exc
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return [r for r in rows if any(c not in (None, "") for c in r)]
    if filename.lower().endswith(".xls"):
        raise ImportError_("Old .xls files are not supported. Save as .xlsx or .csv and upload again.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportError_("The file is not readable text. Upload a CSV or .xlsx file.")
    rows = list(csv.reader(io.StringIO(text)))
    return [r for r in rows if any(c.strip() for c in r)]


def _map_headers(category: str, header: list) -> tuple[dict[int, str], list[str], list[str]]:
    schema = SCHEMAS[category]
    lookup = {}
    for f in schema.fields:
        for a in [f.name] + f.aliases:
            lookup[_norm(a)] = f.name
    mapping, ignored = {}, []
    for i, h in enumerate(header):
        name = lookup.get(_norm(h))
        if name and name not in mapping.values():
            mapping[i] = name
        elif str(h or "").strip():
            ignored.append(str(h))
    missing = [f.name for f in schema.fields if f.required and f.name not in mapping.values()]
    return mapping, ignored, missing


def validate(category: str, filename: str, raw: bytes, reporting_period: str, principal) -> dict:
    if category not in SCHEMAS:
        raise ImportError_(f"Unknown data category '{category}'")
    if not re.fullmatch(r"20\d{2}-(ODD|EVEN)", reporting_period or ""):
        raise ImportError_("Choose the reporting period this file belongs to (e.g. 2026-ODD).")
    schema = SCHEMAS[category]
    store = get_store()
    upload_id = now_iso()[:10].replace("-", "") + "-" + uuid.uuid4().hex[:8]
    sha = hashlib.sha256(raw).hexdigest()
    summary = {
        "id": upload_id, "category": category, "label": schema.label, "filename": filename,
        "sha256": sha, "reporting_period": reporting_period, "uploaded_by": principal.username,
        "uploaded_at": now_iso(), "status": "validated", "file_errors": [], "warnings": [],
        "total_rows": 0, "accepted": 0, "rejected": 0, "duplicates": 0, "conflicts": 0,
        "unmatched_ids": [], "missing_values": {}, "new": 0, "changed": 0, "unchanged": 0,
        "columns": {}, "ignored_columns": [], "errors": [],
    }
    staged: list[dict] = []
    try:
        table = read_table(filename, raw)
        if not table:
            raise ImportError_("The file is empty.")
        mapping, ignored, missing = _map_headers(category, table[0])
        summary["columns"] = {str(table[0][i]): f for i, f in mapping.items()}
        summary["ignored_columns"] = ignored
        if ignored:
            summary["warnings"].append(f"Ignored columns not in the template: {', '.join(ignored)}")
        if missing:
            raise ImportError_(f"Missing required column(s): {', '.join(missing)}. Download the template to see the expected headers.")
    except ImportError_ as exc:
        summary["status"] = "rejected"
        summary["file_errors"].append(str(exc))
        _save(summary, raw, [])
        audit.log(principal, "upload.rejected", "upload", upload_id, {"category": category, "file": filename, "reason": str(exc)})
        return summary

    roster = records.roster()
    existing = records.load(category)
    seen: dict[str, tuple[int, dict]] = {}
    missing_counter: Counter = Counter()
    unmatched: Counter = Counter()

    for n, cells in enumerate(table[1:], start=2):
        row, errs, warns = {}, [], []
        for i, fname in mapping.items():
            f = schema.field(fname)
            try:
                v = coerce(f, cells[i] if i < len(cells) else None)
            except ValueError as exc:
                errs.append(f"{fname}: {exc}")
                continue
            if v is None:
                if f.required:
                    errs.append(f"{fname} is required")
                else:
                    missing_counter[fname] += 1
                    warns.append(f"{fname} is blank")
            row[fname] = v
        for f in schema.fields:
            row.setdefault(f.name, None)
        if not errs:
            errs += cross_checks(category, row)
        sid = row.get("student_id")
        if sid and category != "students" and sid not in roster:
            errs.append(f"student_id {sid} is not in the student roster")
            unmatched[sid] += 1
        entry = {"row": n, "student_id": sid, "status": "accepted", "errors": errs, "warnings": warns, "data": row}
        if errs:
            entry["status"] = "rejected"
        else:
            k = row_key(category, row)
            if k in seen:
                first_n, first = seen[k]
                if first["data"] == row:
                    entry["status"] = "duplicate"
                    entry["errors"] = [f"exact duplicate of row {first_n}; ignored"]
                else:
                    entry["status"] = "rejected"
                    entry["errors"] = [f"conflicts with row {first_n} (same {', '.join(schema.key)} but different values)"]
                    if first["status"] == "accepted":
                        first["status"] = "rejected"
                        first["errors"] = [f"conflicts with row {n} (same {', '.join(schema.key)} but different values)"]
                        summary["conflicts"] += 1
                    summary["conflicts"] += 1
            else:
                seen[k] = (n, entry)
        staged.append(entry)

    summary["total_rows"] = len(staged)
    for e in staged:
        if e["status"] == "accepted":
            summary["accepted"] += 1
            old = existing.get(row_key(category, e["data"]))
            if old is None:
                summary["new"] += 1
            elif {k: old.get(k) for k in e["data"]} == e["data"]:
                summary["unchanged"] += 1
            else:
                summary["changed"] += 1
        elif e["status"] == "duplicate":
            summary["duplicates"] += 1
        else:
            summary["rejected"] += 1
    summary["missing_values"] = dict(missing_counter)
    summary["unmatched_ids"] = sorted(unmatched)
    summary["errors"] = [{"row": e["row"], "student_id": e["student_id"], "status": e["status"], "errors": e["errors"]}
                         for e in staged if e["status"] != "accepted"][:MAX_ERRORS_IN_SUMMARY]
    prior = [u for u in list_uploads() if u["sha256"] == sha and u["status"] == "committed"]
    if prior:
        summary["warnings"].append(f"This exact file was already imported on {prior[0]['committed_at'][:10]} "
                                   f"(upload {prior[0]['id']}). Importing again changes nothing.")
    if summary["accepted"] == 0:
        summary["status"] = "rejected"
        summary["file_errors"].append("No valid rows to import.")
    _save(summary, raw, staged)
    audit.log(principal, "upload.validated", "upload", upload_id,
              {"category": category, "file": filename, "accepted": summary["accepted"], "rejected": summary["rejected"],
               "duplicates": summary["duplicates"], "status": summary["status"]})
    return summary


def _save(summary: dict, raw: bytes, staged: list[dict]) -> None:
    store = get_store()
    ext = summary["filename"].rsplit(".", 1)[-1].lower() if "." in summary["filename"] else "dat"
    store.blobs.put(f"uploads/{summary['id']}/original.{re.sub(r'[^a-z0-9]', '', ext)[:5]}", raw)
    store.put_json(f"uploads/{summary['id']}/staged.json.gz", staged)
    store.table.put("UPLOAD", summary["id"], summary)


def list_uploads() -> list[dict]:
    return sorted(get_store().table.query("UPLOAD"), key=lambda u: u["uploaded_at"], reverse=True)


def get_upload(upload_id: str) -> dict | None:
    return get_store().table.get("UPLOAD", upload_id)


def commit(upload_id: str, principal, recalc: bool = True) -> dict:
    store = get_store()
    with store.lock():
        summary = get_upload(upload_id)
        if not summary:
            raise ImportError_("Upload not found")
        if summary["status"] != "validated":
            raise ImportError_(f"This upload is '{summary['status']}' and cannot be imported.")
        staged = store.get_json(f"uploads/{upload_id}/staged.json.gz") or []
        category = summary["category"]
        rows = dict(records.load(category))
        if category != "students":
            roster = records.roster()
        ts = now_iso()
        stats = {"new": 0, "changed": 0, "unchanged": 0, "skipped_unmatched": 0}
        for e in staged:
            if e["status"] != "accepted":
                continue
            d = e["data"]
            if category != "students" and d["student_id"] not in roster:
                stats["skipped_unmatched"] += 1  # roster changed since validation
                continue
            k = row_key(category, d)
            old = rows.get(k)
            if old is not None and {f: old.get(f) for f in d} == d:
                stats["unchanged"] += 1
                continue
            stats["new" if old is None else "changed"] += 1
            rows[k] = {**d, "_upload": upload_id, "_period": summary["reporting_period"],
                       "_file": summary["filename"], "_updated": ts}
        summary.update(status="committed", committed_at=ts, committed_by=principal.username, applied=stats)
        records.save(category, rows, summary, stats)
        store.table.put("UPLOAD", upload_id, summary)
    audit.log(principal, "upload.committed", "upload", upload_id, {"category": category, **stats})
    if recalc:
        from . import engine
        try:
            engine.recalculate(principal, reason=f"upload {upload_id} ({category})")
            summary["recalculated"] = True
        except Conflict:
            summary["recalculated"] = False
    return summary


def discard(upload_id: str, principal) -> dict:
    t = get_store().table
    s = get_upload(upload_id)
    if not s:
        raise ImportError_("Upload not found")
    if s["status"] != "validated":
        raise ImportError_(f"This upload is '{s['status']}' and cannot be discarded.")
    s["status"] = "discarded"
    s["discarded_by"] = principal.username
    s["discarded_at"] = now_iso()
    t.put("UPLOAD", upload_id, s)
    audit.log(principal, "upload.discarded", "upload", upload_id, {"category": s["category"]})
    return s
