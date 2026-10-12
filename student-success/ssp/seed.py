"""Seed a deployment with synthetic data and demo users.

    python -m ssp.seed                      # local mode (password Demo@2026 for all demo users)
    SSP_MODE=aws ... python -m ssp.seed     # AWS: random passwords, written to --passwords-file

Data goes through the normal import pipeline (validate -> commit), so seeding
exercises exactly what an administrator's upload does.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import secrets
import shutil
import string
from datetime import date, timedelta

from . import config, engine, importer, interventions, records, settings, synth
from .auth import Principal, directory

LOCAL_PASSWORD = "Demo@2026"
SYSTEM = Principal("seed", "Initial data load", "admin")
HOD_NAMES = {"CSE": "Dr. Meenakshi Iyer", "IT": "Dr. Rajesh Kulkarni", "ECE": "Dr. Farah Khan", "MECH": "Dr. Suresh Naidu",
             "CIVIL": "Dr. Anita Bose", "MCA": "Dr. Joseph D'Souza"}
FACULTY = ["Prof. Kavitha Rao", "Prof. Arjun Mehta", "Prof. Lakshmi Pillai", "Prof. Vikram Singh", "Prof. Neha Gupta",
           "Prof. Sanjay Hegde", "Prof. Divya Menon", "Prof. Rahul Das", "Prof. Ayesha Siddiqui"]


def _password() -> str:
    if settings.MODE == "local":
        return LOCAL_PASSWORD
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(14))
    return core + secrets.choice("!@#$%^*") + secrets.choice(string.digits) + secrets.choice(string.ascii_uppercase)


def _create(users: list[dict], creds: list[dict]) -> None:
    existing = {u["username"] for u in directory.list()}
    for u in users:
        if u["username"] in existing:
            continue
        pw = _password()
        directory.create(u["username"], u["name"], u["role"], u.get("dept", ""), u.get("student_id", ""), password=pw)
        creds.append({"username": u["username"], "role": u["role"], "password": pw, "name": u["name"]})


def load_data() -> None:
    m = json.loads((settings.SAMPLE_DIR / "manifest.json").read_text())
    for f in m["load_order"]:
        p = settings.SAMPLE_DIR / f["file"]
        s = importer.validate(f["category"], p.name, p.read_bytes(), f["period"], SYSTEM)
        if s["status"] != "validated":
            raise SystemExit(f"Seed file {p.name} failed validation: {s['file_errors']}")
        importer.commit(s["id"], SYSTEM, recalc=False)
        print(f"  imported {p.name:<42} {s['accepted']:>6} rows")


def seed_interventions(rng: random.Random) -> int:
    cfg = config.active()
    roster = records.roster()
    even = engine.snapshot("2026-EVEN")["students"]
    odd = engine.snapshot("2026-ODD")["students"]
    names = {u["username"]: u["name"] for u in directory.list()}
    n = 0

    def mentor_of(sid):
        u = roster[sid]["mentor_username"]
        return Principal(u, names.get(u, u), "mentor")

    placement = Principal("placement", names.get("placement", "Placement Officer"), "placement")

    # Previous review (Feb 2026): actions that have run their course
    hi_even = [s for s in even.values() if s["risk"]["academic"]["level"] == "High" and s["actions"]]
    for s in rng.sample(hi_even, min(45, len(hi_even))):
        sid = s["student_id"]
        a = s["actions"][0]
        who = mentor_of(sid)
        created = f"2026-02-{rng.randint(16, 27):02d}T10:{rng.randint(10, 59)}:00+00:00"
        item = interventions.create(who, roster[sid], {**s, "period": "2026-EVEN"},
                                    {"action_id": a["action_id"], "title": a["title"], "detail": a["detail"], "risk": a["risk"],
                                     "rules": a["rules"], "owner": who.username, "owner_role": "mentor",
                                     "due_days": a["due_days"], "review_days": a["review_days"],
                                     "note": "Discussed at the February review meeting."}, created_at=created)
        n += 1
        later = odd.get(sid)
        upd1 = (date.fromisoformat(created[:10]) + timedelta(days=rng.randint(3, 9))).isoformat() + "T09:00:00+00:00"
        interventions.update(who, item["id"], {"status": "In Progress", "note": "Met the student; plan agreed."}, "full", at=upd1)
        if rng.random() < 0.8 and later:
            delta = (later["score"]["score"] or 0) - (s["score"]["score"] or 0)
            outcome = "Improved" if delta >= 3 else "Worse" if delta <= -3 else "No change"
            done = (date.fromisoformat(created[:10]) + timedelta(days=rng.randint(35, 60))).isoformat() + "T15:00:00+00:00"
            interventions.update(who, item["id"], {"status": "Completed", "outcome": outcome,
                                                   "outcome_note": f"Score moved {delta:+.1f} by the next review.",
                                                   "note": "Closed after the April review."}, "full", at=done)

    # Current review (last few weeks): open work, some of it overdue
    today = date.today()
    hi_odd = [s for s in odd.values() if s["risk"]["academic"]["level"] == "High" and s["actions"]]
    for s in rng.sample(hi_odd, min(40, len(hi_odd))):
        sid = s["student_id"]
        a = next((x for x in s["actions"] if x["owner_role"] == "mentor"), None)
        if not a:
            continue
        who = mentor_of(sid)
        created = (today - timedelta(days=rng.randint(4, 26))).isoformat() + "T11:00:00+00:00"
        item = interventions.create(who, roster[sid], {**s, "period": "2026-ODD"},
                                    {"action_id": a["action_id"], "title": a["title"], "detail": a["detail"], "risk": a["risk"],
                                     "rules": a["rules"], "owner": who.username, "owner_role": "mentor",
                                     "due_days": a["due_days"], "review_days": a["review_days"]}, created_at=created)
        n += 1
        if rng.random() < 0.5:
            interventions.update(who, item["id"], {"status": "In Progress", "note": "First conversation done."}, "full",
                                 at=(date.fromisoformat(created[:10]) + timedelta(days=2)).isoformat() + "T10:00:00+00:00")
    pl = [s for s in odd.values() if s["risk"]["placement"]["level"] in ("High", "Insufficient data") and s["actions"]]
    for s in rng.sample(pl, min(25, len(pl))):
        sid = s["student_id"]
        a = next((x for x in s["actions"] if x["owner_role"] == "placement"), None)
        if not a:
            continue
        created = (today - timedelta(days=rng.randint(3, 30))).isoformat() + "T12:00:00+00:00"
        interventions.create(placement, roster[sid], {**s, "period": "2026-ODD"},
                             {"action_id": a["action_id"], "title": a["title"], "detail": a["detail"], "risk": "placement",
                              "rules": a["rules"], "owner": "placement", "owner_role": "placement",
                              "due_days": a["due_days"], "review_days": a["review_days"]}, created_at=created)
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="local mode: wipe local data first")
    ap.add_argument("--passwords-file", default=str(settings.ROOT / "deploy" / ".demo-credentials.json"))
    a = ap.parse_args()
    if a.reset and settings.MODE == "local" and settings.LOCAL_DIR.exists():
        shutil.rmtree(settings.LOCAL_DIR)
    if not (settings.SAMPLE_DIR / "manifest.json").exists():
        synth.generate(settings.SAMPLE_DIR)
    cfg = config.active()
    print(f"Scoring rules: version {cfg['version']}")

    creds: list[dict] = []
    with (settings.SAMPLE_DIR / "current" / "01_roster.csv").open() as fh:
        roster_rows = list(csv.DictReader(fh))
    mentors = sorted({r["mentor_username"] for r in roster_rows})
    users = [{"username": "admin", "name": "Priya Raman (Academic Office)", "role": "admin"},
             {"username": "placement", "name": "Rohit Verma (Training & Placement)", "role": "placement"}]
    users += [{"username": f"hod.{d.lower()}", "name": n, "role": "hod", "dept": d} for d, n in HOD_NAMES.items()]
    users += [{"username": m, "name": FACULTY[i % len(FACULTY)] + f" ({m.split('.')[1].rstrip('0123456789').upper()})",
               "role": "mentor"} for i, m in enumerate(mentors)]
    _create(users, creds)

    if not records.meta().get("categories"):
        print("Importing sample data:")
        load_data()
        run = engine.recalculate(SYSTEM, "initial data load")
        print(f"Scored: {run['students']}")
        print(f"Seeded {seed_interventions(random.Random(11))} interventions")
    odd = engine.snapshot(cfg["current_period"])["students"]
    picks = [next(s for s in sorted(odd.values(), key=lambda s: s["student_id"]) if s["risk"]["academic"]["level"] == "High"),
             next(s for s in sorted(odd.values(), key=lambda s: s["student_id"]) if s["score"]["band"] == "Thriving")]
    roster = records.roster()
    _create([{"username": p["student_id"].lower(), "name": roster[p["student_id"]]["name"], "role": "student",
              "student_id": p["student_id"]} for p in picks], creds)

    if creds and settings.MODE == "aws":
        from pathlib import Path
        out = Path(a.passwords_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(out.read_text()) if out.exists() else []
        out.write_text(json.dumps(old + creds, indent=2))
        out.chmod(0o600)
        print(f"Created {len(creds)} users; passwords saved to {out} (not committed to git).")
    elif creds:
        print(f"Created {len(creds)} users. Local demo password for all: {LOCAL_PASSWORD}")
    print("Demo sign-ins: admin, hod.cse, mentor.cse1, placement, " + ", ".join(p["student_id"].lower() for p in picks))


if __name__ == "__main__":
    main()
