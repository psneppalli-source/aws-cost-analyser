"""Every role's allowed and denied operations, through the HTTP API."""

import pytest

from app import db
from conftest import first

CSE3 = "CSE24001"      # in mentor.arjun's mentee class (CSE year 3) and taught subjects
CSE3_LAST = "CSE24012"  # CSE year 3, the 12th: also a mentee
CSE3_OTHER = None
ECE2 = "ECE25001"      # mentor.kavitha's class
MECH4 = "MECH23001"


def marks(subject="Operating Systems", score=30):
    return {"data": {"subject": subject, "assessment": "Quiz A", "score": score, "max_score": 50}}


# --------------------------------------------------------------------------- reads
@pytest.mark.parametrize("user,sid,expected", [
    ("admin.priya", MECH4, 200), ("hod.meenakshi", CSE3, 200), ("hod.meenakshi", ECE2, 403),
    ("mentor.arjun", CSE3, 200), ("mentor.arjun", ECE2, 403), ("mentor.arjun", MECH4, 403),
    ("placement.rohit", MECH4, 200), ("activity.sara", ECE2, 200), ("student.cse", CSE3, 200),
    ("student.cse", CSE3_LAST, 403), ("student.ece", CSE3, 403), ("sysadmin.dev", CSE3, 403),
])
def test_profile_access(call, user, sid, expected):
    assert call(user, "GET", f"/api/students/demo/{sid}").status_code == expected


def test_listing_scopes(call):
    def total(u):
        return call(u, "GET", "/api/students?dataset=demo&limit=200").json()["total"]
    assert total("admin.priya") == 150
    assert total("hod.meenakshi") == 50
    assert total("mentor.arjun") == 12
    assert total("student.cse") == 1
    assert total("sysadmin.dev") == 0


def test_placement_officer_sees_only_needed_fields(call):
    p = call("placement.rohit", "GET", f"/api/students/demo/{MECH4}").json()
    ins = p["insight"]
    assert set(ins["components"]) <= {"placement", "skills"}
    assert set(ins["risks"]) == {"placement"}
    assert "summary" not in ins and "support_needs" not in ins and "email" not in p["student"]
    rows = call("placement.rohit", "GET", "/api/students?dataset=demo&limit=5").json()["items"]
    assert all("academic" not in (r.get("risks") or {}) for r in rows)


def test_activity_coordinator_limited_fields(call):
    ins = call("activity.sara", "GET", f"/api/students/demo/{MECH4}").json()["insight"]
    assert set(ins.get("components", {})) <= {"engagement"} and "risks" not in ins


def test_system_admin_has_no_student_access(call):
    assert call("sysadmin.dev", "GET", "/api/dashboard?dataset=demo").status_code == 403
    assert call("sysadmin.dev", "GET", f"/api/students/demo/{CSE3}/records").status_code == 403
    assert call("sysadmin.dev", "GET", "/api/users").status_code == 200


# --------------------------------------------------------------------------- writes
def test_mentor_marks_only_for_assigned_subject_and_class(call):
    assert call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/marks/2026-09", marks()).status_code == 201
    r = call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/marks/2026-09", marks("Computer Networks"))
    assert r.status_code == 403  # taught to the class, but not by this mentor
    assert call("mentor.arjun", "PUT", f"/api/students/demo/{ECE2}/records/marks/2026-09",
                marks("Signals and Systems")).status_code == 403
    existing = [x for x in call("mentor.arjun", "GET", f"/api/students/demo/{CSE3}/records?category=attendance&period=2026-08").json()["items"]
                if x["subject"] == "Database Systems"][0]
    att = {"data": {"subject": "Database Systems", "classes_held": 10, "classes_attended": 9}}
    no_version = call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/attendance/2026-08", att)
    assert no_version.status_code == 422  # changing an existing record must name the version it started from
    r = call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/attendance/2026-08", {**att, "version": existing["version"]})
    assert r.status_code == 202  # verified attendance changes go to the HOD as a correction


def test_mentor_lms_only_for_mentees(call):
    lms = {"data": {"assignments_due": 4, "assignments_submitted": 3, "logins": 15}}
    non_mentee_same_class = "CSE24013" if db.table().get("STU#demo#CSE24013", "MASTER") else first("CSE", 4)
    assert call("mentor.arjun", "PUT", f"/api/students/demo/{non_mentee_same_class}/records/lms/2025-12", lms).status_code == 403
    r = call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/lms/2025-12", lms)
    assert r.status_code == 201, r.text


def test_placement_officer_writes(call):
    pa = {"data": {"assessment_type": "coding", "score": 61}}
    assert call("placement.rohit", "PUT", f"/api/students/demo/{MECH4}/records/placement_assessment/2026-09", pa).status_code in (200, 201)
    assert call("placement.rohit", "PUT", f"/api/students/demo/{MECH4}/records/marks/2026-09",
                marks("CAD/CAM")).status_code == 403
    sk = {"data": {"technical": 70, "communication": 66}}
    assert call("placement.rohit", "PUT", f"/api/students/demo/{MECH4}/records/skills/2026-03", sk).status_code == 201


def test_activity_coordinator_cannot_touch_academic_or_placement(call):
    ev = {"data": {"activity_type": "event", "name": "Robotics Expo", "role": "Volunteer"}}
    assert call("activity.sara", "PUT", f"/api/students/demo/{ECE2}/records/engagement/2026-09", ev).status_code == 201
    assert call("activity.sara", "PUT", f"/api/students/demo/{ECE2}/records/placement_assessment/2026-09",
                {"data": {"assessment_type": "aptitude", "score": 80}}).status_code == 403
    assert call("activity.sara", "PUT", f"/api/students/demo/{ECE2}/records/academic_result/2026-09",
                {"data": {"semester": 3, "cgpa": 9.9, "backlogs": 0}}).status_code == 403


def test_student_cannot_edit_verified_results_or_scores(call):
    for cat, data in [("marks", marks()["data"]), ("attendance", {"subject": "Operating Systems", "classes_held": 10, "classes_attended": 10}),
                      ("placement_assessment", {"assessment_type": "coding", "score": 99}),
                      ("academic_result", {"semester": 5, "cgpa": 10, "backlogs": 0})]:
        assert call("student.cse", "PUT", f"/api/students/demo/{CSE3}/records/{cat}/2026-09", {"data": data}).status_code == 403
    assert call("student.cse", "PATCH", f"/api/students/demo/{CSE3}", {"data": {"name": "X"}, "version": 1}).status_code == 403
    assert call("student.cse", "POST", "/api/admin/recompute", {"dataset": "demo"}).status_code == 403


def test_student_submits_feedback_and_certification_but_cannot_edit_verified(call):
    fb = {"data": {"satisfaction": 2, "stress": 5, "support_needed": ["career"], "comment": "Worried about placements"}}
    assert call("student.cse", "PUT", f"/api/students/demo/{CSE3}/records/feedback/2026-03", fb).status_code == 201
    cert = {"data": {"name": "Cloud Basics Test", "issuer": "Example Academy"}}
    r = call("student.cse", "PUT", f"/api/students/demo/{CSE3}/records/certification/2026-09", cert)
    assert r.status_code == 201 and r.json()["record"]["verification"] == "pending"
    rec = r.json()["record"]
    v = call("activity.sara", "POST", f"/api/students/demo/{CSE3}/verify",
             {"category": "certification", "record_key": f"REC#certification#2026-09#{rec['subkey']}", "decision": "verified",
              "version": rec["version"]})
    assert v.status_code == 200, v.text
    again = call("student.cse", "PUT", f"/api/students/demo/{CSE3}/records/certification/2026-09",
                 {"data": {**cert["data"], "issuer": "Changed"}, "version": v.json()["version"]})
    assert again.status_code == 403
    assert call("student.cse", "PUT", f"/api/students/demo/{CSE3_LAST}/records/feedback/2026-03", fb).status_code == 403


def test_hod_assigns_mentors_only_in_department(call):
    mentor = "local-mentor.arjun"
    cse = call("hod.meenakshi", "GET", f"/api/students/demo/{first('CSE', 1)}").json()["student"]
    r = call("hod.meenakshi", "PUT", f"/api/students/demo/{first('CSE', 1)}/mentor", {"mentor_sub": mentor, "version": cse["version"]})
    assert r.status_code == 200, r.text
    ece = db.table().get(f"STU#demo#{first('ECE', 1)}", "MASTER")
    assert call("hod.meenakshi", "PUT", f"/api/students/demo/{first('ECE', 1)}/mentor",
                {"mentor_sub": mentor, "version": ece["version"]}).status_code == 403


def test_corrections_need_hod_approval_within_department(call):
    rec = [x for x in call("mentor.arjun", "GET", f"/api/students/demo/{CSE3}/records?category=marks&period=2026-08").json()["items"]
           if x["subject"] == "Operating Systems"][0]
    r = call("mentor.arjun", "PUT", f"/api/students/demo/{CSE3}/records/marks/2026-08",
             {"data": {"subject": "Operating Systems", "assessment": rec["assessment"], "score": 49, "max_score": 50},
              "version": rec["version"]})
    assert r.status_code == 202 and r.json()["status"] == "pending_correction"
    cid = r.json()["correction"]["correction_id"]
    assert call("mentor.arjun", "POST", f"/api/students/demo/{CSE3}/corrections/{cid}", {"approve": True}).status_code == 403
    ok = call("hod.meenakshi", "POST", f"/api/students/demo/{CSE3}/corrections/{cid}", {"approve": True, "reason": "Re-marked paper"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    after = [x for x in call("mentor.arjun", "GET", f"/api/students/demo/{CSE3}/records?category=marks&period=2026-08").json()["items"]
             if x["subject"] == "Operating Systems"][0]
    assert after["score"] == 49 and after["version"] == rec["version"] + 1


def test_system_admin_cannot_change_own_roles_or_mix_duties(call):
    me = call("sysadmin.dev", "GET", "/api/users").json()["items"]
    own = next(u for u in me if u["username"] == "sysadmin.dev")
    r = call("sysadmin.dev", "PUT", f"/api/users/{own['sub']}/roles",
             {"assignments": [{"role": "system_admin"}, {"role": "college_admin"}], "version": own["version"]})
    assert r.status_code == 403
    new = call("sysadmin.dev", "POST", "/api/users", {"username": "temp.user", "display_name": "Temp"}).json()
    bad = call("sysadmin.dev", "PUT", f"/api/users/{new['sub']}/roles",
               {"assignments": [{"role": "system_admin"}, {"role": "mentor"}], "version": new["version"]})
    assert bad.status_code == 422
    good = call("sysadmin.dev", "PUT", f"/api/users/{new['sub']}/roles", {"assignments": [{"role": "mentor"}], "version": new["version"]})
    assert good.status_code == 200 and good.json()["roles"] == ["mentor"]
    assert call("admin.priya", "POST", "/api/users", {"username": "sneaky"}).status_code == 403


def test_scoring_config_workflow_is_admin_only_and_audited(call):
    cfg = call("admin.priya", "GET", "/api/config/scoring").json()["active"]
    cfg2 = {**cfg, "version": "1.0.1-test", "description": "Test change"}
    assert call("hod.meenakshi", "POST", "/api/config/scoring/propose", {"config": cfg2, "reason": "testing"}).status_code == 403
    bad = {**cfg2, "components": {**cfg["components"], "academic": {"label": "Academic", "weight": 0.9}}}
    assert call("admin.priya", "POST", "/api/config/scoring/propose", {"config": bad, "reason": "bad weights"}).status_code == 422
    assert call("admin.priya", "POST", "/api/config/scoring/propose", {"config": cfg2, "reason": "same rules, new version"}).status_code == 200
    a = call("admin.priya", "POST", "/api/config/scoring/activate", {"version": "1.0.1-test", "reason": "approved for test"})
    assert a.status_code == 200
    rep = call("admin.priya", "POST", "/api/admin/recompute", {"dataset": "demo"})
    while rep.json()["remaining"]:
        rep = call("admin.priya", "POST", "/api/admin/recompute", {"dataset": "demo"})
    acts = {e["action"] for e in call("admin.priya", "GET", "/api/audit?category=academic&limit=200").json()["items"]}
    assert {"scoring.proposed", "scoring.activated"} <= acts
    back = {**cfg, "version": "1.0.2-test"}
    call("admin.priya", "POST", "/api/config/scoring/propose", {"config": back, "reason": "restore defaults"})
    call("admin.priya", "POST", "/api/config/scoring/activate", {"version": "1.0.2-test", "reason": "restore defaults"})
    while call("admin.priya", "POST", "/api/admin/recompute", {"dataset": "demo"}).json()["remaining"]:
        pass


def test_role_matrix_viewer_and_doc_in_sync(call):
    assert call("student.cse", "GET", "/api/role-matrix").status_code == 200
    from app.tools.render_role_matrix import OUT, render
    assert OUT.read_text() == render(), "run python -m app.tools.render_role_matrix"
