"""AI summaries through OpenRouter, built only from figures the signed-in user may already see.

Privacy: the model receives numbers and category labels only. Names, student IDs, emails, dates of birth and
free-text comments are never sent; the page shows those itself. Summaries describe recorded data and suggest
next steps; they are not predictions and never change a score.

Cost: by default only free OpenRouter models are used (chosen from OpenRouter's live model list). Identical
requests are answered from a 24-hour cache, and each user may generate a limited number of new summaries a day.
The API key lives in SSM Parameter Store (SecureString) and is read by the API function only; locally it can
come from OPENROUTER_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from statistics import mean

from . import audit, db, insights, views
from .policy import Denied, Principal, grants
from .settings import settings

log = logging.getLogger("ssp.ai")

API = "https://openrouter.ai/api/v1"
DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "40"))
CACHE_SECONDS = 24 * 3600
# completely free models only (ids ending ":free"); Meta Llama and NVIDIA Nemotron first, as the college asked
PREFERRED = ("meta-llama/llama-3.3-70b", "meta-llama/llama-4", "meta-llama/", "nvidia/", "mistralai/", "qwen/", "google/gemma",
             "deepseek/")
_key: dict = {"value": None, "at": 0.0}
_models: dict = {"ids": None, "at": 0.0, "good": None}

SYSTEM = (
    "You are an analyst for a college's student-success platform. Summarise ONLY the JSON facts given; never invent "
    "numbers, names or causes. Quote numbers exactly as they appear; never add, subtract or combine numbers yourself "
    "(totals and percentages are already provided). Scores are 0-100 (60+ is on track). Risks come from simple published rules, not "
    "predictions. Write in plain British English for {audience}. Format exactly: one short headline sentence on the first "
    "line, then 3 to 5 lines that each start with '- ' (key findings first, then 1 or 2 practical next steps). "
    "No markdown other than the '- ' bullets, no tables, under 130 words. If data is missing, say so briefly."
)


COACH = (
    "You are a friendly study coach for {audience}. Using ONLY the JSON facts about their own recorded data, write a "
    "practical plan for the coming week. Format exactly: one short encouraging sentence on the first line, then 4 to 6 "
    "lines that each start with '- ' and give one concrete action with how often or how much (e.g. 'Practise coding "
    "problems 3 times this week for 20 minutes'). Focus on the weakest areas and any risk flags first; mention support "
    "plans if there are any. Address the student as 'you'. Never invent numbers, never compare with named people, never "
    "mention wellbeing diagnoses. Plain British English, no markdown except the '- ' bullets, under 140 words."
)

PLAN = (
    "You help {audience} draft a support plan (intervention) for one student. Using ONLY the JSON facts, return ONE JSON "
    "object and nothing else, in this exact shape: "
    '{{"title": "short plan title, max 80 characters", "steps": ["3 to 5 concrete actions, each under 140 characters"], '
    '"review_weeks": 4}}. '
    "Base the plan on the given category and evidence; be specific about who does what and how often. Never invent "
    "numbers or names. review_weeks is between 2 and 8."
)

ASK = (
    "You translate a college staff member's question about student data into ONE query. Reply with ONE JSON object only. "
    "Allowed shapes:\n"
    '{{"query":"average","metric":M,"group_by":G}} - average of a metric, optionally per group\n'
    '{{"query":"risk_count","risk":"academic"|"placement","group_by":G}} - how many students at each risk level\n'
    '{{"query":"rank","metric":M,"order":"lowest"|"highest","limit":1-10}} - students with the lowest/highest values\n'
    '{{"query":"band_count","group_by":G}} - how many students in each score band\n'
    "M is one of: score, academic, attendance, lms, placement, skills, engagement. "
    "G is one of: none, department, year, department_year. "
    'Optional filters on any query: "department": "CSE"|"ECE"|"MECH", "year": 1-4. '
    'If the question cannot be answered with these, reply {{"query":"unsupported"}}. {audience}'
)


class AIUnavailable(Exception):
    pass


# --------------------------------------------------------------------------- configuration
def api_key() -> str | None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    name = os.environ.get("AI_KEY_PARAM")
    if not name:
        return None
    if _key["value"] and time.time() - _key["at"] < 3600:
        return _key["value"]
    try:
        import boto3
        v = boto3.client("ssm", region_name=settings().region).get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except Exception:
        return None
    _key.update(value=v, at=time.time())
    return v


def enabled() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("AI_KEY_PARAM"))


def _call_with_deadline(fn, seconds: float):
    """Run fn() but give up after `seconds` in total (socket timeouts only cover gaps between bytes)."""
    import concurrent.futures as cf
    ex = cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except cf.TimeoutError:
        raise TimeoutError(f"no answer within {seconds:.0f}s") from None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _http(url: str, body: dict | None, key: str, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "HTTP-Referer": os.environ.get("SITE_URL", "https://smart-campus.local"),
                                          "X-Title": "Smart Campus"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def models(key: str) -> list[str]:
    """Configured models, or the best few free models from OpenRouter's live list (refreshed every 6 hours)."""
    if os.environ.get("AI_MODELS"):
        return [m.strip() for m in os.environ["AI_MODELS"].split(",") if m.strip()][:8]
    if _models["ids"] and time.time() - _models["at"] < 6 * 3600:
        return _models["ids"]
    try:
        data = _http(f"{API}/models", None, key, 5)["data"]
    except Exception:
        return _models["ids"] or []
    free = [m for m in data if m["id"].endswith(":free") and str(m.get("pricing", {}).get("prompt")) in ("0", "0.0") and
            str(m.get("pricing", {}).get("completion")) in ("0", "0.0") and (m.get("context_length") or 0) >= 8000
            and "text" in str((m.get("architecture") or {}).get("output_modalities", ["text"]))]
    def rank(m):
        mid = m["id"].lower()
        return next((i for i, p in enumerate(PREFERRED) if p in mid), len(PREFERRED)), -(m.get("context_length") or 0)
    ids, seen = [], set()
    for m in sorted(free, key=rank):  # one model per provider first, so a busy provider doesn't block the rest
        prov = m["id"].split("/")[0]
        if prov not in seen:
            ids.append(m["id"]); seen.add(prov)
    ids += [m["id"] for m in sorted(free, key=rank) if m["id"] not in ids]
    ids = ids[:8]
    log.warning("openrouter free models: %s (llama available: %s)", ids, [m["id"] for m in free if "llama" in m["id"]][:5])
    _models.update(ids=ids, at=time.time())
    return ids


def complete(facts: dict, audience: str, system: str | None = None, user: str | None = None) -> tuple[str, str]:
    """Try free models one at a time (last good one first) until one answers, within about 16 seconds."""
    key = api_key()
    if not key:
        raise AIUnavailable("AI summaries are not configured.")
    ids = models(key)
    if _models.get("good") in ids:
        ids = [_models["good"]] + [i for i in ids if i != _models["good"]]
    if not ids:
        raise AIUnavailable("No AI model is available right now. Please try again later.")
    messages = [{"role": "system", "content": (system or SYSTEM).format(audience=audience)},
                {"role": "user", "content": user if user is not None else "Facts (JSON):\n" + json.dumps(facts, separators=(",", ":"))}]
    deadline = time.time() + 17  # plus up to 5 s model discovery, inside the 25 s function limit
    busy = False
    for mid in ids:
        left = deadline - time.time()
        if left < 3:
            break
        try:
            # reasoning models think before answering: keep that short and leave room for the summary itself
            msgs = messages
            if mid.startswith(("nvidia/", "qwen/")):  # these honour a "no thinking" switch in the system prompt
                msgs = [{"role": "system", "content": "/no_think\n" + messages[0]["content"]}] + messages[1:]
            # summaries need no step-by-step reasoning: switch it off so the whole allowance goes to the answer
            body = {"model": mid, "messages": msgs, "temperature": 0.1, "max_tokens": 900, "reasoning": {"enabled": False}}
            budget = min(left, 12)
            r = _call_with_deadline(lambda: _http(f"{API}/chat/completions", body, key, budget), budget)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf8", "replace")[:300]
            except Exception:
                detail = ""
            log.warning("openrouter %s for %s: %s", e.code, mid, detail)
            busy = busy or e.code == 429
            if e.code in (401, 402):  # key or account problem: no other model will work either
                raise AIUnavailable("The AI service refused the request (check the API key or account).") from None
            if e.code in (403, 404):  # this model isn't usable from this app: don't try it again
                _models["ids"] = [i for i in (_models["ids"] or []) if i != mid]
            continue
        except Exception as e:  # timeout or network: try the next model
            log.warning("openrouter error for %s: %s %s", mid, type(e).__name__, str(e)[:80])
            continue
        choice = (r.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if text.strip():
            _models["good"] = mid
            return text, r.get("model") or mid
        log.warning("openrouter empty answer from %s (finish %s)", mid, choice.get("finish_reason"))
    if busy:
        raise AIUnavailable("The free AI models are busy right now. Please try again in a minute.")
    raise AIUnavailable("The AI service could not create a summary right now. Please try again.")


def lines(text: str) -> list[str]:
    """Plain lines for display: markdown emphasis and headings stripped, bullets normalised to '- '."""
    out = []
    for ln in text.replace("\r", "").split("\n"):
        bullet = re.match(r"^\s*(?:[-*•–]|\d+[.)])\s+", ln)
        ln = re.sub(r"[*_`#>]+", "", ln[bullet.end():] if bullet else ln).strip()
        ln = re.sub(r"^(?:headline|summary|key findings|next steps?)\s*:\s*", "", ln, flags=re.I)
        if not ln:
            continue
        if bullet:
            ln = "- " + ln
        out.append(ln[:400])
    return out[:8]


# --------------------------------------------------------------------------- facts (no identities)
def _r(v):
    return round(v, 1) if isinstance(v, (int, float)) else v


def _student_facts(p: Principal, ds: str, sid: str) -> tuple[dict, str]:
    prof = views.profile(p, ds, sid)
    ins = prof.get("insight") or {}
    st = prof.get("student") or {}
    risks = ins.get("risks") or {}
    facts = {
        "scope": "one student", "department": st.get("department"), "year": st.get("year"),
        "latest_period": ins.get("period"), "success_score": _r(ins.get("score")), "band": ins.get("band"),
        "data_status": ins.get("status"), "data_coverage_pct": _r((ins.get("coverage") or 0) * 100) if ins.get("coverage") is not None else None,
        "components_0_100": {k: _r((v or {}).get("value")) for k, v in (ins.get("components") or {}).items()},
        "indicators": {k: _r(v) for k, v in (ins.get("indicators") or {}).items()},
        "score_history": [{"period": h["period"], "score": _r(h.get("score"))} for h in prof.get("history", [])],
        "risks": {k: {"level": (v or {}).get("level"), "flags": [f.get("label") for f in (v or {}).get("flags") or []]}
                  for k, v in risks.items()},
        "segments": ins.get("segments"), "support_needs": ins.get("support_needs"),
        "support_plans": [{"category": i.get("category"), "status": i.get("status"), "title": i.get("title")}
                          for i in prof.get("interventions") or []],
    }
    own = p.student is not None and p.student == (ds, sid)
    return facts, ("the student themself (address them as 'you', encouraging and practical)" if own
                   else "the student's mentor and college staff")


def _staff_check(p: Principal, what: str) -> None:
    if p.roles == {"student"} or not grants(p, "student_insight", "read"):
        raise Denied(f"{what} are for staff roles.")


def _overview_facts(p: Principal, ds: str, dept: str | None, year: int | None) -> dict:
    _staff_check(p, "Dashboards")
    d = views.dashboard(p, ds, dept, year, None)
    from collections import Counter
    reasons = Counter(r for x in d["needs_review"] for r in x["reasons"])
    return {"scope": "students visible to this user" + (f", department {dept}" if dept else "") + (f", year {year}" if year else ""),
            "period": d["period"], "students": d["students"], "kpis": d["kpis"], "bands": d["bands"],
            "risk_by_department": d["risk_by_department"], "segments": d["segments"],
            "trend": d["trend"], "review_reasons": dict(reasons)}


def _insights_facts(p: Principal, ds: str, dept: str | None, year: int | None) -> dict:
    _staff_check(p, "Insights")
    a = views.analytics(p, ds, dept, year)
    keep = ("students", "periods", "distribution", "components", "components_by_department", "department_trend",
            "year_averages", "coverage", "risk_matrix", "risk_trend", "band_flow", "early_warning_total")
    facts = {k: a.get(k) for k in keep if a.get(k) is not None}
    if a.get("movers"):  # counts only, no names
        mv = a["movers"]
        facts["movers"] = {k: len(v) for k, v in mv.items()} if isinstance(mv, dict) else len(mv)
    if a.get("early_warning"):
        from collections import Counter
        facts["early_warning_reasons"] = dict(Counter(r for w in a["early_warning"] for r in (w.get("reasons") or [])))
    return {"scope": "students visible to this user" + (f", department {dept}" if dept else ""), **facts}


def _risk_facts(p: Principal, ds: str, kind: str, dept: str | None, year: int | None) -> dict:
    _staff_check(p, "Risk lists")
    from collections import Counter, defaultdict
    rows = views.visible_rows(p, ds, dept, year)
    by = defaultdict(Counter)
    scores = defaultdict(list)
    for r in rows:
        lv = views._risk_level(r, kind)
        if lv in (None, "not_applicable"):
            continue
        lv = {"insufficient_data": "not yet assessed"}.get(lv, f"{lv} risk")  # explicit labels: "low risk" is not "low score"
        by[f"{r['department']} year {r['year']}"][lv] += 1
        if r.get("score") is not None:
            scores[lv].append(r["score"])
    comp = "placement" if kind == "placement" else "academic"
    vals = [(r.get("components") or {}).get(comp) for r in rows]
    vals = [v for v in vals if isinstance(v, (int, float))]
    total = sum(by.values(), Counter())
    n = sum(total.values())
    return {"scope": f"{kind} risk for students visible to this user", "period": insights.current_period(),
            "students_assessed": n, "students_by_level": dict(total),
            "percent_by_level": {k: round(v * 100 / n) for k, v in total.items()} if n else {},
            "high_risk_students_by_class": {k: v.get("high risk", 0) for k, v in sorted(by.items())},
            "levels_by_class": {k: dict(v) for k, v in sorted(by.items())},
            "average_success_score_by_risk_level": {k: _r(mean(v)) for k, v in scores.items() if v},
            f"average_{comp}_component": _r(mean(vals)) if vals else None,
            "segment_strong_academics_low_placement": sum("strong_academics_low_placement" in (r.get("segments") or []) for r in rows)
            if kind == "placement" else None}


IDENTIFYING = {"name", "student_id", "email", "date_of_birth", "comment", "mentor_name", "owner_name", "username",
               "display_name", "sub", "detail", "note", "text", "outcome_note", "evidence_ref"}


def scrub(v):
    """Last line of defence: drop any identifying or free-text field before facts leave the platform."""
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if k not in IDENTIFYING}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    return v


# --------------------------------------------------------------------------- entry point
def summarise(p: Principal, kind: str, ds: str, student_id: str | None = None, department: str | None = None,
              year: int | None = None) -> dict:
    if not enabled():
        raise AIUnavailable("AI summaries are not configured.")
    audience = "college staff (heads of department, mentors, administrators)"
    if kind == "student":
        if not student_id:
            raise AIUnavailable("Choose a student first.")
        facts, audience = _student_facts(p, ds, student_id.upper())
    elif kind == "coach":
        if p.student is None:
            raise Denied("The weekly plan is for students.")
        facts, _ = _student_facts(p, p.student[0], p.student[1])
        return generate(p, "coach", facts, "the student themself", system=COACH, label=p.student[1])
    elif kind == "overview":
        facts = _overview_facts(p, ds, department, year)
    elif kind == "insights":
        facts = _insights_facts(p, ds, department, year)
    elif kind in ("academic", "placement"):
        facts = _risk_facts(p, ds, kind, department, year)
    else:
        raise AIUnavailable("Unknown summary type.")
    return generate(p, kind, facts, audience, label=student_id or department or "all")


def generate(p: Principal, kind: str, facts: dict, audience: str, system: str | None = None, user: str | None = None,
             label: str = "all", raw: bool = False) -> dict:
    """Shared path for every AI feature: scrub, 24-hour cache, per-user daily limit, model call, audit."""
    facts = scrub(facts)
    t = db.table()
    h = hashlib.sha256(json.dumps([kind, audience, facts, system, user], sort_keys=True, default=str).encode()).hexdigest()[:32]
    hit = t.get(f"AI#{h}", "SUMMARY")
    if hit and time.time() - float(hit.get("at", 0)) < CACHE_SECONDS:
        return {"lines": hit["lines"], "text": hit.get("text"), "model": hit.get("model"), "generated_at": hit.get("generated_at"),
                "cached": True}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    q = t.get(f"AIQUOTA#{p.sub}", day) or {"pk": f"AIQUOTA#{p.sub}", "sk": day, "count": 0}
    if int(q["count"]) >= DAILY_LIMIT:
        raise AIUnavailable(f"You've reached today's limit of {DAILY_LIMIT} new AI requests. Try again tomorrow.")
    text, model = complete(facts, audience, system, user)
    out = {"lines": lines(text), "text": text[:4000] if raw else None, "model": model, "generated_at": db.now(), "cached": False}
    t.put({**q, "count": int(q["count"]) + 1})
    t.put({"pk": f"AI#{h}", "sk": "SUMMARY", "lines": out["lines"], "text": out["text"], "model": model,
           "generated_at": out["generated_at"], "at": str(int(time.time())), "kind": kind})
    audit.log(p, f"ai.{kind}_generated", kind, label, {"model": model})
    return out
