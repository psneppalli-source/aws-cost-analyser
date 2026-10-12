"""Imports, idempotent seeding, concurrency, recalculation, notes, interventions, datasets."""

import hashlib
import json

import pytest

from app import db, imports, insights, seed
from app.store import C, ConditionFailed, Put

CSE3 = "CSE24004"


def _preview(call, user, category, csv_text, dataset="demo"):
    return call(user, "POST", f"/api/imports/preview?category={category}&dataset={dataset}&filename=t.csv", raw=csv_text.encode())


# --------------------------------------------------------------------------- imports
def test_import_preview_validation_duplicates_and_permissions(call):
    csv = ("student_id,period,subject,classes_held,classes_attended\n"
           f"{CSE3},2026-02,Operating Systems,20,18\n"
           f"{CSE3},2026-02,Operating Systems,20,18\n"              # exact duplicate
           f"CSE24005,2026-02,Operating Systems,20,25\n"             # attended > held
           f"CSE24006,2026-02,Computer Networks,20,18\n"            # subject not taught by this mentor
           f"XX99999,2026-02,Operating Systems,20,18\n"             # unknown student
           f"CSE24007,2026/02,Operating Systems,20,18\n")           # bad period
    r = _preview(call, "mentor.arjun", "attendance", csv)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["accepted"], d["duplicates"], d["rejected"]) == (1, 1, 4)
    msgs = " ".join(" ".join(p["errors"]) for p in d["problems"])
    for needle in ("cannot be more than classes held", "permission", "not a known student", "YYYY-MM", "duplicate"):
        assert needle in msgs


def test_import_commit_is_batched_retryable_and_idempotent(call):
    lines = ["student_id,period,assignments_due,assignments_submitted,logins"]
    lines += [f"CSE24{n:03d},2026-03,5,{n % 5},{10 + n}" for n in range(1, 13)]
    lines += [f"MECH23{n:03d},2026-03,5,4,12" for n in range(1, 21)]  # placement officer can't write LMS -> rejected later? no: mentor
    csv = "\n".join(lines) + "\n"
    d = _preview(call, "mentor.arjun", "lms", csv).json()
    assert d["accepted"] == 12 and d["rejected"] == 20, d["problems"][:3]  # only the mentor's own mentees are accepted
    assert d["batches_total"] == 1
    iid = d["import_id"]
    first = call("mentor.arjun", "POST", f"/api/imports/{iid}/commit").json()
    assert first["status"] == "completed" and first["written"] == 12
    # Simulate a retry of an already-applied batch (e.g. Lambda timed out after writing): reset progress and re-run.
    m = db.table().get(f"IMPORT#{iid}", "META")
    db.table().put({**m, "next_batch": 0, "status": "partial", "version": m["version"] + 1})
    again = call("mentor.arjun", "POST", f"/api/imports/{iid}/commit").json()
    assert again["status"] == "completed" and again["failed"] == 0
    recs = call("mentor.arjun", "GET", "/api/students/demo/CSE24001/records?category=lms&period=2026-03").json()["items"]
    assert len(recs) == 1 and recs[0]["version"] == 1  # no duplicate, no extra write
    d2 = _preview(call, "mentor.arjun", "lms", csv).json()
    assert d2["planned"]["unchanged"] == 12 and d2["planned"]["create"] == 0


def test_import_partial_progress_resumes(call, monkeypatch):
    lines = ["student_id,period,technical,communication"] + [f"MECH23{n:03d},2026-02,{50 + n},{40 + n}" for n in range(1, 13)] \
        + [f"MECH24{n:03d},2026-02,{50 + n},{40 + n}" for n in range(1, 13)] + [f"ECE23{n:03d},2026-02,60,60" for n in range(1, 13)]
    d = _preview(call, "placement.rohit", "skills", "\n".join(lines) + "\n").json()
    assert d["batches_total"] == 2
    real = imports.commit
    monkeypatch.setattr(imports, "commit", lambda p, iid, budget_seconds=10.0: real(p, iid, budget_seconds=0.0001))
    part = call("placement.rohit", "POST", f"/api/imports/{d['import_id']}/commit").json()
    assert part["status"] == "partial" and part["next_batch"] == 1
    monkeypatch.setattr(imports, "commit", real)
    done = call("placement.rohit", "POST", f"/api/imports/{d['import_id']}/commit").json()
    assert done["status"] == "completed" and done["written"] == 36


def test_import_xlsx(call):
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["student_id", "period", "activity_type", "name", "role"])
    ws.append(["ECE25003", "2026-07", "club", "Electronics Club", "Member"])
    buf = io.BytesIO()
    wb.save(buf)
    r = call("activity.sara", "POST", "/api/imports/preview?category=engagement&dataset=demo&filename=e.xlsx", raw=buf.getvalue())
    assert r.status_code == 200 and r.json()["accepted"] == 1


def test_templates_download(call):
    r = call("admin.priya", "GET", "/api/templates/marks.csv")
    assert r.status_code == 200 and r.text.startswith("student_id,period,subject,assessment,score,max_score")


# --------------------------------------------------------------------------- seeding
def test_seed_is_idempotent_and_never_overwrites_staff_changes(call, monkeypatch):
    again = seed.run(with_accounts=True)
    assert again["written"] == 0 and again["accounts"] == 0
    rec = [x for x in call("mentor.arjun", "GET", "/api/students/demo/CSE24008/records?category=lms&period=2026-09").json()["items"]][0]
    upd = call("mentor.arjun", "PUT", "/api/students/demo/CSE24008/records/lms/2026-09",
               {"data": {"assignments_due": 9, "assignments_submitted": 9, "logins": 40}, "version": rec["version"]})
    assert upd.status_code == 200
    monkeypatch.setattr(seed, "SEED_VERSION", seed.SEED_VERSION + 1)  # a newer generator version re-runs
    newer = seed.run(with_accounts=False)
    assert newer["written"] > 0
    after = call("mentor.arjun", "GET", "/api/students/demo/CSE24008/records?category=lms&period=2026-09").json()["items"][0]
    assert after["assignments_due"] == 9 and after["source"] == "manual"  # staff edit kept


def test_demo_records_excluded_from_real_aggregates(call):
    r = call("admin.priya", "POST", "/api/students", {"student_id": "CSE24999", "name": "Real Person", "department": "CSE",
                                                      "year": 3, "dataset": "real"})
    assert r.status_code == 201, r.text
    real = call("admin.priya", "GET", "/api/dashboard").json()
    demo = call("admin.priya", "GET", "/api/dashboard?dataset=demo").json()
    assert real["students"] == 1 and demo["students"] == 150


def test_demo_reset_requires_admin_and_confirmation(call):
    assert call("hod.meenakshi", "POST", "/api/admin/demo/reset", {"confirmation": "RESET DEMO"}).status_code == 403
    assert call("admin.priya", "POST", "/api/admin/demo/reset", {"confirmation": "yes"}).status_code == 422


# --------------------------------------------------------------------------- concurrency
def test_concurrent_edits_conflict_instead_of_overwriting(call):
    s = call("admin.priya", "GET", "/api/students/demo/MECH24003").json()["student"]
    a = call("admin.priya", "PATCH", "/api/students/demo/MECH24003", {"data": {"email": "a@example.edu"}, "version": s["version"]})
    b = call("admin.priya", "PATCH", "/api/students/demo/MECH24003", {"data": {"email": "b@example.edu"}, "version": s["version"]})
    assert a.status_code == 200 and b.status_code == 409
    assert b.json()["error"]["details"]["current"]["email"] == "a@example.edu"


def test_store_conditional_writes_and_transactions_roll_back():
    t = db.table()
    t.put({"pk": "T#1", "sk": "A", "version": 1}, C.not_exists())
    with pytest.raises(ConditionFailed):
        t.put({"pk": "T#1", "sk": "A", "version": 2}, C.not_exists())
    with pytest.raises(ConditionFailed):
        t.transact([Put({"pk": "T#1", "sk": "B", "version": 1}), Put({"pk": "T#1", "sk": "A", "version": 3}, C.version(99))])
    assert t.get("T#1", "B") is None  # whole transaction rolled back


# --------------------------------------------------------------------------- recalculation
def test_score_updates_after_authorised_change_and_repair_heals_failures(call, monkeypatch):
    sid = "CSE24009"
    before = call("mentor.arjun", "GET", f"/api/students/demo/{sid}").json()["insight"]
    recs = call("mentor.arjun", "GET", f"/api/students/demo/{sid}/records?category=lms&period=2026-09").json()["items"]
    r = call("mentor.arjun", "PUT", f"/api/students/demo/{sid}/records/lms/2026-09",
             {"data": {"assignments_due": 6, "assignments_submitted": 0, "logins": 0}, "version": recs[0]["version"]})
    assert r.status_code == 200
    after = call("mentor.arjun", "GET", f"/api/students/demo/{sid}").json()["insight"]
    assert after["calculated_at"] >= before["calculated_at"]
    assert after["components"]["lms"]["value"] < before["components"]["lms"]["value"]
    assert after["recalc_status"] == "current"
    # A failing recalculation leaves the student visibly stale, and repair fixes it.
    import app.insights as ins
    monkeypatch.setattr(ins, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r2 = call("mentor.arjun", "PUT", f"/api/students/demo/{sid}/records/lms/2026-08",
              {"data": {"assignments_due": 6, "assignments_submitted": 6, "logins": 30},
               "version": call("mentor.arjun", "GET", f"/api/students/demo/{sid}/records?category=lms&period=2026-08").json()["items"][0]["version"]})
    assert r2.status_code == 200
    assert call("mentor.arjun", "GET", f"/api/students/demo/{sid}").json()["insight"]["recalc_status"] == "stale"
    monkeypatch.undo()
    rep = call("admin.priya", "POST", "/api/admin/recompute", {"dataset": "demo"}).json()
    assert rep["recomputed"] >= 1 and rep["remaining"] == 0
    assert call("mentor.arjun", "GET", f"/api/students/demo/{sid}").json()["insight"]["recalc_status"] == "current"


# --------------------------------------------------------------------------- interventions and notes
def _rec(call, sid="CSE24010"):
    return call("mentor.arjun", "GET", f"/api/students/demo/{sid}").json()


def test_intervention_lifecycle(call):
    sid = "CSE24010"
    body = {"title": "Attendance recovery plan", "category": "attendance", "owner_sub": "local-mentor.arjun",
            "due_date": "2026-09-01", "review_date": "2026-10-01", "evidence": ["A6"]}
    assert call("mentor.arjun", "POST", f"/api/students/demo/{sid}/interventions", body).status_code == 422  # not reviewed
    r = call("mentor.arjun", "POST", f"/api/students/demo/{sid}/interventions", {**body, "reviewed": True})
    assert r.status_code == 201, r.text
    iv = r.json()
    assert iv["overdue"] and iv["baseline"]["period"] == "2026-09"
    bad = call("mentor.arjun", "PATCH", f"/api/students/demo/{sid}/interventions/{iv['intervention_id']}",
               {"status": "Completed", "version": iv["version"]})
    assert bad.status_code == 422  # outcome required
    stale = call("mentor.arjun", "PATCH", f"/api/students/demo/{sid}/interventions/{iv['intervention_id']}",
                 {"status": "In Progress", "version": iv["version"] + 5})
    assert stale.status_code == 409
    ok = call("mentor.arjun", "PATCH", f"/api/students/demo/{sid}/interventions/{iv['intervention_id']}",
              {"status": "Completed", "outcome": {"result": "improved", "note": "Back above 80%"}, "version": iv["version"]})
    assert ok.status_code == 200 and not ok.json()["overdue"]
    prof = _rec(call, sid)
    mine = next(i for i in prof["interventions"] if i["intervention_id"] == iv["intervention_id"])
    assert "not proof" in mine["comparison"]["note"] or "Not comparable" in mine["comparison"]["note"]
    assert call("student.cse", "GET", "/api/students/demo/CSE24001").json()["interventions"] is not None


def test_placement_officer_limited_to_placement_training(call):
    body = {"title": "Coding bootcamp", "category": "placement_training", "owner_sub": "local-placement.rohit",
            "due_date": "2026-11-01", "review_date": "2026-12-01", "reviewed": True}
    assert call("placement.rohit", "POST", "/api/students/demo/MECH23002/interventions", body).status_code == 201
    assert call("placement.rohit", "POST", "/api/students/demo/MECH23002/interventions",
                {**body, "category": "academic", "title": "Remedial maths"}).status_code == 403


def test_confidential_notes_visibility(call):
    sid = "CSE24011"
    iv = call("mentor.arjun", "POST", f"/api/students/demo/{sid}/interventions",
              {"title": "Wellbeing check-in", "category": "wellbeing", "owner_sub": "local-mentor.arjun",
               "due_date": "2026-11-01", "review_date": "2026-11-15", "reviewed": True}).json()
    path = f"/api/students/demo/{sid}/interventions/{iv['intervention_id']}/notes"
    assert call("mentor.arjun", "POST", path, {"text": "Family circumstances discussed", "visibility": "confidential"}).status_code == 201
    assert call("mentor.arjun", "POST", path, {"text": "Agreed weekly meeting", "visibility": "staff"}).status_code == 201
    assert call("placement.rohit", "POST", path, {"text": "x", "visibility": "confidential"}).status_code == 403

    def texts(u):
        return {n["text"] for n in call(u, "GET", f"/api/students/demo/{sid}").json()["notes"]}
    assert texts("mentor.arjun") == {"Family circumstances discussed", "Agreed weekly meeting"}
    assert texts("hod.meenakshi") == {"Family circumstances discussed", "Agreed weekly meeting"}
    assert texts("placement.rohit") == {"Agreed weekly meeting"}
    assert texts("activity.sara") == set()


def test_student_never_sees_staff_notes(call):
    prof = call("student.cse", "GET", "/api/students/demo/CSE24001").json()
    assert prof["notes"] == []
    for i in prof["interventions"]:
        assert set(i) <= {"intervention_id", "student_id", "title", "category", "status", "due_date", "review_date", "outcome",
                          "created_at"}


def test_audit_log_has_no_sensitive_values(call):
    items = call("admin.priya", "GET", "/api/audit?category=academic&limit=200").json()["items"]
    blob = json.dumps(items)
    assert "Worried about placements" not in blob and "Family circumstances" not in blob and "Bearer" not in blob


def test_student_submission_enters_verification_queue_and_leaves_when_verified(call):
    sub = call("student.cse", "PUT", "/api/students/demo/CSE24001/records/certification/2026-09",
               {"data": {"name": "Queue Test Cert", "issuer": "Example Board"}})
    assert sub.status_code == 201 and sub.json()["record"]["verification"] == "pending"
    assert call("mentor.arjun", "GET", "/api/verifications?dataset=demo").status_code == 403
    q = call("activity.sara", "GET", "/api/verifications?dataset=demo").json()["items"]
    mine = [i for i in q if i["student_id"] == "CSE24001" and i["name"] == "Queue Test Cert"]
    assert len(mine) == 1
    v = call("activity.sara", "POST", "/api/students/demo/CSE24001/verify",
             {"category": "certification", "record_key": mine[0]["record_key"], "decision": "verified", "version": mine[0]["version"]})
    assert v.status_code == 200, v.text
    q = call("activity.sara", "GET", "/api/verifications?dataset=demo").json()["items"]
    assert not [i for i in q if i["name"] == "Queue Test Cert"]
    # a verified record can no longer be changed by the student
    again = call("student.cse", "PUT", "/api/students/demo/CSE24001/records/certification/2026-09",
                 {"data": {"name": "Queue Test Cert", "issuer": "Other"}, "version": 2})
    assert again.status_code == 403


def test_demo_reset_restores_changes_in_bounded_resumable_steps(call):
    from app import db, seed
    from app.auth import load_principal
    # a staff edit, a staff-created demo student and an intervention; plus a real record that must survive
    rec = call("mentor.arjun", "GET", "/api/students/demo/CSE24010/records?category=lms&period=2026-09").json()["items"][0]
    assert call("mentor.arjun", "PUT", "/api/students/demo/CSE24010/records/lms/2026-09",
                {"data": {"assignments_due": 9, "assignments_submitted": 1, "logins": 3}, "version": rec["version"]}).status_code == 200
    assert call("admin.priya", "POST", "/api/students", {"student_id": "ECE26777", "name": "Temp Demo", "department": "ECE",
                                                          "year": 1, "dataset": "demo"}).status_code == 201
    assert call("admin.priya", "POST", "/api/students", {"student_id": "ECE26778", "name": "Kept Real", "department": "ECE",
                                                          "year": 1, "dataset": "real"}).status_code == 201
    admin = load_principal("local-admin.priya")
    cursor, steps, totals = 0, 0, {"removed": 0, "restored": 0}
    while True:
        r = seed.reset_demo(admin, "RESET DEMO", cursor, budget_seconds=0.05)
        steps += 1
        totals["removed"] += r["removed"]
        totals["restored"] += r["restored"]
        if r["done"]:
            break
        cursor = r["cursor"]
    assert steps > 1  # resumable
    assert totals["restored"] >= 1 and totals["removed"] >= 1
    assert totals["restored"] < 100  # proportional to changes, not a full rewrite
    after = call("mentor.arjun", "GET", "/api/students/demo/CSE24010/records?category=lms&period=2026-09").json()["items"][0]
    assert after["source"] == "seed" and after["assignments_due"] == rec["assignments_due"]
    assert db.table().get("STU#demo#ECE26777", "MASTER") is None
    assert db.table().get("STU#real#ECE26778", "MASTER") is not None


def test_csv_templates_in_docs_match_the_importer():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "app.tools.export_templates", "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    r = subprocess.run([sys.executable, "-m", "app.tools.render_role_matrix", "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
