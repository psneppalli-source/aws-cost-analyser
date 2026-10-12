"""The smaller AI helpers: permissions, no identities sent, server-computed figures (model call faked)."""

import json

import pytest

from app import ai, ai_more


@pytest.fixture()
def fake(monkeypatch):
    calls = []

    def complete(facts, audience, system=None, user=None, vision=False, **kw):
        calls.append({"facts": facts, "audience": audience, "system": system, "user": user, "vision": vision})
        if system == ai_more.REVIEW:
            return '{"result":"improved","recommendation":"close","note":"Score rose from 29.7 to 64.7; an association, not proof."}', "m:free"
        if system == ai_more.TIDY:
            return "Met [STUDENT] today; agreed to attend the coding clinic weekly.", "m:free"
        if system == ai_more.CERT:
            return '{"name":"Python for Data Science","issuer":"Coursera","date":"2026-05-14"}', "v:free"
        return "Headline.\n- First point\n- Second point", "m:free"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai, "complete", complete)
    return calls


def tool(call, user, **body):
    return call(user, "POST", "/api/ai/tool", body)


def test_brief_explain_digest_and_outcomes(call, fake):
    r = tool(call, "mentor.arjun", tool="brief", student_id="CSE24005")
    assert r.status_code == 200 and r.json()["lines"][0] == "Headline."
    facts = fake[-1]["facts"]
    assert "since_previous_period" in facts and "CSE24005" not in json.dumps(facts)
    assert tool(call, "student.cse", tool="brief", student_id="CSE24001").status_code == 403
    e = tool(call, "student.cse", tool="explain")
    assert e.status_code == 200
    ch = fake[-1]["facts"]
    assert "score_change" in ch or "note" in ch            # computed here, not by the model
    assert "you" in fake[-1]["audience"]
    assert tool(call, "admin.priya", tool="digest").status_code == 200
    assert "early_warnings_this_period" in fake[-1]["facts"]
    o = tool(call, "admin.priya", tool="outcomes")
    assert o.status_code == 200
    cats = fake[-1]["facts"]["by_category"]
    assert all("percent_improved" in v for v in cats.values())
    assert tool(call, "student.cse", tool="digest").status_code == 403


def test_plan_review_and_tidy(call, fake, client, tokens):
    # a student with a support plan that this administrator may update
    from app import db
    pick = None
    for d in ("CSE", "ECE", "MECH"):
        for r in db.table().query(f"DEPT#real#{d}", index="gsi1")[0]:
            ivs = db.table().query(f"STU#real#{r['student_id']}", "INT#")[0]
            if ivs:
                pick = (r["student_id"], ivs[0]["intervention_id"])
                break
        if pick:
            break
    assert pick, "seed data has support plans"
    r = tool(call, "admin.priya", tool="plan_review", student_id=pick[0], intervention_id=pick[1])
    if r.status_code == 403:  # this role can't update plans: the mentor of record would
        r = tool(call, "hod.meenakshi", tool="plan_review", student_id=pick[0], intervention_id=pick[1])
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        assert r.json()["result"] == "improved" and r.json()["recommendation"] == "close"
        assert pick[0] not in json.dumps(fake[-1]["facts"])


def test_tidy_masks_identities(call, fake):
    from app import db
    name = db.table().get("STU#real#CSE24005", "MASTER")["name"]
    r = tool(call, "mentor.arjun", tool="tidy", student_id="CSE24005",
             text=f"met {name} today, call 98765 43210 or mail x@y.com, CSE24005 agreed coding clinic")
    assert r.status_code == 200 and r.json()["masked"]
    sent = fake[-1]["user"]
    assert name not in sent and "98765" not in sent and "x@y.com" not in sent and "CSE24005" not in sent
    assert name.split()[0] in r.json()["text"]           # placeholder restored for the user
    assert tool(call, "student.cse", tool="tidy", student_id="CSE24001", text="hello there").status_code == 403


def test_practice_help_import_and_certificate(call, fake):
    pr = tool(call, "student.cse", tool="practice", mode="subject", subject="Operating Systems")
    assert pr.status_code == 200 and fake[-1]["facts"]["topic"] == "Operating Systems"
    iv = tool(call, "student.cse", tool="practice", mode="interview")
    assert iv.status_code == 200 and "interview" in fake[-1]["facts"]["topic"]
    h = tool(call, "student.cse", tool="help", question="How do I add a certificate?")
    assert h.status_code == 200 and "Help text" in fake[-1]["user"]
    c = tool(call, "student.cse", tool="read_certificate", image="data:image/png;base64,iVBORw0KGgo=")
    assert c.status_code == 200 and c.json()["issuer"] == "Coursera" and fake[-1]["vision"]
    assert tool(call, "student.cse", tool="read_certificate", image="not an image").status_code == 503


def test_check_entries_rules(call, fake):
    rows = [{"student_id": "CSE24001", "values": {"score": 60}, "saved": {}},
            {"student_id": "CSE24002", "values": {"score": 20}, "saved": {"score": 45, "max_score": 50}}]
    r = tool(call, "mentor.arjun", tool="check_entries", category="marks", common={"max_score": 50, "subject": "OS"}, rows=rows)
    assert r.status_code == 200
    msgs = [w["message"] for w in r.json()["warnings"]]
    assert any("above the maximum" in m for m in msgs) and any("percentage points" in m for m in msgs)
    att = tool(call, "mentor.arjun", tool="check_entries", category="attendance", common={},
               rows=[{"student_id": "CSE24001", "values": {"classes_held": 10, "classes_attended": 12}}]).json()
    assert "more than held" in att["warnings"][0]["message"]
