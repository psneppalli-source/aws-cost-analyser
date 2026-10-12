"""AI summaries: permission-scoped facts, no identities sent, caching and daily limits (model call faked)."""

import json

import pytest

from app import ai


@pytest.fixture()
def fake_model(monkeypatch):
    sent = []

    def complete(facts, audience, system=None, user=None, **kw):
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


def test_ask_runs_a_checked_query_never_model_numbers(call, monkeypatch):
    from app import ai
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    asked = []

    def complete(facts, audience, system=None, user=None, **kw):
        asked.append(user)
        return '{"query":"average","metric":"attendance","group_by":"department","year":3}', "test/m:free"
    monkeypatch.setattr(ai, "complete", complete)
    r = call("admin.priya", "POST", "/api/ai/ask", {"question": "Which department has the best attendance in year 3? Is Joseph Menon ok? CSE24001"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source"] == "ai" and out["query"] == {"query": "average", "group_by": "department", "metric": "attendance", "year": 3}
    assert {row["group"] for row in out["rows"]} <= {"CSE", "ECE", "MECH"} and out["sentence"].startswith("Highest")
    assert "CSE24001" not in asked[-1]  # IDs are replaced before the question leaves the platform
    # students can't ask about everyone
    assert call("student.cse", "POST", "/api/ai/ask", {"question": "lowest attendance"}).status_code == 403


def test_ask_falls_back_to_keywords_when_ai_is_busy(call, monkeypatch):
    from app import ai

    def busy(*a, **k):
        raise ai.AIUnavailable("busy")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai, "complete", busy)
    out = call("admin.priya", "POST", "/api/ai/ask", {"question": "5 students with the lowest attendance in ECE"}).json()
    assert out["source"] == "keywords" and out["query"]["query"] == "rank" and out["query"]["department"] == "ECE"
    assert len(out["rows"]) == 5 and out["rows"][0]["value"] <= out["rows"][-1]["value"]
    which = call("admin.priya", "POST", "/api/ai/ask", {"question": "Which department has the lowest attendance?"}).json()
    assert which["query"] == {"query": "average", "group_by": "department", "metric": "attendance"}
    risk = call("admin.priya", "POST", "/api/ai/ask", {"question": "how many at placement risk by department"}).json()
    assert risk["query"]["query"] == "risk_count" and risk["query"]["risk"] == "placement" and risk["query"]["group_by"] == "department"


def test_plan_draft_and_coach(call, monkeypatch):
    from app import ai
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    systems = []

    def complete(facts, audience, system=None, user=None, **kw):
        systems.append(system)
        if system == ai.PLAN:
            return 'Sure: {"title":"Coding practice plan","steps":["Weekly coding clinic","Two practice tests"],"review_weeks":3}', "m:free"
        return "You're making progress.\n- Practise coding 3 times this week", "m:free"
    monkeypatch.setattr(ai, "complete", complete)
    d = call("mentor.arjun", "POST", "/api/ai/plan-draft", {"student_id": "CSE24001", "category": "placement_training",
                                                            "evidence": [{"label": "Coding below 55", "observed": 48, "threshold": 55}]})
    assert d.status_code == 200, d.text
    assert d.json()["title"] == "Coding practice plan" and len(d.json()["steps"]) == 2 and d.json()["review_weeks"] == 3
    assert call("student.cse", "POST", "/api/ai/plan-draft", {"student_id": "CSE24001"}).status_code == 403
    c = call("student.cse", "POST", "/api/ai/summary", {"kind": "coach"})
    assert c.status_code == 200 and systems[-1] == ai.COACH and c.json()["lines"][1].startswith("- ")
    assert call("mentor.arjun", "POST", "/api/ai/summary", {"kind": "coach"}).status_code == 403
