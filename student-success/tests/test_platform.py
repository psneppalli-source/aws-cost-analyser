"""Platform tests. Run from student-success/:  python -m unittest discover -s tests -v

Seeds an isolated local deployment (synthetic data) once, then checks
authentication, server-side authorisation, imports, scoring, risk,
interventions and auditing.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ssp-test-")
os.environ["SSP_LOCAL_DIR"] = TMP
os.environ["SSP_MODE"] = "local"

from ssp import access, auth, config, engine, importer, interventions, records, seed, settings  # noqa: E402
from ssp.api import Request, handle  # noqa: E402
from ssp.auth import Principal  # noqa: E402
from ssp.lambda_handler import handler  # noqa: E402

ADMIN = Principal("admin", "Admin", "admin")
DEMO = settings.SAMPLE_DIR / "demo"


def setUpModule():
    import sys
    argv = sys.argv
    sys.argv = ["seed"]
    try:
        seed.main()
    finally:
        sys.argv = argv


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def call(method, path, user=None, body=None, query=None, raw=None):
    headers = {}
    if user:
        tok, _ = auth.local_login(user, seed.LOCAL_PASSWORD)
        headers["authorization"] = "Bearer " + tok
    b = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    status, _, out = handle(Request(method, path, query or {}, headers, b, "127.0.0.1"))
    try:
        return status, json.loads(out)
    except ValueError:
        return status, out


def cur():
    return engine.snapshot(config.active()["current_period"])["students"]


class TestAuth(unittest.TestCase):
    def test_rs256_verification_against_openssl(self):
        if not shutil.which("openssl"):
            self.skipTest("openssl not available")
        with tempfile.TemporaryDirectory() as d:
            key, msgf, sigf = Path(d, "k.pem"), Path(d, "m"), Path(d, "s")
            subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
            msgf.write_bytes(b"header.payload")
            subprocess.run(["openssl", "dgst", "-sha256", "-sign", key, "-out", sigf, msgf], check=True)
            mod = subprocess.run(["openssl", "rsa", "-in", key, "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout
            n = int(mod.split("=")[1], 16)
            sig = sigf.read_bytes()
            self.assertTrue(auth.rsa_sha256_verify(n, 65537, b"header.payload", sig))
            self.assertFalse(auth.rsa_sha256_verify(n, 65537, b"header.payloaX", sig))
            self.assertFalse(auth.rsa_sha256_verify(n, 65537, b"header.payload", sig[:-1] + bytes([sig[-1] ^ 1])))

    def test_login_wrong_password_and_lockout(self):
        auth.directory.create("locktest", "Lock Test", "mentor", password="Right@12345")
        for _ in range(settings.MAX_FAILED_LOGINS):
            with self.assertRaises(auth.AuthError):
                auth.local_login("locktest", "wrong")
        with self.assertRaisesRegex(auth.AuthError, "Too many"):
            auth.local_login("locktest", "Right@12345")

    def test_tampered_token_rejected(self):
        tok, _ = auth.local_login("mentor.cse1", seed.LOCAL_PASSWORD)
        h, p, s = tok.split(".")
        claims = json.loads(base64.urlsafe_b64decode(p + "=="))
        claims["cognito:groups"] = ["admin"]
        forged = h + "." + base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode() + "." + s
        status, _ = handle(Request("GET", "/api/users", headers={"authorization": "Bearer " + forged}))[:2]
        self.assertEqual(status, 401)

    def test_disabled_user_cannot_use_token(self):
        auth.directory.create("tmpuser", "Temp", "mentor", password="Temp@12345")
        tok, _ = auth.local_login("tmpuser", "Temp@12345")
        auth.directory.set_active("tmpuser", False)
        self.assertEqual(handle(Request("GET", "/api/me", headers={"authorization": "Bearer " + tok}))[0], 401)

    def test_no_token(self):
        self.assertEqual(call("GET", "/api/me")[0], 401)


class TestAccess(unittest.TestCase):
    def test_scopes_per_role(self):
        roster = records.roster()
        c = cur()
        self.assertEqual(len(access.visible_ids(ADMIN, roster, c)), len(roster))
        hod = access.visible_ids(Principal("hod.cse", "", "hod", dept="CSE"), roster, c)
        self.assertTrue(hod and all(roster[s]["department"] == "CSE" for s in hod))
        m = access.visible_ids(Principal("mentor.cse1", "", "mentor"), roster, c)
        self.assertTrue(m and all(roster[s]["mentor_username"] == "mentor.cse1" for s in m))
        pl = access.visible_ids(Principal("placement", "", "placement"), roster, c)
        self.assertTrue(pl and all(c[s]["placement_year"] for s in pl))
        self.assertEqual(access.visible_ids(Principal("x", "", "student", student_id="23CSE001"), roster, c), {"23CSE001"})

    def test_cross_scope_requests_forbidden(self):
        other = next(s for s, r in records.roster().items() if r["mentor_username"] != "mentor.cse1")
        self.assertEqual(call("GET", f"/api/students/{other}", "mentor.cse1")[0], 403)
        self.assertEqual(call("GET", "/api/uploads", "mentor.cse1")[0], 403)
        self.assertEqual(call("GET", "/api/audit", "hod.cse")[0], 403)
        self.assertEqual(call("GET", "/api/dashboard", "23civil006")[0], 403)
        self.assertEqual(call("POST", "/api/config", "placement", body={})[0], 403)

    def test_placement_officer_cannot_see_wellbeing_details(self):
        sid = next(s for s, v in cur().items() if v["placement_year"] and v["detail"].get("faculty_remark"))
        status, p = call("GET", f"/api/students/{sid}", "placement")
        self.assertEqual(status, 200)
        self.assertNotIn("faculty_remark", p["snapshot"]["detail"])
        self.assertIsNone(p["snapshot"]["features"]["stress"])
        _, a = call("GET", f"/api/students/{sid}", "admin")
        self.assertIn("faculty_remark", a["snapshot"]["detail"])

    def test_hod_can_note_but_not_change(self):
        it = next(i for i in interventions.all_items() if i["dept"] == "CSE")
        self.assertEqual(call("PATCH", f"/api/interventions/{it['id']}", "hod.cse", body={"status": "Completed"})[0], 400)
        s, r = call("PATCH", f"/api/interventions/{it['id']}", "hod.cse", body={"note": "Reviewed at HOD meeting"})
        self.assertEqual(s, 200)
        self.assertEqual(r["notes"][-1]["by"], "hod.cse")


class TestImport(unittest.TestCase):
    def test_error_file_is_classified(self):
        s = importer.validate("attendance", "bad.csv", (DEMO / "attendance_with_errors.csv").read_bytes(), "2026-ODD", ADMIN)
        self.assertEqual(s["status"], "validated")
        self.assertEqual(s["unmatched_ids"], ["24CSE999"])
        self.assertEqual(s["duplicates"], 1)
        self.assertEqual(s["conflicts"], 2)
        problems = " ".join(e for r in s["errors"] for e in r["errors"])
        for needle in ("not in the student roster", "more than classes_held", "is not a month", "classes_held is required", "not a valid roll number"):
            self.assertIn(needle, problems)
        self.assertEqual(s["new"] + s["changed"], 0)  # the valid rows match what is already loaded

    def test_reupload_is_idempotent_and_excel_works(self):
        before = records.meta()["categories"]["skills"]["rows"]
        s = importer.validate("skills", "skills.xlsx", (DEMO / "skills_2026-ODD.xlsx").read_bytes(), "2026-ODD", ADMIN)
        self.assertEqual((s["new"], s["changed"]), (0, 0))
        c = importer.commit(s["id"], ADMIN, recalc=False)
        self.assertEqual(c["applied"]["unchanged"], s["accepted"])
        self.assertEqual(records.meta()["categories"]["skills"]["rows"], before)

    def test_missing_required_column_rejects_file(self):
        s = importer.validate("lms", "x.csv", b"student_id,logins\n23CSE001,4\n", "2026-ODD", ADMIN)
        self.assertEqual(s["status"], "rejected")
        self.assertIn("week_start", s["file_errors"][0])

    def test_failed_commit_leaves_records_untouched(self):
        s = importer.validate("lms", "upd.csv", (DEMO / "lms_2026-ODD_weeks11-12.csv").read_bytes(), "2026-ODD", ADMIN)
        before = dict(records.load("lms"))
        orig = records.save
        records.save = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
        try:
            with self.assertRaises(RuntimeError):
                importer.commit(s["id"], ADMIN, recalc=False)
        finally:
            records.save = orig
        self.assertEqual(len(records.load("lms")), len(before))
        self.assertEqual(importer.get_upload(s["id"])["status"], "validated")  # can retry

    def test_commit_triggers_recalculation(self):
        run_before = engine.scoring_meta()["run_id"]
        s = importer.validate("lms", "upd.csv", (DEMO / "lms_2026-ODD_weeks11-12.csv").read_bytes(), "2026-ODD", ADMIN)
        c = importer.commit(s["id"], ADMIN)
        self.assertTrue(c["recalculated"])
        self.assertNotEqual(engine.scoring_meta()["run_id"], run_before)
        self.assertEqual(importer.commit.__name__, "commit")
        with self.assertRaises(importer.ImportError_):
            importer.commit(s["id"], ADMIN)  # cannot import the same upload twice


class TestScoring(unittest.TestCase):
    def test_points_add_up_and_missing_excluded(self):
        for s in list(cur().values())[:200]:
            sc = s["score"]
            if sc["score"] is None:
                continue
            used = [i for i in sc["indicators"] if i["status"] == "used"]
            self.assertAlmostEqual(sum(i["points"] for i in used), sc["score"], delta=0.1)
            self.assertAlmostEqual(sum(i["weight_share"] for i in used), 1, delta=0.01)
            for i in sc["indicators"]:
                if i["status"] != "used":
                    self.assertNotIn("points", i)

    def test_missing_data_makes_score_provisional_not_zero(self):
        cfg = config.active()
        f = {k: None for k in cfg["features"]}
        f.update(cgpa=8.0, backlogs=0, attendance_pct=90, placement_year=False)
        sc = engine.success_score(f, cfg)
        self.assertEqual(sc["status"], "insufficient")
        f.update(internal_pct=70, attendance_min_subject_pct=85, attendance_trend=0, lms_completion_pct=90,
                 lms_logins_per_week=5, lms_quiz_avg=70, lms_login_trend=1.0, technical=70, communication=70,
                 problem_solving=70, events=2, clubs=1, projects_hackathons=1, certifications=1)
        sc = engine.success_score(f, cfg)
        self.assertIn(sc["status"], ("ok", "provisional"))
        self.assertGreater(sc["score"], 60)
        self.assertTrue(all(i["status"] == "not_applicable" for i in sc["indicators"] if i["pillar"] == "placement"))

    def test_insufficient_data_is_not_low_risk(self):
        cfg = config.active()
        f = {k: None for k in cfg["features"]}
        f.update(placement_year=True, cgpa=8.5, backlogs=0)
        r = engine.assess_risk("placement", f, {}, cfg)
        self.assertEqual(r["level"], engine.INSUFFICIENT)
        self.assertIn("register_placement_test", r["actions"])
        f.update(aptitude_score=80, coding_score=75, mock_interview_rating=4, communication=70, portfolio_items=2)
        self.assertEqual(engine.assess_risk("placement", f, {}, cfg)["level"], "Low")

    def test_risk_evidence_and_levels(self):
        cfg = config.active()
        f = {k: None for k in cfg["features"]}
        f.update(cgpa=5.5, backlogs=4, attendance_pct=62, placement_year=False)
        r = engine.assess_risk("academic", f, {"academic": {"file": "x.csv"}}, cfg)
        self.assertEqual(r["level"], "High")
        rules = {e["rule"] for e in r["evidence"]}
        self.assertTrue({"A-CGPA-LOW", "A-BACKLOG-MANY", "A-ATT-SHORT", "A-ATT-CRIT"} <= rules)
        self.assertEqual(r["points"], sum(e["points"] for e in r["evidence"]))
        self.assertEqual(engine.assess_risk("placement", f, {}, cfg)["level"], engine.NOT_APPLICABLE)

    def test_config_validation(self):
        cfg = json.loads(settings.DEFAULT_CONFIG.read_text())
        cfg["pillars"]["academic"]["weight"] = 0.5
        self.assertTrue(any("pillar weights" in e for e in config.validate(cfg)))
        cfg = json.loads(settings.DEFAULT_CONFIG.read_text())
        cfg["risk"]["academic"]["rules"][0]["op"] = "~"
        self.assertTrue(any("unknown operator" in e for e in config.validate(cfg)))

    def test_new_version_rescoring_keeps_old_snapshots(self):
        cfg = json.loads(json.dumps(config.active()))
        old = cfg["version"]
        cfg["version"] = old + "-t"
        cfg["risk"]["academic"]["rules"][4]["value"] = 80  # stricter attendance rule
        s, r = call("POST", "/api/config", "admin", body={"config": cfg, "note": "test"})
        self.assertEqual(s, 200)
        self.assertIsNotNone(engine.snapshot(cfg["current_period"], old)["students"])
        self.assertEqual(engine.scoring_meta()["version"], old + "-t")
        dup = dict(cfg)
        dup["description"] = "changed but same version"
        self.assertEqual(call("POST", "/api/config", "admin", body={"config": dup, "note": "x"})[0], 400)
        orig = json.loads(json.dumps(config.active()))
        orig["version"] = old + "-t2"
        orig["risk"]["academic"]["rules"][4]["value"] = 75
        self.assertEqual(call("POST", "/api/config", "admin", body={"config": orig, "note": "restore"})[0], 200)

    def test_segment_reasons(self):
        for s in cur().values():
            self.assertTrue(s["segment"]["reasons"])

    def test_year_appropriate_indicators(self):
        c = cur()
        mca2 = next(v for k, v in c.items() if "MCA" in k and v["year"] == 2)
        btech2 = next(v for k, v in c.items() if "MCA" not in k and v["year"] == 2)
        self.assertTrue(mca2["placement_year"])
        self.assertFalse(btech2["placement_year"])


class TestInterventions(unittest.TestCase):
    def test_lifecycle(self):
        sid = next(s for s, r in records.roster().items() if r["mentor_username"] == "mentor.cse1" and s in cur())
        s, it = call("POST", "/api/interventions", "mentor.cse1", body={"student_id": sid, "title": "Weekly check-in",
                                                                      "due_date": (date.today() - timedelta(days=1)).isoformat(),
                                                                      "review_date": date.today().isoformat()})
        self.assertEqual(s, 201)
        self.assertTrue(it["overdue"])
        self.assertEqual(it["owner"], "mentor.cse1")
        self.assertEqual(call("PATCH", f"/api/interventions/{it['id']}", "mentor.cse1", body={"status": "Completed"})[0], 400)
        s, done = call("PATCH", f"/api/interventions/{it['id']}", "mentor.cse1",
                       body={"status": "Completed", "outcome": "Improved", "note": "Attendance back above 80%"})
        self.assertEqual(s, 200)
        self.assertFalse(done["overdue"])
        self.assertEqual(len(done["notes"]), 1)
        self.assertEqual(call("POST", "/api/interventions", "23civil006", body={"student_id": "23CIVIL006", "title": "x"})[0], 403)

    def test_placement_officer_limited_to_placement_actions(self):
        sid = next(s for s, v in cur().items() if v["placement_year"])
        body = {"student_id": sid, "title": "Remedial maths", "owner_role": "mentor"}
        self.assertEqual(call("POST", "/api/interventions", "placement", body=body)[0], 403)
        body.update(owner_role="placement", title="Mock interviews")
        self.assertEqual(call("POST", "/api/interventions", "placement", body=body)[0], 201)


class TestAuditAndApi(unittest.TestCase):
    def test_audit_records_key_events(self):
        call("GET", "/api/students/23CSE001", "admin")
        _, rows = call("GET", "/api/audit", "admin")
        actions = {r["action"] for r in rows}
        for a in ("upload.committed", "scoring.recalculated", "intervention.created", "student.viewed"):
            self.assertIn(a, actions)

    def test_dashboard_and_filters(self):
        s, d = call("GET", "/api/dashboard", "admin", query={"dept": "CSE", "risk": "academic:High"})
        self.assertEqual(s, 200)
        self.assertTrue(all(r["dept"] == "CSE" for r in d["risk_by_dept"]["academic"]))
        self.assertEqual(d["kpis"]["academic"].get("High", 0), d["kpis"]["students"])
        s, st = call("GET", "/api/students", "admin", query={"q": "23cse00"})
        self.assertTrue(st["total"] > 0 and all(r["student_id"].startswith("23CSE00") for r in st["rows"]))

    def test_lambda_handler_shape(self):
        tok, _ = auth.local_login("admin", seed.LOCAL_PASSWORD)
        ev = {"rawPath": "/api/me", "requestContext": {"http": {"method": "GET", "sourceIp": "1.2.3.4"}},
              "headers": {"Authorization": "Bearer " + tok}, "isBase64Encoded": False}
        r = handler(ev, None)
        self.assertEqual(r["statusCode"], 200)
        self.assertIn("Strict-Transport-Security", r["headers"])
        self.assertEqual(json.loads(r["body"])["user"]["role"], "admin")
        body = base64.b64encode(b"student_id\n").decode()
        r = handler({"rawPath": "/api/uploads", "queryStringParameters": {"category": "lms", "period": "2026-ODD"},
                     "requestContext": {"http": {"method": "POST"}}, "headers": {"authorization": "Bearer " + tok},
                     "body": body, "isBase64Encoded": True}, None)
        self.assertEqual(json.loads(r["body"])["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
