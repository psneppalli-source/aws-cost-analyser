"""More AI helpers. Same rules as app/ai.py: only free models, facts without names/IDs, server-computed numbers,
and people approve every draft before anything is saved.

  brief            mentor meeting brief (staff)
  plan_review      drafts a support-plan outcome from the before/after comparison (staff who can update the plan)
  outcomes         "what's working": completed plans by category, figures computed here (staff)
  tidy             rewrites rough notes clearly; names, IDs, emails and phone numbers are masked first (staff)
  digest           this week's changes for heads of department and administrators (staff)
  explain          why a score moved, from the per-component contributions (the student or staff)
  practice         practice or mock-interview questions for a subject (no student data at all)
  help             how-to answers from the app's own help text
  import_help      plain-language explanation of import problems with suggested fixes
  check_entries    rules flag unusual values before saving; AI words a short summary (optional)
  read_certificate reads a certificate photo (free vision model) to pre-fill the form; the image is not stored
"""

from __future__ import annotations

import base64
import re
from collections import Counter, defaultdict
from statistics import mean

from . import ai, imports, insights, interventions, views
from .ai_tools import CATEGORIES, _json_obj
from .categories import CATEGORIES as RECORD_CATEGORIES
from .policy import Denied, Principal, decide, grants

COMP = {"academic": "Academic", "attendance": "Attendance", "lms": "LMS activity", "placement": "Placement readiness",
        "skills": "Skills", "engagement": "Engagement"}


def _staff(p: Principal, what: str) -> None:
    if p.roles == {"student"} or not grants(p, "student_insight", "read"):
        raise Denied(f"{what} is for staff roles.")


def _changes(prof: dict) -> dict:
    """Score and per-component contribution changes between the last two scored periods (computed here)."""
    hist = [h for h in prof.get("history") or [] if h.get("score") is not None]
    if not hist:
        return {"latest_score": None, "note": "no scored period yet"}
    cur = hist[-1]
    out = {"latest_period": cur["period"], "latest_score": cur["score"]}
    if len(hist) < 2:
        return {**out, "note": "only one scored period, so no change to explain"}
    prev = hist[-2]
    if prev.get("profile") != cur.get("profile"):
        return {**out, "note": "the scoring profile changed between periods, so they are not compared"}
    before = {r["component"]: r for r in prev.get("rows") or []}
    rows = []
    for r in cur.get("rows") or []:
        b = before.get(r["component"])
        if r.get("contribution") is None or not b or b.get("contribution") is None:
            continue
        rows.append({"component": COMP.get(r["component"], r["component"]),
                     "component_score_before_0_100": round(b["value"], 1), "component_score_now_0_100": round(r["value"], 1),
                     "success_score_points_added": round(r["contribution"] - b["contribution"], 1)})
    rows.sort(key=lambda x: -abs(x["success_score_points_added"]))
    return {**out, "previous_period": prev["period"], "previous_score": prev["score"],
            "score_change": round(cur["score"] - prev["score"], 1), "component_changes": rows}


# --------------------------------------------------------------------------- prompts
BRIEF = (
    "You prepare {audience} for a short one-to-one meeting with a student. Using ONLY the JSON facts, write: one line "
    "summarising where the student stands, then lines starting with '- ' in this order: 2-3 things that changed since "
    "the previous period, support plans that are due or overdue (with dates as given), and exactly 3 open questions the "
    "mentor could ask (start each with 'Ask: '). Quote numbers exactly as given; never invent numbers, names or causes. "
    "Plain British English, no markdown except '- ', under 170 words."
)
REVIEW = (
    "You help {audience} record the outcome of a support plan. Using ONLY the JSON facts (plan, before/after figures "
    "computed by the system, current risk flags), reply with ONE JSON object only: "
    '{{"result": "improved"|"no_change"|"declined"|"not_assessed", "recommendation": "continue"|"adjust"|"close", '
    '"note": "2-3 sentences for the record, quoting figures exactly as given, and saying a change is an association, '
    'not proof the plan caused it"}}. If the before/after figures are not comparable, use "not_assessed".'
)
OUTCOMES = (
    "You summarise for {audience} how completed support plans went. The JSON facts give, per plan category, how many "
    "plans were completed and their recorded outcomes; percentages are already computed. Format: one headline line, "
    "then 3-5 lines starting with '- '. Quote numbers exactly; never add or combine numbers. Say clearly that these "
    "show what went together with improvement, not what caused it, and note small groups (under 5 plans). Plain British "
    "English, under 140 words."
)
TIDY = (
    "Rewrite the staff note below so it is clear, professional and correctly spelt, in British English. Keep every fact "
    "and its meaning; do not add facts, opinions, diagnoses or advice. Keep placeholders like [STUDENT], [EMAIL] and "
    "[PHONE] exactly as written. Reply with the rewritten note only, without quotes or explanations. {audience}"
)
DIGEST = (
    "You write this week's digest for {audience}. Using ONLY the JSON facts (all figures are computed by the system), "
    "write one headline line, then 4-6 lines starting with '- ' covering: new early warnings and their main reasons, "
    "overdue support plans, risk changes since last period, and biggest improvements or declines (counts only). End "
    "with one '- Next: ' line suggesting the most useful action. Quote numbers exactly; never add numbers. Plain British "
    "English, no markdown except '- ', under 150 words."
)
EXPLAIN = (
    "Explain to {audience} why the Success Score changed, using ONLY the JSON facts. 'success_score_points_added' is how many Success "
    "Score points each component added (negative = removed); component scores are 0-100 and are not attendance percentages. Format: one plain sentence with the overall "
    "change, then 2-4 lines starting with '- ' naming the components that moved most (quote the figures exactly), then "
    "one '- Tip: ' line with a practical next step. If there is no change to explain, say why in one sentence. Never "
    "invent numbers. Plain British English, under 120 words."
)
PRACTICE = (
    "You are a helpful tutor for {audience}. Write 5 practice questions for the topic in the JSON facts, from easier to "
    "harder, suitable for the level given. Format: one short line introducing the set, then 5 lines that each start "
    "with '- ' and contain the question followed by ' Hint: ' and a one-line hint. No answers, no markdown except '- '."
)
HELP = (
    "You answer questions about using the Smart Campus web app for {audience}. Answer ONLY from the help text in the "
    "JSON facts. If the answer is not there, say you are not sure and suggest asking the college office. Format: one "
    "short line, then up to 5 lines starting with '- ' with the steps. Plain British English, under 120 words."
)
IMPORT = (
    "You help {audience} fix a CSV/Excel import. Using ONLY the JSON facts (expected columns, detected column mapping "
    "and grouped problems with counts), write one headline line, then 3-6 lines starting with '- ' that explain each "
    "problem in plain words and how to fix it in the spreadsheet (e.g. rename a column, fill a missing value, correct a "
    "range). Quote counts exactly. Plain British English, under 150 words."
)
ENTRIES = (
    "In one or two plain sentences for {audience}, summarise the warnings in the JSON facts (computed by rules) and "
    "suggest checking them before saving. Quote counts exactly. No markdown."
)
CERT = (
    "Read the certificate in the image. Reply with ONE JSON object only: {{\"name\": course or certificate title, "
    "\"issuer\": organisation that issued it, \"date\": issue date as YYYY-MM-DD or null}}. Use null for anything you "
    "cannot read clearly. Do not include the person's name. {audience}"
)

HELP_TEXT = {
    "sign_in": "Sign in with your user ID and password, then the 6-digit code from your authenticator app. "
               "Forgot password? and Lost your phone? on the sign-in page reset them using a code emailed to you.",
    "register": "New students choose 'Create your account' on the sign-in page, enter their student ID and date of birth "
                "and any email address, then the 6-digit code emailed to them, then choose a user ID and password.",
    "security": "Account > Security: change password, or move the authenticator app to a new phone.",
    "student_dashboard": "Students: My dashboard shows your Success Score, marks by subject, improvement, semester results, "
                         "what to focus on, support plans and submissions. 'Make my weekly plan' and 'Explain my score' use AI.",
    "submit": "Students: Submit information lets you add a certificate (it counts after staff verify it) or share "
              "feedback (seen only by you, your mentor, HOD and administrator; it never lowers your score). A photo "
              "of a certificate can pre-fill the form.",
    "practice": "Students: on My dashboard, Practice questions creates questions for a subject or mock interview questions.",
    "overview": "Staff: Overview shows key figures, risk by department and students needing review. Weekly digest summarises changes.",
    "insights": "Staff: Insights shows charts. Ask about your students answers questions such as averages by department, "
                "risk counts, score bands, or the highest/lowest students.",
    "students": "Staff: Students lists the students you may see with filters; open one to see the profile, Meeting brief and Explain score.",
    "enter_data": "Staff: Enter data: choose what to enter, the period, department and year, type values in the grid, "
                  "use 'Check entries' to spot unusual values, then Save. Changes to saved marks, attendance and results go to the HOD for approval.",
    "import": "Staff: Import CSV / Excel: choose the data type, download the template, upload, preview problems "
              "('Explain these problems' uses AI), then apply.",
    "interventions": "Staff: Support plans (interventions) are created from a student's profile (Risks & actions). "
                     "'Draft with AI' fills a draft; 'Draft review' suggests an outcome. Interventions page lists all plans; "
                     "'What's working' summarises outcomes.",
    "notes": "Staff: add notes to a support plan on the student's profile; 'Tidy' rewrites a note clearly. Students never see notes.",
    "approvals": "Staff: Approvals & verification: HODs approve corrections to saved data; staff verify student certificates.",
    "users": "Administrators: Users and roles: create staff accounts (an invitation with a temporary password is emailed), "
             "assign roles, disable accounts, send a password reset, or reset an authenticator.",
    "ai": "AI features use free models, send no names or IDs, can be wrong, and always need a person to check.",
}


def _lines_out(out: dict) -> dict:
    return {"lines": out["lines"], "model": out["model"], "cached": out["cached"]}


# --------------------------------------------------------------------------- features
def brief(p: Principal, ds: str, sid: str) -> dict:
    _staff(p, "The meeting brief")
    facts, _ = ai._student_facts(p, ds, sid.upper())
    prof = views.profile(p, ds, sid.upper())
    facts["since_previous_period"] = _changes(prof)
    facts["support_plans"] = [{"title": i.get("title"), "category": i.get("category"), "status": i.get("status"),
                               "due_date": i.get("due_date"), "review_date": i.get("review_date"), "overdue": i.get("overdue")}
                              for i in prof.get("interventions") or [] if i.get("status") != "Completed"]
    return _lines_out(ai.generate(p, "brief", facts, "a mentor", system=BRIEF, label=sid))


def plan_review(p: Principal, ds: str, sid: str, iid: str) -> dict:
    prof = views.profile(p, ds, sid.upper())
    if not prof.get("permissions", {}).get("update_intervention"):
        raise Denied("You can't update support plans for this student.")
    iv = next((i for i in prof.get("interventions") or [] if i["intervention_id"] == iid), None)
    if not iv:
        raise Denied("Support plan not found.")
    name = (prof.get("student") or {}).get("name") or ""
    detail = (iv.get("detail") or "")
    if name:
        detail = re.sub(re.escape(name), "the student", detail, flags=re.I)
    ins = prof.get("insight") or {}
    facts = {"plan": {"title": iv.get("title"), "category": CATEGORIES.get(iv.get("category"), iv.get("category")),
                      "steps": detail[:600], "status": iv.get("status"), "due_date": iv.get("due_date")},
             "before_after": iv.get("comparison"),
             "current_risk_flags": {k: [f.get("label") for f in (v or {}).get("flags") or []] for k, v in (ins.get("risks") or {}).items()},
             "current_components": {k: (v or {}).get("value") for k, v in (ins.get("components") or {}).items()}}
    facts["plan"]["steps_text"] = facts["plan"].pop("steps")  # 'detail' style keys are scrubbed; this one is pre-cleaned
    out = ai.generate(p, "plan_review", facts, "a mentor", system=REVIEW, label=iid, raw=True, accept=lambda t: bool(_json_obj(t)))
    obj = _json_obj(out.get("text") or "") or {}
    result = obj.get("result") if obj.get("result") in ("improved", "no_change", "declined", "not_assessed") else "not_assessed"
    rec = obj.get("recommendation") if obj.get("recommendation") in ("continue", "adjust", "close") else "continue"
    note = str(obj.get("note") or " ".join(out["lines"]))[:900].strip()
    if not note:
        raise ai.AIUnavailable("The AI could not draft a review this time. Please try again.")
    return {"result": result, "recommendation": rec, "note": note, "model": out["model"], "cached": out["cached"]}


def outcomes(p: Principal, ds: str, dept: str | None = None) -> dict:
    _staff(p, "This summary")
    if decide(p, "intervention", "read", None) is None and not grants(p, "intervention", "read"):
        raise Denied("You can't see support plans.")
    items, _ = interventions.listing(p, ds, status="Completed", dept=dept, limit=500)
    by = defaultdict(lambda: {"completed": 0, "results": Counter(), "score_changes": []})
    for i in items:
        c = by[CATEGORIES.get(i.get("category"), "Other")]
        c["completed"] += 1
        c["results"][(i.get("outcome") or {}).get("result") or "not_recorded"] += 1
        b, a = (i.get("baseline") or {}), ((i.get("outcome") or {}).get("after") or {})
        if b.get("score") is not None and a.get("score") is not None and b.get("profile") == a.get("profile"):
            c["score_changes"].append(a["score"] - b["score"])
    facts = {"scope": "completed support plans visible to this user" + (f", department {dept}" if dept else ""),
             "total_completed": len(items), "by_category": {}}
    for k, c in sorted(by.items()):
        n = c["completed"]
        facts["by_category"][k] = {"completed": n, "outcomes": dict(c["results"]),
                                   "percent_improved": round(c["results"].get("improved", 0) * 100 / n) if n else None,
                                   "average_score_change": round(mean(c["score_changes"]), 1) if c["score_changes"] else None,
                                   "small_group": n < 5}
    if not items:
        return {"lines": ["No support plans have been completed yet, so there is nothing to compare."], "model": None, "cached": False}
    return _lines_out(ai.generate(p, "outcomes", facts, "heads of department and administrators", system=OUTCOMES, label=dept or "all"))


def tidy(p: Principal, ds: str, sid: str, text: str) -> dict:
    prof = views.profile(p, ds, sid.upper())
    if not prof.get("permissions", {}).get("staff_note"):
        raise Denied("You can't add notes for this student.")
    raw = (text or "").strip()[:2000]
    if len(raw) < 5:
        raise ai.AIUnavailable("Write the note first, then use Tidy.")
    name = (prof.get("student") or {}).get("name") or ""
    masked = raw
    if name:
        masked = re.sub(re.escape(name), "[STUDENT]", masked, flags=re.I)
        first = name.split()[0]
        masked = re.sub(rf"\b{re.escape(first)}\b", "[STUDENT]", masked, flags=re.I)
    masked = re.sub(r"\b(?:CSE|ECE|MECH)\d{5}\b", "[STUDENT ID]", masked, flags=re.I)
    masked = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[EMAIL]", masked)
    masked = re.sub(r"\+?\d[\d\s-]{8,}\d", "[PHONE]", masked)
    out = ai.generate(p, "tidy", {"note": "masked"}, "", system=TIDY, user=masked, label=sid, raw=True)
    tidy_text = (out.get("text") or "\n".join(out["lines"])).strip().strip('"')[:2000]
    if name:
        tidy_text = tidy_text.replace("[STUDENT]", name.split()[0])
    sid_u = sid.upper()
    tidy_text = tidy_text.replace("[STUDENT ID]", sid_u)
    return {"text": tidy_text, "model": out["model"], "masked": masked != raw}


def digest(p: Principal, ds: str, dept: str | None = None, year: int | None = None) -> dict:
    _staff(p, "The weekly digest")
    a = views.analytics(p, ds, dept, year)
    d = views.dashboard(p, ds, dept, year, None)
    per = a.get("periods") or []
    rt = a.get("risk_trend") or {}
    def last2(series):
        return series[-2:] if isinstance(series, list) else series
    reasons = Counter(r for w in a.get("early_warning") or [] for r in (w.get("reasons") or []))
    mv = a.get("movers") or {}
    facts = {"scope": "students visible to this user" + (f", department {dept}" if dept else ""), "period": per[-1] if per else None,
             "previous_period": per[-2] if len(per) > 1 else None, "students": a.get("students"),
             "early_warnings_this_period": a.get("early_warning_total"),
             "early_warning_reasons": dict(reasons.most_common(5)),
             "overdue_support_plans": d["kpis"].get("overdue_interventions"), "open_support_plans": d["kpis"].get("open_interventions"),
             "high_academic_risk_last_two_periods": last2(rt.get("academic")), "high_placement_risk_last_two_periods": last2(rt.get("placement")),
             "students_improved_5_plus": len(mv.get("up", [])) if isinstance(mv, dict) else None,
             "students_declined_5_plus": len(mv.get("down", [])) if isinstance(mv, dict) else None,
             "average_score": d["kpis"].get("average_score")}
    return _lines_out(ai.generate(p, "digest", facts, "heads of department and administrators", system=DIGEST, label=dept or "all"))


def explain(p: Principal, ds: str, sid: str) -> dict:
    prof = views.profile(p, ds, sid.upper())
    own = p.student is not None and p.student == (ds, sid.upper())
    facts = _changes(prof)
    facts["scale"] = "0-100; 60+ is on track"
    aud = "the student themself (address them as 'you')" if own else "the student's mentor"
    return _lines_out(ai.generate(p, "explain", facts, aud, system=EXPLAIN, label=sid))


def practice(p: Principal, ds: str, mode: str, subject: str | None) -> dict:
    level, dept = "undergraduate engineering", None
    if p.student:
        prof = views.profile(p, p.student[0], p.student[1])
        st = prof.get("student") or {}
        level = f"year {st.get('year')} undergraduate engineering"
        dept = st.get("department")
    if mode == "interview":
        facts = {"topic": "campus placement interview (technical and HR questions)", "level": level, "department": dept}
    else:
        subj = re.sub(r"[^A-Za-z0-9 &()/+,.-]", "", subject or "").strip()[:80]
        if len(subj) < 2:
            raise ai.AIUnavailable("Choose a subject first.")
        facts = {"topic": subj, "level": level}
    return _lines_out(ai.generate(p, "practice", facts, "a college student", system=PRACTICE, label=facts["topic"][:40]))


def help_answer(p: Principal, question: str) -> dict:
    q = re.sub(r"\s+", " ", question or "").strip()[:300]
    if len(q) < 4:
        raise ai.AIUnavailable("Type a question, for example: How do I reset my password?")
    q = re.sub(r"\b(?:CSE|ECE|MECH)\d{5}\b", "a student", q, flags=re.I)
    roles = ", ".join(sorted(p.roles)) or "user"
    facts = {"user_roles": roles, "help": HELP_TEXT}
    return _lines_out(ai.generate(p, "help", facts, f"a signed-in user with roles: {roles}", system=HELP,
                                  user=f"Help text (JSON): {HELP_TEXT}\n\nQuestion: {q}", label="help"))


def import_help(p: Principal, iid: str) -> dict:
    imp = imports.get(p, iid)
    cat = imp.get("category")
    spec = RECORD_CATEGORIES.get(cat)
    fields = [f.name for f in spec.fields] if spec else []
    groups = Counter()
    for row in imp.get("problems") or []:
        for e in row.get("errors") or []:
            groups[re.sub(r"\b(?:CSE|ECE|MECH)\d{5}\b", "<student>", re.sub(r"\d+(?:\.\d+)?", "<n>", str(e)))[:160]] += 1
    facts = {"data_type": cat, "expected_columns": ["student_id", "period", *fields] if fields else None,
             "detected_mapping": imp.get("mapping"), "ignored_columns": imp.get("ignored_columns"), "rows_total": imp.get("total_rows"), "accepted": imp.get("accepted"),
             "rejected": imp.get("rejected"), "duplicates": imp.get("duplicates"),
             "problems_grouped": dict(groups.most_common(12))}
    if not groups:
        return {"lines": ["There are no problems to explain in this import."], "model": None, "cached": False}
    return _lines_out(ai.generate(p, "import_help", facts, "the person importing data", system=IMPORT, label=iid))


def check_entries(p: Principal, category: str, common: dict, rows: list) -> dict:
    """Rules first (always available); AI only words a short summary when warnings exist."""
    _staff(p, "Checking entries")
    warns = []
    num = lambda v: float(v) if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v.strip() or "x")) else None  # noqa: E731
    seen = Counter()
    for r in rows[:500]:
        sid, v, saved = str(r.get("student_id", "")), r.get("values") or {}, r.get("saved") or {}
        vals = {**(common or {}), **v}
        w = lambda field, msg: warns.append({"student_id": sid, "field": field, "message": msg})  # noqa: E731
        if category == "marks":
            s, mx = num(vals.get("score")), num(vals.get("max_score"))
            if s is not None and mx and s > mx:
                w("score", f"score {s:g} is above the maximum {mx:g}")
            if s is not None and mx and saved.get("score") is not None and num(saved.get("max_score")):
                old = num(saved["score"]) / num(saved["max_score"]) * 100
                if abs(s / mx * 100 - old) >= 30:
                    w("score", f"changes the saved mark by {abs(s / mx * 100 - old):.0f} percentage points")
        elif category == "attendance":
            h, a = num(vals.get("classes_held")), num(vals.get("classes_attended"))
            if h is not None and a is not None and a > h:
                w("classes_attended", f"attended ({a:g}) is more than held ({h:g})")
            if h == 0:
                w("classes_held", "no classes held")
            if h and a is not None and a / h < 0.4:
                w("classes_attended", f"very low attendance ({a / h * 100:.0f}%)")
        elif category == "academic_result":
            cg, sg, bl = num(vals.get("cgpa")), num(vals.get("sgpa")), num(vals.get("backlogs"))
            if cg is not None and not 0 <= cg <= 10:
                w("cgpa", f"CGPA {cg:g} is outside 0-10")
            if cg is not None and sg is not None and abs(cg - sg) > 3:
                w("sgpa", f"SGPA {sg:g} is far from CGPA {cg:g}")
            if bl is not None and bl > 8:
                w("backlogs", f"{bl:g} backlogs is unusually high")
            if cg is not None and num(saved.get("cgpa")) is not None and abs(cg - num(saved["cgpa"])) > 1.5:
                w("cgpa", f"CGPA changes by {abs(cg - num(saved['cgpa'])):.1f} from the saved value")
        elif category == "lms":
            due, sub, lg = num(vals.get("assignments_due")), num(vals.get("assignments_submitted")), num(vals.get("logins"))
            if due is not None and sub is not None and sub > due:
                w("assignments_submitted", f"submitted ({sub:g}) is more than due ({due:g})")
            if lg is not None and lg > 300:
                w("logins", f"{lg:g} logins in a month is unusually high")
        elif category in ("skills", "placement_assessment"):
            for k in ("technical", "communication", "score"):
                x = num(vals.get(k))
                if x is not None and not 0 <= x <= 100 and not (category == "placement_assessment" and vals.get("assessment_type") == "mock_interview" and 0 <= x <= 5):
                    w(k, f"{k} {x:g} looks out of range")
        sig = tuple(sorted((k, str(x)) for k, x in v.items() if str(x).strip()))
        if sig:
            seen[sig] += 1
    copies = sum(n for n in seen.values() if n >= 5)
    if copies:
        warns.append({"student_id": "", "field": "", "message": f"{copies} rows have exactly the same values; check they weren't pasted by mistake"})
    out = {"warnings": warns, "rows_checked": len(rows), "summary": None, "model": None}
    if warns and ai.enabled():
        try:
            facts = {"data_type": category, "rows_checked": len(rows), "warnings": len(warns),
                     "warning_types": dict(Counter(re.sub(r"\d+(?:\.\d+)?", "<n>", x["message"]) for x in warns).most_common(6))}
            g = ai.generate(p, "check_entries", facts, "the staff member entering data", system=ENTRIES, label=category)
            out["summary"], out["model"] = " ".join(g["lines"]), g["model"]
        except ai.AIUnavailable:
            pass
    return out


def read_certificate(p: Principal, image_data_url: str) -> dict:
    m = re.match(r"^data:image/(png|jpe?g|webp);base64,([A-Za-z0-9+/=]+)$", image_data_url or "")
    if not m:
        raise ai.AIUnavailable("Choose a photo or scan of the certificate (JPG, PNG or WebP).")
    if len(m.group(2)) > 2_000_000:
        raise ai.AIUnavailable("The image is too large. Please use a smaller photo.")
    base64.b64decode(m.group(2)[:100] + "==", validate=False)
    content = [{"type": "text", "text": "Read this certificate."},
               {"type": "image_url", "image_url": {"url": image_data_url}}]
    ai.use_quota(p)
    def readable(t: str) -> bool:
        o = _json_obj(t) or {}
        return bool(o.get("name") or o.get("issuer"))
    text, model = ai.complete({}, "", system=CERT, user=content, vision=True, accept=readable)
    obj = _json_obj(text) or {}
    date = obj.get("date") if isinstance(obj.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", obj.get("date") or "") else None
    clean = lambda v: re.sub(r"\s+", " ", str(v)).strip()[:120] if v and str(v).lower() != "null" else None  # noqa: E731
    out = {"name": clean(obj.get("name")), "issuer": clean(obj.get("issuer")), "date": date, "model": model}
    if not (out["name"] or out["issuer"]):
        raise ai.AIUnavailable("The certificate couldn't be read clearly. Please type the details instead.")
    from . import audit
    audit.log(p, "ai.certificate_read", "certificate", p.student[1] if p.student else p.username, {"model": model})
    return out
