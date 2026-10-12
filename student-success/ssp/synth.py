"""Synthetic campus generator. Writes upload-ready CSV/XLSX files (clearly
labelled synthetic; no real student data) in the exact template formats.

Every table is driven by hidden student traits (ability, diligence,
engagement, career focus, wellbeing), so signals are correlated the way they
are on a real campus. Exports keep realistic quirks: mixed ID spellings,
department aliases, "72%" strings, Excel files.

Outputs (data/sample/):
  current/   roster + two review periods (2026-EVEN, 2026-ODD) for 660 students
  demo/      files for the live demo: a file with validation errors, an LMS
             update that changes risk flags, an Excel skills file
  history/   the 2022 B.Tech batch at the start of final year + graduation
             outcomes, used only to validate the score offline
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .schemas import SCHEMAS

DEPTS = ["CSE", "IT", "ECE", "MECH", "CIVIL"]
DEPT_LABELS = {"CSE": ["CSE", "Computer Science", "C.S.E"], "IT": ["IT", "Information Technology"],
               "ECE": ["ECE", "Electronics & Communication"], "MECH": ["MECH", "Mechanical Engg"],
               "CIVIL": ["CIVIL", "Civil Engg"], "MCA": ["MCA"]}
SUBJECTS = {
    "CSE": ["Data Structures", "Operating Systems", "DBMS", "Computer Networks", "Theory of Computation", "Software Engg",
            "Machine Learning", "Compiler Design", "Cloud Computing", "Distributed Systems", "Cryptography", "Web Technologies"],
    "IT": ["Data Structures", "Web Technologies", "DBMS", "Cloud Computing", "Information Security", "Software Engg",
           "Data Mining", "Mobile Computing", "DevOps", "Big Data", "IoT Systems", "UI Design"],
    "ECE": ["Signals & Systems", "Digital Electronics", "Analog Circuits", "Microprocessors", "Communication Systems",
            "Control Systems", "VLSI Design", "Embedded Systems", "DSP", "Antennas", "Wireless Networks", "Optical Comm"],
    "MECH": ["Thermodynamics", "Fluid Mechanics", "Machine Design", "Manufacturing Processes", "Heat Transfer", "Kinematics",
             "CAD/CAM", "Dynamics of Machinery", "Metrology", "Automobile Engg", "Robotics", "Finite Element Analysis"],
    "CIVIL": ["Structural Analysis", "Surveying", "Geotechnical Engg", "Fluid Mechanics", "Concrete Technology", "Hydrology",
              "Transportation Engg", "Steel Structures", "Environmental Engg", "Estimation & Costing", "Foundation Engg", "GIS"],
    "MCA": ["Advanced Java", "Data Structures", "DBMS", "Python Programming", "Software Testing", "Computer Networks",
            "Machine Learning", "Cloud Computing", "Mobile App Development", "Data Analytics", "Cyber Security", "Project Mgmt"],
}
CODING_BONUS = {"CSE": 8, "IT": 6, "ECE": 0, "MECH": -6, "CIVIL": -8, "MCA": 4}
FIRST = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan", "Ananya", "Diya",
         "Aadhya", "Saanvi", "Pari", "Kavya", "Meera", "Isha", "Riya", "Nisha", "Rahul", "Karthik", "Siddharth", "Varun",
         "Pranav", "Lakshmi", "Divya", "Sneha", "Pooja", "Tanvi", "Harsh", "Yash", "Manav", "Nikhil", "Abhinav", "Shreya",
         "Neha", "Priya", "Aditi", "Swathi", "Farhan", "Zoya", "Gurpreet", "Joseph", "Fatima", "Tenzin", "Anjali", "Deepak"]
LAST = ["Sharma", "Verma", "Reddy", "Iyer", "Nair", "Patel", "Gupta", "Singh", "Rao", "Kumar", "Menon", "Joshi", "Das",
        "Mehta", "Chopra", "Bose", "Pillai", "Kulkarni", "Agarwal", "Naidu", "Khan", "D'Souza", "Hegde", "Banerjee"]
CONCERN = ["Mentions financial difficulty at home; working part-time evenings.",
           "Reported health issues this term; missed several classes.",
           "Commutes over 2 hours daily; often late for first period.",
           "Seems withdrawn in class and avoids mentor meetings.",
           "Family responsibilities are affecting study time.",
           "Struggling to cope with workload; asked about dropping a subject."]
NEUTRAL = ["Regular in mentoring sessions; no concerns raised.", "Attends regularly but participation is limited.",
           "Steady progress; needs encouragement to take up projects."]
POSITIVE = ["Active in class discussions and helps peers.", "Shows leadership in project work; highly motivated.",
            "Pursuing extra online courses; very curious."]
EVENTS = ["Tech Fest Volunteer", "Guest Lecture", "Cultural Fest", "Industry Visit", "Workshop: IoT", "Workshop: GenAI",
          "Blood Donation Drive", "NSS Camp", "Sports Meet", "Alumni Talk"]
CLUBS = ["Coding Club", "Robotics Club", "Literary Society", "Entrepreneurship Cell", "Music Club", "NSS"]
PROJECTS = ["Campus Navigation App", "Smart Irrigation Prototype", "Library Analytics Dashboard", "Drone Survey Study"]
HACKS = ["Smart India Hackathon", "Campus Hack 24h", "HackerEarth Sprint", "Google Solution Challenge"]
CERTS = ["NPTEL", "Coursera ML", "AWS Cloud Practitioner", "Cisco CCNA", "AutoCAD Certified", "Python (HackerRank)"]

# Review windows: (term id, attendance months, first LMS Monday, skills/placement test dates)
TERMS = {
    "2025-ODD": {"months": ["2025-07", "2025-08", "2025-09"], "lms_start": date(2025, 7, 7),
                 "tests": [date(2025, 8, 14)], "skills": date(2025, 8, 21)},
    "2026-EVEN": {"months": ["2026-01", "2026-02", "2026-03"], "lms_start": date(2026, 1, 5),
                  "tests": [date(2026, 2, 12), date(2026, 3, 19)], "skills": date(2026, 2, 10)},
    "2026-ODD": {"months": ["2026-07", "2026-08", "2026-09"], "lms_start": date(2026, 7, 6),
                 "tests": [date(2026, 8, 13), date(2026, 9, 17)], "skills": date(2026, 8, 20)},
}


def sig(x):
    return 1 / (1 + math.exp(-x))


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def term_of_semester(adm: int, sem: int) -> str:
    # sem 1 = adm-ODD, sem 2 = (adm+1)-EVEN, sem 3 = (adm+1)-ODD ...
    return f"{adm + sem // 2}-{'ODD' if sem % 2 else 'EVEN'}"


def year_at(adm: int, term: str) -> int:
    y, h = term.split("-")
    return (int(y) if h == "ODD" else int(y) - 1) - adm + 1


class Campus:
    def __init__(self, seed: int, cohorts: list[tuple[str, str, int, int]]):
        """cohorts: (dept, course, admission_year, count)."""
        self.rng = random.Random(seed)
        self.students = []
        for dept, course, adm, n in cohorts:
            for i in range(1, n + 1):
                self.students.append(self._student(dept, course, adm, i))

    def _student(self, dept, course, adm, i):
        g = self.rng.gauss
        ability, diligence, wellbeing = g(0, 1), g(0, 1), g(0, 1)
        engagement = 0.4 * diligence + 0.92 * g(0, 1)
        career = 0.45 * ability + 0.3 * engagement + 0.75 * g(0, 1)
        comm = 0.3 * engagement + 0.95 * g(0, 1)
        return {
            "student_id": f"{adm % 100:02d}{dept}{i:03d}", "name": f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}",
            "dept": dept, "course": course, "adm": adm, "gender": self.rng.choice(["F", "M", "M"]),
            "hosteller": self.rng.random() < 0.45, "ability": ability, "diligence": diligence, "engagement": engagement,
            "career": career, "comm": comm, "wellbeing": wellbeing,
            # disengagement episodes: mostly in the current term, a few in the previous one
            "dis": {"2026-ODD": self.rng.random() < 0.06 + 0.06 * (wellbeing < -0.8),
                    "2026-EVEN": self.rng.random() < 0.04, "2025-ODD": self.rng.random() < 0.06},
            # realistic gaps in the current term: LMS account never linked, or a late lateral entry
            "no_lms": self.rng.random() < 0.03, "late_join": self.rng.random() < 0.015,
        }

    # ------------------------------------------------------------------ tables
    def roster(self, mentors_per: int = 20):
        rows, by_dept = [], {}
        for s in self.students:
            by_dept.setdefault(s["dept"], []).append(s)
        for dept, group in by_dept.items():
            group.sort(key=lambda s: s["student_id"])
            for k, s in enumerate(group):
                s["mentor"] = f"mentor.{dept.lower()}{k // mentors_per + 1}"
                rows.append({"student_id": s["student_id"], "name": s["name"],
                             "department": self.rng.choice(DEPT_LABELS[dept]), "course": s["course"],
                             "admission_year": s["adm"], "mentor_username": s["mentor"], "gender": s["gender"],
                             "hosteller": "Y" if s["hosteller"] else "N"})
        return rows

    def academic(self, upto_term: str):
        rows = []
        from .features import term_key
        for s in self.students:
            base = 6.9 + 0.95 * s["ability"] + 0.45 * s["diligence"]
            sg, backlogs = [], 0
            for sem in range(1, 9):
                t = term_of_semester(s["adm"], sem)
                if term_key(t) >= term_key(upto_term) or year_at(s["adm"], t) > (2 if s["course"] == "MCA" else 4):
                    break
                v = base + 0.06 * (sem - 3) * s["diligence"] + self.rng.gauss(0, 0.35)
                if s["dis"].get(t):
                    v -= self.rng.uniform(0.5, 1.1)
                v = round(clip(v, 3.8, 10), 2)
                sg.append(v)
                lam = max(0.0, 6.4 - v) * 0.9
                backlogs = max(0, backlogs + _poisson(self.rng, lam) - _binom(self.rng, backlogs, sig(0.2 + s["diligence"])))
                rows.append({"student_id": s["student_id"], "term": t, "semester": sem, "sgpa": v,
                             "cgpa": round(sum(sg) / len(sg), 2), "backlogs": min(backlogs, 12)})
        return rows

    def internal_marks(self, term: str):
        rows = []
        half = 0 if term.endswith("EVEN") else 6
        for s in self._enrolled(term):
            for subj in SUBJECTS[s["dept"]][half:half + 6]:
                m = 25 + 5 * s["ability"] + 3.5 * s["diligence"] + self.rng.gauss(0, 4) - (self.rng.uniform(3, 8) if s["dis"][term] else 0)
                rows.append({"student_id": s["student_id"], "term": term, "subject": subj,
                             "marks": round(clip(m, 2, 40), 1), "max_marks": 40})
        return rows

    def attendance(self, term: str):
        rows = []
        half = 0 if term.endswith("EVEN") else 6
        for s in self._enrolled(term):
            if term == "2026-ODD" and s["late_join"]:
                continue
            base = clip(84 + 7 * s["diligence"] + 3 * s["wellbeing"] - (0 if s["hosteller"] else 3), 38, 99)
            sid = self._messy_id(s["student_id"])
            for mi, month in enumerate(TERMS[term]["months"]):
                rate = base - ((9 * mi + self.rng.uniform(0, 6)) if s["dis"][term] and mi >= 1 else 0)
                for subj in SUBJECTS[s["dept"]][half:half + 6]:
                    held = self.rng.randint(13, 18)
                    p = clip(rate + self.rng.gauss(0, 6), 0, 100) / 100
                    rows.append({"student_id": sid, "month": month, "subject": subj, "classes_held": held,
                                 "classes_attended": _binom(self.rng, held, p)})
        return rows

    def lms(self, term: str, weeks: range = range(12)):
        rows = []
        start = TERMS[term]["lms_start"]
        for s in self._enrolled(term):
            if term == "2026-ODD" and (s["no_lms"] or s["late_join"]):
                continue
            rate = max(0.5, 4.6 + 1.6 * s["diligence"] + 0.9 * s["engagement"])
            sp = sig(1.7 + 1.3 * s["diligence"] + 0.3 * s["wellbeing"])
            for w in weeks:
                decay = max(0.15, 1 - 0.13 * (w - 4)) if s["dis"][term] and w > 4 else 1.0
                logins = _poisson(self.rng, rate * decay)
                due = self.rng.randint(1, 2)
                sub = _binom(self.rng, due, clip(sp * decay ** 0.7, 0, 1))
                quiz = None if logins == 0 else round(clip(62 + 11 * s["ability"] + 5 * s["diligence"] + self.rng.gauss(0, 9), 0, 100) * (0.85 + 0.15 * decay), 1)
                rows.append({"student_id": f"{s['student_id'].lower()}@campus.edu.in",
                             "week_start": (start + timedelta(weeks=w)).isoformat(), "logins": logins,
                             "assignments_due": due, "assignments_submitted": sub,
                             "quiz_score": "" if quiz is None else quiz})
        return rows

    def engagement(self, start: date, end: date):
        rows = []
        days = (end - start).days
        for s in self.students:
            e, c = s["engagement"], s["career"]
            counts = {"event": _poisson(self.rng, max(0.2, 3.2 + 2 * e)), "club": min(3, _poisson(self.rng, max(0.05, 0.8 + 0.6 * e))),
                      "project": _poisson(self.rng, max(0.02, 0.3 + 0.3 * c)),
                      "hackathon": _poisson(self.rng, max(0.02, 0.4 + 0.5 * c + 0.3 * e + (0.3 if s["dept"] in ("CSE", "IT", "MCA") else 0))),
                      "certification": _poisson(self.rng, max(0.05, 1.0 + 0.5 * c + 0.4 * s["diligence"]))}
            pools = {"event": EVENTS, "club": CLUBS, "project": PROJECTS, "hackathon": HACKS, "certification": CERTS}
            for kind, n in counts.items():
                names = self.rng.sample(pools[kind], min(n, len(pools[kind]))) if kind == "club" else [self.rng.choice(pools[kind]) for _ in range(n)]
                for name in names:
                    d = start + timedelta(days=self.rng.randint(0, days))
                    rows.append({"student_id": s["student_id"], "activity_date": d.isoformat(),
                                 "activity_type": kind if self.rng.random() > 0.05 else kind.upper(), "activity_name": name})
        # identical repeats from a club coordinator's sheet
        rows += self.rng.sample(rows, 6)
        return rows

    def placement(self, term: str):
        rows = []
        for s in self._enrolled(term):
            yr = year_at(s["adm"], term)
            if yr < (2 if s["course"] == "MCA" else 3):
                continue
            take = clip((0.6 if yr == (2 if s["course"] == "MCA" else 3) and term.endswith("EVEN") else 0.8) + 0.18 * s["career"], 0.05, 0.98)
            for k, d in enumerate(TERMS[term]["tests"]):
                if self.rng.random() > take * (1 if k == 0 else 0.6):
                    continue
                gain = 3 * k + (4 if term == "2026-ODD" else 0)
                rows.append({"student_id": s["student_id"], "assessment_date": d.isoformat(),
                             "aptitude_score": round(clip(56 + 11 * s["ability"] + 6 * s["career"] + self.rng.gauss(0, 7) + gain, 5, 100), 1),
                             "coding_score": round(clip(50 + 9 * s["ability"] + 12 * s["career"] + CODING_BONUS[s["dept"]] + self.rng.gauss(0, 8) + gain, 0, 100), 1),
                             "mock_interview_rating": round(clip(3.0 + 0.55 * s["career"] + 0.45 * s["comm"] + self.rng.gauss(0, 0.35), 1, 5), 1),
                             "resume_reviewed": self.rng.choice(["Yes", "Y", "yes"]) if s["career"] > -0.4 else self.rng.choice(["No", "N"])})
        return rows

    def skills(self, term: str):
        rows = []
        for s in self._enrolled(term):
            if self.rng.random() < 0.04:
                continue  # absent on assessment day
            pct = self.rng.random() < 0.3

            def v(x):
                x = clip(x, 10, 100)
                return f"{x:.0f}%" if pct else round(x, 1)
            rows.append({"student_id": s["student_id"], "assessed_on": TERMS[term]["skills"].isoformat(),
                         "technical": v(58 + 10 * s["ability"] + 8 * s["career"] + self.rng.gauss(0, 7)),
                         "communication": v(60 + 12 * s["comm"] + self.rng.gauss(0, 6)),
                         "teamwork": v(64 + 7 * s["engagement"] + 4 * s["comm"] + self.rng.gauss(0, 7)),
                         "problem_solving": v(57 + 10 * s["ability"] + 4 * s["diligence"] + self.rng.gauss(0, 7))})
        return rows

    def feedback(self, term: str):
        rows = []
        for s in self._enrolled(term):
            if self.rng.random() < 0.12:
                continue  # did not respond
            w = s["wellbeing"]
            concern = w < -0.9 or (s["dis"][term] and self.rng.random() < 0.6)
            note = (self.rng.choice(CONCERN) if concern and self.rng.random() < 0.85 else
                    self.rng.choice(POSITIVE) if s["engagement"] + s["diligence"] > 1.5 else self.rng.choice(NEUTRAL))
            rows.append({"student_id": s["student_id"], "term": term,
                         "satisfaction": int(clip(round(3.5 + 0.7 * w + 0.2 * s["engagement"] + self.rng.gauss(0, 0.5)), 1, 5)),
                         "stress": int(clip(round(2.8 - 0.7 * w + self.rng.gauss(0, 0.6)), 1, 5)),
                         "faculty_rating": round(clip(3.3 + 0.6 * s["diligence"] + 0.4 * s["engagement"] + self.rng.gauss(0, 0.5), 1, 5), 1),
                         "faculty_remark": note})
        return rows

    def outcomes(self, term: str):
        """End-of-programme outcomes for a historical batch (term = start of final year)."""
        acad = {}
        for r in self.academic(term):
            acad[r["student_id"]] = r
        out = []
        for s in self.students:
            a = acad.get(s["student_id"], {"cgpa": 6.9, "backlogs": 0})
            final = clip(a["cgpa"] + 0.35 * s["diligence"] + 0.2 * s["wellbeing"] - (0.9 if s["dis"][term] else 0) + self.rng.gauss(0, 0.45), 4, 10)
            bl = max(0, a["backlogs"] - _binom(self.rng, a["backlogs"], sig(0.3 + s["diligence"])))
            poor = int(final < 6.0 or bl > 0)
            logit = 0.7 + 1.1 * s["career"] + 0.6 * s["ability"] + 0.4 * s["comm"] - 1.4 * (bl > 0) - 0.8 * (final < 6) + self.rng.gauss(0, 0.6)
            out.append({"student_id": s["student_id"], "final_cgpa": round(final, 2), "backlogs_at_graduation": bl,
                        "academic_outcome_poor": poor, "placed_within_6_months": int(self.rng.random() < sig(logit))})
        return out

    # ------------------------------------------------------------------ helpers
    def _enrolled(self, term):
        for s in self.students:
            if 1 <= year_at(s["adm"], term) <= (2 if s["course"] == "MCA" else 4):
                s["dis"].setdefault(term, False)
                yield s

    def _messy_id(self, sid):
        r = self.rng.random()
        if r < 0.4:
            return sid.lower()
        if r < 0.6:
            return f"{sid[:2]}-{sid[2:-3]}-{sid[-3:]}".lower()
        if r < 0.7:
            return f" {sid} "
        return sid


def _poisson(rng, lam):
    lam = max(lam, 0)
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _binom(rng, n, p):
    return sum(rng.random() < p for _ in range(n))


def write_csv(path: Path, rows: list[dict], category: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in SCHEMAS[category].fields] if category else list(rows[0])
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_xlsx(path: Path, rows: list[dict], category: str) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SCHEMAS[category].label[:30]
    cols = [f.name for f in SCHEMAS[category].fields]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    wb.save(path)


def generate(out: Path) -> dict:
    cur = Campus(2026, [(d, "B.Tech", a, 40) for a in (2023, 2024, 2025) for d in DEPTS]
                 + [("MCA", "MCA", a, 30) for a in (2024, 2025)])
    c = out / "current"
    files = []

    def put(name, rows, cat):
        write_csv(c / name, rows, cat)
        files.append({"file": f"current/{name}", "category": cat, "period": name.split("_")[-1].removesuffix(".csv")
                      if "20" in name else "2026-ODD", "rows": len(rows)})

    put("01_roster.csv", cur.roster(), "students")
    put("02_academic_results_2026-ODD.csv", cur.academic("2026-ODD"), "academic")
    keep = {}
    for term in ("2026-EVEN", "2026-ODD"):
        put(f"03_internal_marks_{term}.csv", cur.internal_marks(term), "internal_marks")
        keep[("attendance", term)] = cur.attendance(term)
        put(f"04_attendance_{term}.csv", keep[("attendance", term)], "attendance")
        put(f"05_lms_{term}.csv", cur.lms(term, range(12) if term == "2026-EVEN" else range(10)), "lms")
        put(f"07_placement_{term}.csv", cur.placement(term), "placement")
        keep[("skills", term)] = cur.skills(term)
        put(f"08_skills_{term}.csv", keep[("skills", term)], "skills")
        put(f"09_feedback_{term}.csv", cur.feedback(term), "feedback")
    put("06_engagement_2026-ODD.csv", cur.engagement(date(2025, 10, 1), date(2026, 9, 30)), "engagement")
    files.sort(key=lambda f: f["file"])

    # Demo files for the live walkthrough
    d = out / "demo"
    write_csv(d / "lms_2026-ODD_weeks11-12.csv", cur.lms("2026-ODD", range(10, 12)), "lms")
    # Same rows as the loaded CSV, re-exported as Excel: importing it again must change nothing.
    write_xlsx(d / "skills_2026-ODD.xlsx", keep[("skills", "2026-ODD")], "skills")
    good = keep[("attendance", "2026-ODD")][:40]
    bad = [dict(r) for r in good[:8]]
    bad[0]["student_id"] = "24CSE999"                                 # not in roster
    bad[1]["classes_attended"] = bad[1]["classes_held"] + 3          # attended > held
    bad[2]["month"] = "Sept 2026"                                    # bad format
    bad[3]["classes_held"] = ""                                      # required value missing
    bad[4]["student_id"] = "ABC-123"                                 # invalid roll number
    bad += [dict(good[10]), dict(good[10])]                          # exact duplicate
    conflict = dict(good[11])
    conflict["classes_attended"] = max(0, conflict["classes_attended"] - 2)
    bad += [dict(good[11]), conflict]                                # conflicting duplicate
    write_csv(d / "attendance_with_errors.csv", bad + good[12:30], "attendance")

    # Historical batch for offline validation
    hist = Campus(1977, [(dpt, "B.Tech", 2022, 180) for dpt in DEPTS])
    h = out / "history"
    write_csv(h / "roster.csv", hist.roster(), "students")
    write_csv(h / "academic.csv", hist.academic("2025-ODD"), "academic")
    write_csv(h / "internal_marks.csv", hist.internal_marks("2025-ODD"), "internal_marks")
    write_csv(h / "attendance.csv", hist.attendance("2025-ODD"), "attendance")
    write_csv(h / "lms.csv", hist.lms("2025-ODD"), "lms")
    write_csv(h / "engagement.csv", hist.engagement(date(2024, 10, 1), date(2025, 9, 30)), "engagement")
    write_csv(h / "placement.csv", hist.placement("2025-ODD"), "placement")
    write_csv(h / "skills.csv", hist.skills("2025-ODD"), "skills")
    write_csv(h / "feedback.csv", hist.feedback("2025-ODD"), "feedback")
    write_csv(h / "graduation_outcomes.csv", hist.outcomes("2025-ODD"))

    manifest = {"note": "SYNTHETIC DATA. Generated by ssp/synth.py; no real student information.",
                "students": len(cur.students), "load_order": files,
                "demo": ["demo/attendance_with_errors.csv", "demo/lms_2026-ODD_weeks11-12.csv", "demo/skills_2026-ODD.xlsx"]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    from .settings import SAMPLE_DIR
    m = generate(SAMPLE_DIR)
    print(json.dumps({k: v for k, v in m.items() if k != "load_order"}, indent=2))
    for f in m["load_order"]:
        print(f"  {f['file']:<45} {f['category']:<15} {f['rows']}")
