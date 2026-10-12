"""AI helpers that act on real data without letting the model invent numbers.

draft_plan: the model drafts a support-plan title and steps from one student's facts; staff edit and confirm it.
ask:        the model only translates a question into one of a few fixed queries; the server checks it, runs it
            against the rows this user may see and writes the answer sentence itself. If the model is busy or
            unclear, a keyword reader handles common questions.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from statistics import mean

from . import ai, views
from .policy import Denied, Principal, decide, grants
from .recordsvc import get_master, target

METRICS = {"score": "Success Score", "academic": "Academic", "attendance": "Attendance", "lms": "LMS activity",
           "placement": "Placement readiness", "skills": "Skills", "engagement": "Engagement"}
GROUPS = ("none", "department", "year", "department_year")
DEPTS = ("CSE", "ECE", "MECH")
CATEGORIES = {"academic": "Academic", "attendance": "Attendance", "wellbeing": "Wellbeing",
              "placement_training": "Placement training", "other": "Other"}


def _json_obj(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- support-plan drafts
def draft_plan(p: Principal, ds: str, sid: str, category: str, recommendation: str | None, evidence: list | None) -> dict:
    sid = sid.upper()
    if decide(p, "intervention", "create", target(get_master(ds, sid))) is None:
        raise Denied("You can't create support plans for this student.")
    facts, _ = ai._student_facts(p, ds, sid)
    facts["plan_category"] = CATEGORIES.get(category, "Other")
    facts["recommendation"] = (recommendation or "")[:120] or None
    facts["evidence"] = [{"label": str(e.get("label", ""))[:120], "observed": e.get("observed"), "threshold": e.get("threshold"),
                          "period": e.get("period")} for e in (evidence or [])[:6] if isinstance(e, dict)]
    out = ai.generate(p, "plan_draft", facts, "a mentor or head of department", system=ai.PLAN, label=sid, raw=True,
                      accept=lambda t: bool((_json_obj(t) or {}).get("steps")))
    obj = _json_obj(out.get("text") or "\n".join(out["lines"])) or {}
    steps = [str(x).strip()[:160] for x in (obj.get("steps") or []) if str(x).strip()][:5]
    if not steps:  # model ignored the JSON shape: fall back to its bullet lines
        steps = [ln[2:] for ln in out["lines"] if ln.startswith("- ")][:5]
    title = str(obj.get("title") or (recommendation or f"{CATEGORIES.get(category, 'Support')} support plan")).strip()[:100]
    try:
        weeks = min(8, max(2, int(obj.get("review_weeks") or 4)))
    except (TypeError, ValueError):
        weeks = 4
    if not steps:
        raise ai.AIUnavailable("The AI could not draft a plan this time. Please try again or write it yourself.")
    return {"title": title, "steps": steps, "review_weeks": weeks, "model": out["model"], "cached": out["cached"]}


# --------------------------------------------------------------------------- ask a question
def _keywords(q: str) -> dict:
    """Best-effort reading of common questions without the model."""
    s = q.lower()
    spec: dict = {}
    if re.search(r"\bband", s):
        spec["query"] = "band_count"
    elif re.search(r"\brisk|at[- ]risk|flagged", s):
        spec["query"] = "risk_count"
        spec["risk"] = "placement" if "placement" in s else "academic"
    elif re.search(r"\bwhich (?:department|dept|branch|year|class|group)", s):
        spec["query"] = "average"  # "which department has the lowest X" compares groups, not students
    elif re.search(r"\b(lowest|bottom|weakest|worst|least|highest|top|best|strongest)\b", s):
        spec["query"] = "rank"
        spec["order"] = "lowest" if re.search(r"\b(lowest|bottom|weakest|worst|least)\b", s) else "highest"
        n = re.search(r"\b(\d{1,2})\b", s)
        spec["limit"] = int(n.group(1)) if n else 5
    else:
        spec["query"] = "average"
    for k in ("attendance", "engagement", "skills", "academic", "lms", "placement"):
        if k in s:
            spec.setdefault("metric", k)
    spec.setdefault("metric", "score")
    by_d = bool(re.search(r"department|dept|branch|each (?:cse|ece|mech)", s))
    by_y = bool(re.search(r"\b(?:by|each|per) year|which year|year[- ]wise", s))
    if re.search(r"which class|by class|each class", s):
        by_d = by_y = True
    spec["group_by"] = "department_year" if by_d and by_y else "department" if by_d else "year" if by_y else "none"
    if spec["query"] == "average" and spec["group_by"] == "none" and re.search(r"\bwhich\b", s):
        spec["group_by"] = "department"
    d = re.search(r"\b(cse|ece|mech)\b", s)
    if d:
        spec["department"] = d.group(1).upper()
    y = re.search(r"\b(?:year|yr|y)\s*([1-4])\b|\b([1-4])(?:st|nd|rd|th) year\b", s)
    if y:
        spec["year"] = int(y.group(1) or y.group(2))
    return spec


def _valid(spec: dict) -> dict | None:
    if not isinstance(spec, dict):
        return None
    qy = spec.get("query")
    if qy not in ("average", "risk_count", "rank", "band_count"):
        return None
    out = {"query": qy, "group_by": spec.get("group_by") if spec.get("group_by") in GROUPS else "none"}
    if qy in ("average", "rank"):
        out["metric"] = spec.get("metric") if spec.get("metric") in METRICS else "score"
    if qy == "risk_count":
        out["risk"] = "placement" if spec.get("risk") == "placement" else "academic"
    if qy == "rank":
        out["order"] = "highest" if spec.get("order") == "highest" else "lowest"
        try:
            out["limit"] = min(10, max(1, int(spec.get("limit") or 5)))
        except (TypeError, ValueError):
            out["limit"] = 5
    d = str(spec.get("department") or "").upper()
    if d in DEPTS:
        out["department"] = d
    try:
        y = int(spec.get("year") or 0)
        if 1 <= y <= 4:
            out["year"] = y
    except (TypeError, ValueError):
        pass
    return out


def _value(r: dict, metric: str):
    v = r.get("score") if metric == "score" else (r.get("components") or {}).get(metric)
    return v if isinstance(v, (int, float)) else None


def _group(r: dict, g: str) -> str:
    return {"none": "All students", "department": r["department"], "year": f"Year {r['year']}",
            "department_year": f"{r['department']} Y{r['year']}"}[g]


def _describe(spec: dict) -> str:
    where = " in " + " ".join(x for x in (spec.get("department"), f"year {spec['year']}" if spec.get("year") else None) if x) \
        if spec.get("department") or spec.get("year") else ""
    by = {"none": "", "department": " by department", "year": " by year", "department_year": " by department and year"}[spec["group_by"]]
    if spec["query"] == "average":
        return f"Average {METRICS[spec['metric']]}{by}{where}"
    if spec["query"] == "risk_count":
        return f"Students by {spec['risk']} risk level{by}{where}"
    if spec["query"] == "band_count":
        return f"Students by score band{by}{where}"
    return f"{spec['limit']} students with the {spec['order']} {METRICS[spec['metric']]}{where}"


def run(p: Principal, ds: str, spec: dict) -> dict:
    rows = views.visible_rows(p, ds, spec.get("department"), spec.get("year"))
    g = spec["group_by"]
    title = _describe(spec)
    if spec["query"] == "rank":
        m = spec["metric"]
        vals = [(r, _value(r, m)) for r in rows if _value(r, m) is not None]
        vals.sort(key=lambda x: x[1], reverse=spec["order"] == "highest")
        top = vals[:spec["limit"]]
        table = [{"student_id": r["student_id"], "name": r.get("name"), "class": f"{r['department']} Y{r['year']}", "value": round(v, 1)}
                 for r, v in top]
        sentence = (f"These {len(table)} of {len(vals)} students have the {spec['order']} {METRICS[m]}." if table
                    else "No students have a value for this yet.")
        return {"title": title, "kind": "students", "columns": ["Student", "Class", METRICS[m]], "rows": table,
                "chart": [{"label": t["name"] or t["student_id"], "value": t["value"]} for t in table], "sentence": sentence}
    groups: dict = defaultdict(list)
    for r in rows:
        groups[_group(r, g)].append(r)
    out = []
    if spec["query"] == "average":
        m = spec["metric"]
        for k, rs in sorted(groups.items()):
            vs = [v for v in (_value(r, m) for r in rs) if v is not None]
            out.append({"group": k, "value": round(mean(vs), 1) if vs else None, "students": len(vs)})
        scored = [o for o in out if o["value"] is not None]
        if not scored:
            sentence = "No students have a value for this yet."
        elif len(scored) == 1:
            sentence = f"{scored[0]['group']}: average {METRICS[m]} {scored[0]['value']} across {scored[0]['students']} students."
        else:
            hi, lo = max(scored, key=lambda o: o["value"]), min(scored, key=lambda o: o["value"])
            sentence = f"Highest: {hi['group']} ({hi['value']}). Lowest: {lo['group']} ({lo['value']})."
        return {"title": title, "kind": "groups", "columns": ["Group", f"Average {METRICS[m]}", "Students"], "rows": out,
                "chart": [{"label": o["group"], "value": o["value"]} for o in scored], "sentence": sentence}
    if spec["query"] == "risk_count":
        kind = spec["risk"]
        levels = ("high", "medium", "low", "insufficient_data")
        for k, rs in sorted(groups.items()):
            c = Counter(views._risk_level(r, kind) for r in rs)
            out.append({"group": k, **{lv: c.get(lv, 0) for lv in levels}, "students": len(rs)})
        tot = sum(o["high"] for o in out)
        worst = max(out, key=lambda o: o["high"]) if out else None
        sentence = (f"{tot} students at high {kind} risk" + (f"; most in {worst['group']} ({worst['high']})." if worst and len(out) > 1 and tot else ".")
                    if out else "No students match.")
        return {"title": title, "kind": "risk", "columns": ["Group", "High", "Medium", "Low", "Not enough data", "Students"],
                "rows": out, "chart": [{"label": o["group"], "value": o["high"]} for o in out], "sentence": sentence}
    bands = ("Strong", "On track", "Needs attention", "At risk", "Insufficient data")
    for k, rs in sorted(groups.items()):
        c = Counter(r.get("band") or "Insufficient data" for r in rs)
        out.append({"group": k, **{b: c.get(b, 0) for b in bands}, "students": len(rs)})
    total = Counter()
    for o in out:
        total.update({b: o[b] for b in bands})
    big = total.most_common(1)[0] if total else None
    return {"title": title, "kind": "bands", "columns": ["Group", *bands, "Students"], "rows": out,
            "chart": [{"label": b, "value": total[b]} for b in bands],
            "sentence": f"Most common band: {big[0]} ({big[1]} students)." if big and big[1] else "No students match."}


def ask(p: Principal, ds: str, question: str) -> dict:
    if p.roles == {"student"} or not grants(p, "student_insight", "read"):
        raise Denied("Questions about student data are for staff roles.")
    q = re.sub(r"\s+", " ", (question or "")).strip()[:300]
    if len(q) < 4:
        raise ai.AIUnavailable("Type a question, for example: Which department has the lowest attendance?")
    # never send a student's name or ID to the model: replace any that appear in the question
    safe = re.sub(r"\b(?:CSE|ECE|MECH)\d{5}\b", "a student", q, flags=re.I)
    for r in views.visible_rows(p, ds):
        if r.get("name") and r["name"].lower() in safe.lower():
            safe = re.sub(re.escape(r["name"]), "a student", safe, flags=re.I)
    spec, source, model = None, "keywords", None
    if ai.enabled():
        try:
            out = ai.generate(p, "ask", {"question": safe}, "", system=ai.ASK, user=f"Question: {safe}", label="insights", raw=True,
                              accept=lambda t: bool((_json_obj(t) or {}).get("query")))
            obj = _json_obj(out.get("text") or "")
            if obj and obj.get("query") == "unsupported":
                return {"supported": False, "question": q, "source": "ai", "model": out["model"],
                        "message": "That question can't be answered from these figures yet. Try asking about averages, "
                                   "risk levels, score bands or the highest/lowest students."}
            spec = _valid(obj or {})
            if spec:
                source, model = "ai", out["model"]
        except ai.AIUnavailable:
            spec = None
    if not spec:
        spec = _valid(_keywords(q))
    res = run(p, ds, spec)
    return {"supported": True, "question": q, "query": spec, "source": source, "model": model, **res}
