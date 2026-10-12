"""AI summaries: permission-scoped facts, no identities sent, caching and daily limits (model call faked)."""

import json

import pytest

from app import ai


@pytest.fixture()
def fake_model(monkeypatch):
    sent = []

    def complete(facts, audience):
        sent.append((facts, audience))
        return "Headline about the data.\n* **Point one**\n2. Point two\n- Next step", "test/free-model:free"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai, "complete", complete)
    return sent


def test_summaries_send_no_identities_and_are_cached(call, fake_model):
    r = call("mentor.arjun", "POST", "/api/ai/summary", {"kind": "student", "student_id": "CSE24001"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["lines"] == ["Headline about the data.", "- Point one", "- Point two", "- Next step"] and not out["cached"]
    facts, audience = fake_model[-1]
    blob = json.dumps(facts)
    for banned in ("CSE24001", "@", "date_of_birth", '"name"', "comment"):
        assert banned not in blob, banned
    assert "mentor" in audience
    again = call("mentor.arjun", "POST", "/api/ai/summary", {"kind": "student", "student_id": "CSE24001"}).json()
    assert again["cached"] and len(fake_model) == 1


def test_students_get_their_own_summary_only(call, fake_model):
    own = call("student.cse", "POST", "/api/ai/summary", {"kind": "student", "student_id": "CSE24001"})
    assert own.status_code == 200 and "you" in fake_model[-1][1]
    assert call("student.cse", "POST", "/api/ai/summary", {"kind": "student", "student_id": "CSE24002"}).status_code in (403, 404)
    assert call("student.cse", "POST", "/api/ai/summary", {"kind": "overview"}).status_code == 403


def test_staff_summaries_for_each_page(call, fake_model):
    for kind in ("overview", "insights", "academic", "placement"):
        r = call("admin.priya", "POST", "/api/ai/summary", {"kind": kind})
        assert r.status_code == 200, (kind, r.text)
        assert "name" not in json.dumps(fake_model[-1][0]).lower().replace("department", "")


def test_daily_limit(call, fake_model, monkeypatch):
    monkeypatch.setattr(ai, "DAILY_LIMIT", 0)
    r = call("hod.meenakshi", "POST", "/api/ai/summary", {"kind": "overview", "department": "CSE", "year": 2})
    assert r.status_code == 503 and "limit" in r.json()["error"]["message"]


def test_not_configured(call, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AI_KEY_PARAM", raising=False)
    assert call("admin.priya", "GET", "/api/me").json()["ai"] is False
    assert call("admin.priya", "POST", "/api/ai/summary", {"kind": "overview"}).status_code == 503
