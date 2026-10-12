"""Deterministic demo dataset: 150 fictional students (dataset 'demo').

    python -m app.seed                  # idempotent; skips anything staff have changed
    python -m app.seed --accounts       # also create the 9 demo accounts (local-demo mode)

* Fixed random seed and versioned generator (SEED_VERSION / DATASET_VERSION).
* Every item is labelled synthetic (dataset 'demo', source 'seed').
* Re-running writes only missing items or items still owned by an older seed
  version; anything a person has edited (source != 'seed') is never overwritten.
* Only nine sign-in accounts are created; students don't get accounts just
  because their records exist.
"""

from __future__ import annotations

import argparse
import random
import time

from . import db, insights
from .categories import CATEGORIES
from .policy import Principal
from .settings import curriculum
from .store import C, ConditionFailed

SEED = 20260401
SEED_VERSION = 4
DATASET_VERSION = "demo-2026.09"
DS = "demo"
DEPTS = ["CSE", "ECE", "MECH"]
FIRST = ["Aarav", "Ananya", "Vihaan", "Diya", "Arjun", "Saanvi", "Ishaan", "Kavya", "Rohan", "Meera", "Karthik", "Isha",
         "Siddharth", "Riya", "Pranav", "Lakshmi", "Varun", "Sneha", "Nikhil", "Tanvi", "Farhan", "Zoya", "Joseph", "Fatima",
         "Tenzin", "Anjali", "Deepak", "Aditi", "Harsh", "Neha"]
LAST = ["Sharma", "Reddy", "Iyer", "Nair", "Patel", "Gupta", "Singh", "Rao", "Kumar", "Menon", "Joshi", "Das", "Mehta",
        "Pillai", "Kulkarni", "Naidu", "Khan", "D'Souza", "Hegde", "Banerjee"]
ARCHETYPES = ["high_performer", "strong_academic_low_placement", "declining_attendance", "academic_support", "improving",
              "incomplete", "typical"]
SYSTEM = Principal("seed", "seed", "Data setup")

# Display texts carried by seeded records (chosen without extra random draws so the dataset is unchanged).
FEEDBACK_COMMENTS = ["Would like more practice problems before internal tests.", "Workload is heavy this month.",
                     "Lab sessions are helpful.", "Need guidance on choosing electives.", "More mock interviews would help."]
CERT_ISSUERS = {"NPTEL Python": "NPTEL", "Cloud Fundamentals": "Cloud training partner", "Data Analytics Basics": "Skills portal"}
INTERVENTION_DETAIL = "Plan agreed with the student; progress reviewed at each check-in."
OLD_TEXTS = {"comment": "Synthetic feedback comment.", "issuer": "Synthetic issuer", "detail": "Synthetic example intervention."}

# Demo personas (local-demo mode signs in as these; in Cognito mode infra/setup_accounts.py creates them).
PERSONAS = [
    {"username": "admin.priya", "display_name": "Priya Raman (College Administrator)", "roles": [{"role": "college_admin"}]},
    {"username": "hod.meenakshi", "display_name": "Dr Meenakshi Iyer (HOD, CSE)", "roles": [{"role": "hod", "department": "CSE"}]},
    {"username": "mentor.arjun", "display_name": "Prof Arjun Mehta (Mentor, CSE)", "roles": [{"role": "mentor"}],
     "subjects": [("CSE", 3, "Operating Systems"), ("CSE", 3, "Database Systems")], "mentees": ("CSE", 3)},
    {"username": "mentor.kavitha", "display_name": "Prof Kavitha Rao (Mentor, ECE)", "roles": [{"role": "mentor"}],
     "subjects": [("ECE", 2, "Signals and Systems")], "mentees": ("ECE", 2)},
    {"username": "placement.rohit", "display_name": "Rohit Verma (Placement Officer)", "roles": [{"role": "placement_officer"}]},
    {"username": "activity.sara", "display_name": "Sara Thomas (Activity Coordinator)", "roles": [{"role": "activity_coordinator"}]},
    {"username": "sysadmin.dev", "display_name": "Dev Malhotra (System Administrator)", "roles": [{"role": "system_admin"}]},
    {"username": "student.cse", "display_name": "Student (CSE year 3)", "roles": [{"role": "student", "dataset": DS}],
     "student": ("CSE", 3)},
    {"username": "student.ece", "display_name": "Student (ECE year 1)", "roles": [{"role": "student", "dataset": DS}],
     "student": ("ECE", 1)},
]


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def generate() -> dict:
    """Pure function: the full synthetic dataset as plain dicts."""
    rng = random.Random(SEED)
    cur = curriculum()
    periods = cur["reporting_periods"]
    students, records, interventions = [], [], []
    for d_i, dept in enumerate(DEPTS):
        for j in range(50):
            year = 1 if j < 13 else 2 if j < 26 else 3 if j < 38 else 4
            seq = j - (0, 13, 26, 38)[year - 1] + 1
            sid = f"{dept}{(2026 - year + 1) % 100:02d}{seq:03d}"
            arche = _archetype(rng, year)
            students.append({"student_id": sid, "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "department": dept,
                             "year": year, "programme": cur["programme"], "email": f"{sid.lower()}@example.edu",
                             "status": "active", "archetype": arche})
    for s in students:
        records += _records_for(rng, s, periods, cur)
        interventions += _interventions_for(s, periods)
    return {"students": students, "records": records, "interventions": interventions}


def _archetype(rng: random.Random, year: int) -> str:
    r = rng.random()
    if year >= 3 and r < 0.16:
        return "strong_academic_low_placement"
    if r < 0.28:
        return "high_performer"
    if r < 0.37:
        return "declining_attendance"
    if r < 0.48:
        return "academic_support"
    if r < 0.60:
        return "improving"
    if r < 0.69:
        return "incomplete"
    return "typical"


def _records_for(rng, s, periods, cur) -> list[dict]:
    a = s["archetype"]
    g = rng.gauss
    ability = {"high_performer": 1.3, "strong_academic_low_placement": 1.0, "academic_support": -1.3,
               "improving": -1.0, "declining_attendance": 0.2}.get(a, g(0.35, 0.55))
    skilled = a == "academic_support" and rng.random() < 0.45  # strong practical skills despite weak grades
    subjects = cur["departments"][s["department"]]["subjects"][str(s["year"])]
    out = []

    def rec(category, period, **data):
        out.append({"student_id": s["student_id"], "category": category, "period": period, **data})

    for i, p in enumerate(periods):
        progress = 0.0
        if a == "improving" and i >= 2:
            progress = 0.55 * (i - 1)  # improves after the May intervention
        level = ability + progress
        att = 84 + 6 * level + g(0, 3)
        if a == "declining_attendance" and i >= 2:
            att -= 4.5 * (i - 1)
        if a == "high_performer":
            att = 93 + g(0, 2)
        for subj in subjects:
            held = rng.randint(14, 20)
            rec("attendance", p, subject=subj, classes_held=held,
                classes_attended=int(round(held * clip(att + g(0, 4), 30, 100) / 100)))
            pct = clip(62 + 14 * level + g(0, 6) - (6.5 * (i - 1) if a == "declining_attendance" and i >= 2 else 0), 10, 98)
            rec("marks", p, subject=subj, assessment="Monthly test", score=round(pct / 2, 1), max_score=50)
        if a != "incomplete":
            due = rng.randint(3, 6)
            comp = clip(0.75 + 0.15 * level + g(0, 0.08), 0.1, 1.0)
            rec("lms", p, assignments_due=due, assignments_submitted=min(due, int(round(due * comp))),
                logins=max(0, int(14 + 6 * level + g(0, 3))))
        if p in (periods[0], periods[3]):
            base = clip(6.9 + 0.9 * ability + (0.6 if a == "improving" and i >= 3 else 0) + g(0, 0.2), 4.5, 9.8)
            backlogs = 0 if base >= 6.4 else (2 if base < 5.6 else 1)
            if a == "improving" and i >= 3:
                backlogs = max(0, backlogs - 1)
            rec("academic_result", p, semester=2 * s["year"] - (1 if i < 3 else 0), sgpa=round(base + g(0, 0.2), 2),
                cgpa=round(base, 2), backlogs=backlogs)
        if p in (periods[1], periods[4]) and (a != "incomplete" or s["year"] <= 2):
            if a == "incomplete" and rng.random() < 0.5:
                pass  # missed the skills assessment
            else:
                rec("skills", p, technical=round(clip(60 + 11 * ability + g(0, 6) + (15 if a == "strong_academic_low_placement" else 0)
                                                     + (38 if skilled else 0), 15, 98), 1),
                    communication=round(clip(58 + 8 * ability + g(0, 7) - (14 if a == "strong_academic_low_placement" else 0)
                                             + (25 if skilled else 0), 15, 98), 1))
        if s["year"] >= 3 and p in (periods[1], periods[4]) and a != "incomplete" and not (a == "typical" and rng.random() < 0.12):
            weak = a == "strong_academic_low_placement"
            rec("placement_assessment", p, assessment_type="aptitude",
                score=round(clip((40 if weak else 58 + 10 * ability) + g(0, 6), 5, 99), 1))
            rec("placement_assessment", p, assessment_type="coding",
                score=round(clip((30 if weak else 55 + 12 * ability) + g(0, 7), 0, 99), 1))
            rec("placement_assessment", p, assessment_type="mock_interview",
                score=round(clip((2.1 if weak else 3.1 + 0.5 * ability) + g(0, 0.3), 1, 5), 1))
        if p in (periods[2], periods[5]) and rng.random() < 0.85:
            stress = int(clip(round(3 - 0.5 * ability + g(0, 0.8) + (1 if a == "declining_attendance" and i >= 3 else 0)), 1, 5))
            rec("feedback", p, satisfaction=int(clip(round(3.6 + 0.4 * ability + g(0, 0.7)), 1, 5)), stress=stress,
                support_needed=["academic"] if a in ("academic_support", "improving") else (["career"] if a == "strong_academic_low_placement" else []),
                comment=FEEDBACK_COMMENTS[(i + p.count("0")) % len(FEEDBACK_COMMENTS)])
    n_events = max(0, int(round(2 + 1.5 * ability + g(0, 1)))) if a != "incomplete" else 0
    for k in range(n_events):
        rec("engagement", periods[rng.randint(0, 5)], activity_type="event", name=rng.choice(
            ["Tech Fest", "Guest Lecture Series", "Industry Visit", "Hackathon Volunteer", "Cultural Fest", "Blood Donation Drive"]) + f" {k + 1}",
            role="Participant", verification="verified")
    if a in ("high_performer", "typical") and rng.random() < 0.6:
        rec("engagement", periods[0], activity_type="club", name=rng.choice(["Coding Club", "Robotics Club", "Literary Society"]),
            role="Member", verification="verified")
    if a == "high_performer" or rng.random() < 0.25:
        rec("engagement", periods[rng.randint(1, 5)], activity_type="project", name="Mini project: campus app", role="Team member",
            verification="verified")
    if a != "incomplete" and rng.random() < 0.5:
        cp = periods[rng.randint(0, 5)]  # same draw order as before: period, name, verification
        cert = rng.choice(["NPTEL Python", "Cloud Fundamentals", "Data Analytics Basics"])
        rec("certification", cp, name=cert,
            issuer=CERT_ISSUERS[cert], verification="verified" if rng.random() < 0.7 else "pending")
    return out


def _interventions_for(s, periods) -> list[dict]:
    a, sid = s["archetype"], s["student_id"]
    if a == "improving":
        return [{"student_id": sid, "intervention_id": f"SEED-{sid}-1", "title": "Academic support plan", "category": "academic",
                 "recommendation_key": "academic_support_plan", "owner": "mentor", "status": "Completed",
                 "due_date": "2026-06-15", "review_date": "2026-08-15", "baseline_period": periods[1],
                 "outcome": {"result": "improved", "note": "Attendance and marks recovered; continuing fortnightly check-ins."}}]
    if a == "declining_attendance":
        return [{"student_id": sid, "intervention_id": f"SEED-{sid}-1", "title": "Attendance recovery plan", "category": "attendance",
                 "recommendation_key": "attendance_recovery", "owner": "mentor", "status": "Open",
                 "due_date": "2026-09-25", "review_date": "2026-10-20", "baseline_period": periods[5], "outcome": None}]
    if a == "strong_academic_low_placement":
        return [{"student_id": sid, "intervention_id": f"SEED-{sid}-1", "title": "Coding bootcamp", "category": "placement_training",
                 "recommendation_key": "coding_bootcamp", "owner": "placement", "status": "In Progress",
                 "due_date": "2026-10-30", "review_date": "2026-11-30", "baseline_period": periods[4], "outcome": None}]
    return []


# --------------------------------------------------------------------------- writing
def _seed_cond():
    # Write if absent, or if still owned by an older seed. Never overwrite anything a person changed.
    return C.any(C.not_exists(), C.all(C.eq("source", "seed"), C.eq("updated_by", "seed"), C.lt("seed_version", SEED_VERSION)))


def _put(item: dict, stats: dict) -> None:
    try:
        db.table().put({**item, "source": "seed", "seed_version": SEED_VERSION, "dataset_version": DATASET_VERSION,
                        "synthetic": True}, _seed_cond())
        stats["written"] += 1
    except ConditionFailed:
        stats["skipped"] += 1


def persona_roles(per: dict, student_ids: dict) -> list[dict]:
    """Role assignments for a demo persona; student personas point at the first student of their class."""
    return [{**r, "student_id": student_ids[per["student"]]} if r["role"] == "student" else r for r in per["roles"]]


def first_students() -> dict:
    out: dict = {}
    for s in generate()["students"]:
        out.setdefault((s["department"], s["year"]), s["student_id"])
    return out


def assign_persona_roles(subs: dict) -> int:
    """Give each persona account (username -> sub) its demo roles, unless it already has roles."""
    from . import accounts
    ids, n = first_students(), 0
    for per in PERSONAS:
        sub = subs.get(per["username"])
        prof = db.table().get(f"USER#{sub}", "PROFILE") if sub else None
        if prof and not prof.get("roles"):
            accounts.set_roles(SYSTEM, sub, persona_roles(per, ids), prof["version"], system=True)
            n += 1
    return n


def _ensure_accounts(stats: dict, student_ids: dict) -> dict:
    """Local demo mode only: fixed 'local-' subs, no passwords."""
    from . import accounts
    subs = {}
    for per in PERSONAS:
        sub = f"local-{per['username']}"
        if not db.table().get(f"USER#{sub}", "PROFILE"):
            accounts.create_user(SYSTEM, per["username"], per["display_name"], sub=sub, system=True)
        subs[per["username"]] = sub
    stats["accounts"] += assign_persona_roles(subs)
    return subs


def _persona_subs(local: bool) -> dict:
    """Persona username -> sub. Local accounts use a fixed sub; Cognito accounts are looked up."""
    if local:
        return {p["username"]: f"local-{p['username']}" for p in PERSONAS}
    users, _ = db.table().query("USERS", index="gsi2", limit=500)
    by_name = {u["username"]: u["sub"] for u in users}
    return {p["username"]: by_name[p["username"]] for p in PERSONAS if p["username"] in by_name}


def _plan(data: dict, subs: dict, ts: str) -> tuple[dict, dict]:
    """Every seed-owned item, grouped by partition, plus student -> (mentor sub, mentor name)."""
    by_class: dict = {}
    for s in data["students"]:
        by_class.setdefault((s["department"], s["year"]), []).append(s["student_id"])
    mentor_for = {}
    for per in PERSONAS:
        if per.get("mentees") and per["username"] in subs:
            for sid in by_class[per["mentees"]][:12]:
                mentor_for[sid] = (subs[per["username"]], per["display_name"])
    items: dict = {}

    def add(item):
        items.setdefault(item["pk"], {})[item["sk"]] = item

    masters = {s["student_id"]: s for s in data["students"]}
    for s in data["students"]:
        sid = s["student_id"]
        master = {k: v for k, v in s.items() if k != "archetype"}
        m_sub, m_name = mentor_for.get(sid, (None, None))
        add({"pk": f"STU#{DS}#{sid}", "sk": "MASTER", **master, "dataset": DS, "mentor_sub": m_sub, "mentor_name": m_name,
             "seed_profile": s["archetype"], "created_at": ts, "created_by": "seed", "updated_at": ts, "updated_by": "seed",
             "version": 1})
    for r in data["records"]:
        cat = CATEGORIES[r["category"]]
        payload = {f.name: r.get(f.name) for f in cat.fields}
        m = masters[r["student_id"]]
        item = {"pk": f"STU#{DS}#{r['student_id']}", "sk": f"REC#{r['category']}#{r['period']}#{cat.subkey_of(payload)}",
                "student_id": r["student_id"], "dataset": DS, "department": m["department"], "year": m["year"],
                "category": r["category"], "period": r["period"], "subkey": cat.subkey_of(payload), **payload,
                "created_at": ts, "created_by": "seed", "updated_at": ts, "updated_by": "seed", "version": 1}
        if cat.verification:
            item["verification"] = r.get("verification", "verified")
            if item["verification"] == "pending":
                item["gsi1pk"], item["gsi1sk"] = f"VERIFY#{DS}", f"{ts}#{r['student_id']}#{item['sk']}"
        add(item)
    placement = subs.get("placement.rohit")
    for iv in data["interventions"]:
        m = masters[iv["student_id"]]
        owner = mentor_for.get(iv["student_id"], (None, None))[0] if iv["owner"] == "mentor" else placement
        owner = owner or subs.get("admin.priya") or "seed"
        item = {"pk": f"STU#{DS}#{iv['student_id']}", "sk": f"INT#{iv['intervention_id']}", "intervention_id": iv["intervention_id"],
                "student_id": iv["student_id"], "student_name": m["name"], "dataset": DS, "department": m["department"],
                "year": m["year"], "title": iv["title"], "category": iv["category"], "recommendation_key": iv["recommendation_key"],
                "evidence": [], "detail": INTERVENTION_DETAIL, "owner_sub": owner,
                "owner_name": next((p["display_name"] for p in PERSONAS if subs.get(p["username"]) == owner), "Demo owner"),
                "due_date": iv["due_date"], "review_date": iv["review_date"], "status": iv["status"],
                "outcome": iv["outcome"], "reviewed_by": "seed", "created_by": "seed", "created_by_name": "seed",
                "created_at": ts, "updated_at": ts, "updated_by": "seed", "version": 1,
                "baseline": {"period": iv["baseline_period"]}}
        item.update({"gsi1pk": f"DEPTINT#{DS}#{m['department']}", "gsi1sk": f"{iv['status']}#{iv['due_date']}#{iv['intervention_id']}",
                     "gsi2pk": f"OWNER#{owner}", "gsi2sk": f"{iv['status']}#{iv['due_date']}#{iv['intervention_id']}"})
        add(item)
    return items, mentor_for


def _assignments(subs: dict, mentor_for: dict, ts: str) -> None:
    t = db.table()
    for sid, (m_sub, _) in mentor_for.items():
        t.put({"pk": f"USER#{m_sub}", "sk": f"MENTEE#{DS}#{sid}", "dataset": DS, "student_id": sid,
               "assigned_by": "seed", "assigned_at": ts})
    for per in PERSONAS:
        if per.get("subjects") and per["username"] in subs:
            for dept, year, subj in per["subjects"]:
                t.put({"pk": f"USER#{subs[per['username']]}", "sk": f"SUBJ#{dept}#{year}#{subj}",
                       "gsi1pk": f"SUBJECT#{dept}#{year}#{subj}", "gsi1sk": subs[per["username"]], "department": dept,
                       "year": year, "subject": subj, "assigned_by": "seed", "assigned_at": ts})


def run(with_accounts: bool = True) -> dict:
    data = generate()
    ts = db.now()
    stats = {"written": 0, "skipped": 0, "accounts": 0}
    subs = _persona_subs(with_accounts)
    plan, mentor_for = _plan(data, subs, ts)
    for s in data["students"]:  # masters first: accounts and assignments refer to them
        _put(plan[f"STU#{DS}#{s['student_id']}"]["MASTER"], stats)
    if with_accounts:
        by_class: dict = {}
        for s in data["students"]:
            by_class.setdefault((s["department"], s["year"]), []).append(s["student_id"])
        _ensure_accounts(stats, {k: v[0] for k, v in by_class.items()})
    _assignments(subs, mentor_for, ts)
    for part in plan.values():
        for sk, item in part.items():
            if sk != "MASTER":
                _put(item, stats)
    # Recalculate every student, then fill intervention baselines/outcomes from computed history.
    for s in data["students"]:
        insights.recompute_safely(DS, s["student_id"])
    for iv in data["interventions"]:
        _fill_baseline(iv)
    for s in data["students"]:
        if s["archetype"] == "improving":
            insights.recompute_safely(DS, s["student_id"])
    db.table().put({"pk": f"DATASET#{DS}", "sk": "META", "dataset": DS, "seed": SEED, "seed_version": SEED_VERSION,
                    "dataset_version": DATASET_VERSION, "students": len(data["students"]), "records": len(data["records"]),
                    "seeded_at": ts, "synthetic": True})
    stats.update(students=len(data["students"]), records=len(data["records"]), interventions=len(data["interventions"]))
    return stats


def _fill_baseline(iv: dict) -> None:
    t = db.table()
    pk = f"STU#{DS}#{iv['student_id']}"
    item = t.get(pk, f"INT#{iv['intervention_id']}")
    if not item or item.get("source") != "seed" or item.get("baseline", {}).get("score") is not None:
        return
    sc = t.get(pk, f"SCORE#{iv['baseline_period']}") or {}
    ins = t.get(pk, "INSIGHT") or {}
    item["baseline"] = {"period": iv["baseline_period"], "score": sc.get("score"), "status": sc.get("status"),
                        "profile": sc.get("profile"), "scoring_version": sc.get("scoring_version")}
    if item.get("outcome"):
        item["outcome"] = {**item["outcome"], "recorded_by": "seed", "recorded_at": ins.get("calculated_at"),
                           "after": {"period": ins.get("period"), "score": ins.get("score"), "status": ins.get("status"),
                                     "profile": ins.get("profile"), "scoring_version": ins.get("scoring_version")}}
    t.put(item)


DERIVED = ("INSIGHT", "INSIGHTD", "STALE")


def reset_demo(principal, confirmation: str, cursor: int = 0, budget_seconds: float = 10.0) -> dict:
    """Restore the demo dataset to its generated state. Bounded and resumable.

    Only items people created or changed are deleted or restored; untouched seed items are not rewritten,
    so a reset costs writes in proportion to what changed. Call again with the returned cursor until done.
    Real records are never read or written.
    """
    from . import audit
    from .policy import require
    require(principal, "dataset", "reset_demo")
    if confirmation != "RESET DEMO":
        from .categories import ValidationError
        raise ValidationError({"confirmation": "type RESET DEMO to confirm"})
    t = db.table()
    data = generate()
    ts = db.now()
    subs = _persona_subs(local=False) or _persona_subs(local=True)
    plan, mentor_for = _plan(data, subs, ts)
    present = sorted({i["student_id"] for d in curriculum()["departments"] for i in t.query(f"DEPT#{DS}#{d}", index="gsi1")[0]}
                     | {s["student_id"] for s in data["students"]})
    removed = restored = 0
    stats = {"written": 0, "skipped": 0}
    ivs = {iv["student_id"]: [] for iv in data["interventions"]}
    for iv in data["interventions"]:
        ivs[iv["student_id"]].append(iv)
    i = cursor
    start = time.time()
    while i < len(present) and (i == cursor or time.time() - start < budget_seconds):  # always progress
        sid = present[i]
        pk = f"STU#{DS}#{sid}"
        want = plan.get(pk, {})
        items, _ = t.query(pk)
        have = {it["sk"]: it for it in items}
        changed = False
        for sk, it in have.items():
            seed_owned = it.get("source") == "seed" and it.get("updated_by") == "seed"
            derived = sk in DERIVED or sk.startswith("SCORE#")
            if sk in want and seed_owned:
                continue
            if derived and want:
                continue  # recalculated below
            t.delete(pk, sk)
            removed += 1
            changed = True
        for sk, it in want.items():
            if sk not in have or not (have[sk].get("source") == "seed" and have[sk].get("updated_by") == "seed"):
                t.put({**it, "source": "seed", "seed_version": SEED_VERSION, "dataset_version": DATASET_VERSION, "synthetic": True})
                restored += 1
                changed = True
        if changed and want:
            insights.recompute_safely(DS, sid)
            for iv in ivs.get(sid, []):
                _fill_baseline(iv)
        i += 1
    done = i >= len(present)
    if done:
        users, _ = t.query("USERS", index="gsi2", limit=500)
        for u in users:
            for mm in t.query(f"USER#{u['sub']}", f"MENTEE#{DS}#")[0]:
                if mentor_for.get(mm["student_id"], (None,))[0] != u["sub"]:
                    t.delete(mm["pk"], mm["sk"])
                    removed += 1
        _assignments(subs, mentor_for, ts)
        insights.invalidate_listing()
        audit.log(principal, "dataset.reset", "dataset", DS, {"removed": removed, "restored": restored}, dataset=DS)
    return {"done": done, "cursor": None if done else i, "students": len(present), "checked": i - cursor,
            "removed": removed, "restored": restored}


def relabel() -> int:
    """One-off: replace older seeded display texts in place (no score changes). Returns items updated."""
    t, n = db.table(), 0
    by_sid = {}
    for r in generate()["records"]:
        if r["category"] in ("feedback", "certification"):
            by_sid.setdefault(r["student_id"], {})[(r["category"], r["period"], r.get("name"))] = r
    for sid in sorted({s["student_id"] for s in generate()["students"]}):
        items, _ = t.query(f"STU#{DS}#{sid}")
        for it in items:
            new = None
            if it.get("comment") == OLD_TEXTS["comment"]:
                g = by_sid.get(sid, {}).get(("feedback", it["period"], None))
                new = {"comment": g["comment"] if g else FEEDBACK_COMMENTS[0]}
            elif it.get("issuer") == OLD_TEXTS["issuer"]:
                new = {"issuer": CERT_ISSUERS.get(it.get("name"), "Training provider")}
            elif it.get("detail") == OLD_TEXTS["detail"]:
                new = {"detail": INTERVENTION_DETAIL}
            if new:
                try:
                    t.put({**it, **new, "version": it.get("version", 1) + 1}, C.version(it.get("version", 1)))
                    n += 1
                except ConditionFailed:
                    pass  # changed meanwhile by a person; leave it
    for per in PERSONAS:
        for u in t.query("USERS", index="gsi2", limit=500)[0]:
            if u["username"] == per["username"] and u.get("display_name", "").startswith("Demo student"):
                t.put({**u, "display_name": per["display_name"], "version": u["version"] + 1}, C.version(u["version"]))
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-accounts", action="store_true", help="don't create the demo sign-in accounts")
    ap.add_argument("--relabel", action="store_true", help="update older seeded display texts in place, then exit")
    a = ap.parse_args()
    if a.relabel:
        print(f"Updated {relabel()} item(s).")
        return
    from .settings import settings
    if settings().auth_mode == "cognito" and not a.no_accounts:
        raise SystemExit("In Cognito mode create accounts with infra/setup_accounts.py, then run with --no-accounts.")
    s = run(with_accounts=not a.no_accounts)
    print(f"Demo dataset {DATASET_VERSION} (seed {SEED}, generator v{SEED_VERSION}): {s['students']} students, "
          f"{s['records']} records, {s['interventions']} interventions; {s['written']} written, {s['skipped']} kept unchanged, "
          f"{s['accounts']} accounts set up.")


if __name__ == "__main__":
    main()
