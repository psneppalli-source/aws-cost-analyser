"""Generate a realistic, deliberately messy synthetic campus dataset.

Real colleges keep student data in disconnected systems, each with its own
ID format, column names and quality problems. This module simulates seven
such source systems for the *current* students, plus a historical cohort
(last year's graduating batch) whose real outcomes are known and are used
to train and validate the risk models.

Every source table is generated from a small set of hidden student traits
(ability, diligence, engagement, career focus, wellbeing), so the signals
are correlated the way they are on a real campus, and then corrupted with
the kinds of issues found in exports: inconsistent IDs, duplicate rows,
percent strings, out-of-range values, missing responses.

Run: python -m pipeline.generate_data
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

DEPTS = {
    "CSE": ["Computer Science & Engg", "C.S.E", "CSE", "Computer Science"],
    "IT": ["Information Technology", "I.T.", "IT"],
    "ECE": ["Electronics & Communication", "E.C.E", "ECE"],
    "MECH": ["Mechanical Engg", "Mechanical", "MECH"],
    "CIVIL": ["Civil Engg", "Civil", "CIVIL"],
}
SUBJECTS = {
    "CSE": ["Data Structures", "Operating Systems", "DBMS", "Computer Networks", "Machine Learning", "Software Engg"],
    "IT": ["Data Structures", "Web Technologies", "DBMS", "Cloud Computing", "Information Security", "Software Engg"],
    "ECE": ["Signals & Systems", "Digital Electronics", "Analog Circuits", "Microprocessors", "Communication Systems", "VLSI Design"],
    "MECH": ["Thermodynamics", "Fluid Mechanics", "Machine Design", "Manufacturing Processes", "Heat Transfer", "CAD/CAM"],
    "CIVIL": ["Structural Analysis", "Surveying", "Geotechnical Engg", "Fluid Mechanics", "Concrete Technology", "Transportation Engg"],
}
# Coding-score advantage by department (CS-adjacent branches practise more).
DEPT_CODING = {"CSE": 8, "IT": 6, "ECE": 0, "MECH": -6, "CIVIL": -8}
FIRST = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan",
         "Ananya", "Diya", "Aadhya", "Saanvi", "Pari", "Kavya", "Meera", "Isha", "Riya", "Nisha",
         "Rahul", "Karthik", "Siddharth", "Varun", "Pranav", "Lakshmi", "Divya", "Sneha", "Pooja", "Tanvi",
         "Harsh", "Yash", "Manav", "Nikhil", "Abhinav", "Shreya", "Neha", "Priya", "Aditi", "Swathi"]
LAST = ["Sharma", "Verma", "Reddy", "Iyer", "Nair", "Patel", "Gupta", "Singh", "Rao", "Kumar",
        "Menon", "Joshi", "Das", "Mehta", "Chopra", "Bose", "Pillai", "Kulkarni", "Agarwal", "Naidu"]
MONTHS = ["2026-07", "2026-08", "2026-09"]
N_WEEKS = 12

CONCERN_NOTES = [
    "Mentions financial difficulty at home; working part-time evenings.",
    "Reported health issues this semester; missed several classes.",
    "Commutes over 2 hours daily; often late for first period.",
    "Seems withdrawn in class and avoids mentor meetings.",
    "Family responsibilities affecting study time.",
    "Struggling to cope with workload; asked about dropping a subject.",
]
NEUTRAL_NOTES = [
    "Regular in mentoring sessions; no concerns raised.",
    "Attends class regularly but participation is limited.",
    "Steady progress; needs encouragement to take up projects.",
]
POSITIVE_NOTES = [
    "Active in class discussions and helps peers.",
    "Shows leadership in project work; highly motivated.",
    "Consistently curious; pursuing extra online courses.",
]


@dataclass
class Cohort:
    latent: pd.DataFrame
    tables: dict[str, pd.DataFrame]


def _clip(x, lo, hi):
    return np.clip(x, lo, hi)


def _latent(n: int, rng: np.random.Generator, years: list[int], id_prefix_year: dict[int, int]) -> pd.DataFrame:
    """Hidden traits that drive every observed signal."""
    depts = list(DEPTS)
    rows = []
    seq: dict[tuple[int, str], int] = {}
    for i in range(n):
        year = years[i % len(years)]
        dept = depts[(i // len(years)) % len(depts)]
        key = (year, dept)
        seq[key] = seq.get(key, 0) + 1
        adm = id_prefix_year[year]
        rows.append({
            "student_id": f"{adm % 100:02d}{dept}{seq[key]:03d}",
            "dept": dept,
            "year": year,
        })
    df = pd.DataFrame(rows)
    ability = rng.normal(0, 1, n)
    diligence = rng.normal(0, 1, n)
    engagement = 0.4 * diligence + np.sqrt(1 - 0.16) * rng.normal(0, 1, n)
    career = 0.45 * ability + 0.3 * engagement + 0.75 * rng.normal(0, 1, n)
    communication = 0.3 * engagement + 0.95 * rng.normal(0, 1, n)
    wellbeing = rng.normal(0, 1, n)
    df["ability"] = ability
    df["diligence"] = diligence
    df["engagement"] = engagement
    df["career"] = career
    df["communication"] = communication
    df["wellbeing"] = wellbeing
    # A minority of otherwise-normal students start disengaging mid-semester:
    # the early-warning pattern the platform must catch before grades show it.
    df["disengaging"] = rng.random(n) < (0.06 + 0.06 * (wellbeing < -0.8))
    df["gender"] = rng.choice(["F", "M"], n, p=[0.42, 0.58])
    df["name"] = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n)]
    df["hosteller"] = rng.random(n) < 0.45
    return df


def _academic(lat: pd.DataFrame, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    sis_rows, marks_rows = [], []
    for r in lat.itertuples():
        n_sem = 2 * (r.year - 1)
        base = 6.9 + 0.95 * r.ability + 0.45 * r.diligence
        sgpas = []
        for s in range(1, n_sem + 1):
            g = base + 0.05 * (s - n_sem / 2) * r.diligence + rng.normal(0, 0.35)
            if r.disengaging and s == n_sem:
                g -= rng.uniform(0.5, 1.1)
            sgpas.append(round(float(_clip(g, 3.8, 10.0)), 2))
        cgpa = round(float(np.mean(sgpas)), 2)
        lam = max(0.0, 6.6 - cgpa) * 1.1 + 0.03
        backlogs = int(min(rng.poisson(lam), 9))
        dept_label = rng.choice(DEPTS[r.dept])
        rec = {
            "Roll No": r.student_id,
            "Student Name": r.name.upper() if rng.random() < 0.15 else r.name,
            "Department": dept_label,
            "Current Year": r.year,
            "Gender": r.gender,
            "CGPA": cgpa,
            "Active Backlogs": backlogs,
            "Hosteller": "Y" if r.hosteller else "N",
        }
        for s in range(1, 7):
            rec[f"SGPA_S{s}"] = sgpas[s - 1] if s <= n_sem else None
        # Data-quality issues seen in SIS exports.
        if rng.random() < 0.01:
            rec["CGPA"] = "NA"
        sis_rows.append(rec)
        # Current-semester internal assessment marks (out of 40 per subject).
        for subj in SUBJECTS[r.dept]:
            m = 25 + 5 * r.ability + 3.5 * r.diligence + rng.normal(0, 4)
            if r.disengaging:
                m -= rng.uniform(3, 8)
            marks_rows.append({
                "roll_no": r.student_id,
                "semester": n_sem + 1,
                "subject": subj,
                "internal_marks": round(float(_clip(m, 2, 40)), 1),
                "max_marks": 40,
            })
    sis = pd.DataFrame(sis_rows)
    # Duplicate rows from a re-import.
    dupes = sis.sample(frac=0.02, random_state=int(rng.integers(1e9)))
    sis = pd.concat([sis, dupes]).sample(frac=1, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    return sis, pd.DataFrame(marks_rows)


def _attendance(lat: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for r in lat.itertuples():
        base = 84 + 7 * r.diligence + 3 * r.wellbeing - (3 if not r.hosteller else 0)
        base = float(_clip(base, 38, 99))
        roll_fmt = rng.choice(["lower", "dash", "space", "plain"], p=[0.4, 0.2, 0.1, 0.3])
        sid = r.student_id
        if roll_fmt == "lower":
            sid = sid.lower()
        elif roll_fmt == "dash":
            sid = f"{sid[:2]}-{sid[2:-3]}-{sid[-3:]}".lower()
        elif roll_fmt == "space":
            sid = f" {sid} "
        for mi, month in enumerate(MONTHS):
            month_rate = base
            if r.disengaging and mi >= 1:
                month_rate -= 9 * mi + rng.uniform(0, 6)
            for subj in SUBJECTS[r.dept]:
                held = int(rng.integers(13, 19))
                rate = _clip(month_rate + rng.normal(0, 6), 0, 100) / 100
                attended = int(rng.binomial(held, rate))
                rows.append({
                    "RollNo": sid,
                    "Month": month,
                    "Subject": subj,
                    "Classes_Held": held,
                    "Classes_Attended": attended,
                })
    df = pd.DataFrame(rows)
    # Biometric glitch: a few rows record more attended than held.
    glitch = df.sample(frac=0.004, random_state=int(rng.integers(1e9))).index
    df.loc[glitch, "Classes_Attended"] = df.loc[glitch, "Classes_Held"] + rng.integers(1, 4, len(glitch))
    return df


def _lms(lat: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for r in lat.itertuples():
        email = f"{r.student_id.lower()}@campus.edu.in"
        login_rate = max(0.5, 4.6 + 1.6 * r.diligence + 0.9 * r.engagement)
        submit_p = 1 / (1 + np.exp(-(1.7 + 1.3 * r.diligence + 0.3 * r.wellbeing)))
        for w in range(1, N_WEEKS + 1):
            decay = 1.0
            if r.disengaging and w > 5:
                decay = max(0.15, 1 - 0.13 * (w - 5))
            logins = int(rng.poisson(login_rate * decay))
            due = int(rng.integers(1, 3))
            submitted = int(rng.binomial(due, _clip(submit_p * (decay ** 0.7), 0, 1)))
            quiz = _clip(62 + 11 * r.ability + 5 * r.diligence + rng.normal(0, 9), 0, 100)
            if logins == 0:
                quiz_val = None  # no attempt
            else:
                quiz_val = round(float(quiz * (0.85 + 0.15 * decay)), 1)
            rows.append({
                "user_email": email,
                "week": w,
                "logins": logins,
                "assignments_due": due,
                "assignments_submitted": submitted,
                "quiz_score": quiz_val,
                "minutes_active": int(logins * rng.uniform(12, 35)),
            })
    return pd.DataFrame(rows)


def _engagement(lat: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    events = ["Tech Fest Volunteer", "Guest Lecture", "Cultural Fest", "Industry Visit", "Workshop: IoT",
              "Workshop: GenAI", "Blood Donation Drive", "NSS Camp", "Sports Meet", "Alumni Talk"]
    clubs = ["Coding Club", "Robotics Club", "Literary Society", "Entrepreneurship Cell", "Music Club", "NSS"]
    hacks = ["Smart India Hackathon", "Campus Hack 24h", "HackerEarth Sprint", "Google Solution Challenge"]
    certs = ["NPTEL", "Coursera ML", "AWS Cloud Practitioner", "Cisco CCNA", "AutoCAD Certified", "Python (HackerRank)"]
    for r in lat.itertuples():
        ref = r.student_id
        if rng.random() < 0.1:  # un-padded IDs typed by club coordinators
            ref = ref[:-3] + str(int(ref[-3:]))
        n_ev = rng.poisson(max(0.2, 2.6 + 1.6 * r.engagement))
        n_cl = rng.poisson(max(0.05, 0.8 + 0.6 * r.engagement))
        n_hk = rng.poisson(max(0.02, 0.4 + 0.5 * r.career + 0.3 * r.engagement + (0.3 if r.dept in ("CSE", "IT") else 0)))
        n_ce = rng.poisson(max(0.05, 0.9 + 0.5 * r.career + 0.4 * r.diligence))
        for kind, n_items, pool in (("event", n_ev, events), ("club", min(n_cl, 3), clubs),
                                    ("hackathon", n_hk, hacks), ("certification", n_ce, certs)):
            for _ in range(int(n_items)):
                rows.append({
                    "student_ref": ref,
                    "activity_type": kind if rng.random() > 0.05 else kind.upper(),
                    "activity_name": rng.choice(pool),
                    "date": f"2026-{int(rng.integers(1, 10)):02d}-{int(rng.integers(1, 28)):02d}",
                })
    return pd.DataFrame(rows)


def _placement(lat: pd.DataFrame, rng, coverage: dict[int, float]) -> pd.DataFrame:
    rows = []
    for r in lat.itertuples():
        # Less career-focused students are more likely to skip placement tests.
        take_p = float(_clip(coverage.get(r.year, 0) + 0.18 * r.career, 0.05, 0.99)) if r.year >= 3 else 0
        if rng.random() > take_p:
            continue
        attempts = int(rng.integers(1, 4))
        for a in range(attempts):
            gain = 3 * a  # practice effect on later attempts
            apt = _clip(56 + 11 * r.ability + 6 * r.career + rng.normal(0, 7) + gain, 5, 100)
            code = _clip(52 + 9 * r.ability + 12 * r.career + DEPT_CODING[r.dept] + rng.normal(0, 8) + gain, 0, 100)
            mock = _clip(3.0 + 0.55 * r.career + 0.45 * r.communication + rng.normal(0, 0.35), 1, 5)
            rows.append({
                "reg_no": r.student_id,
                "attempt_date": f"2026-0{3 + 2 * a}-15",
                "aptitude_score": round(float(apt), 1),
                "coding_score": round(float(code), 1),
                "mock_interview_rating": round(float(mock), 1),
                "resume_reviewed": rng.choice(["Yes", "No", "yes", "Y"]) if r.career > -0.5 else rng.choice(["No", "N", ""]),
            })
    return pd.DataFrame(rows)


def _skills(lat: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for r in lat.itertuples():
        tech = _clip(58 + 10 * r.ability + 8 * r.career + rng.normal(0, 7), 10, 100)
        comm = _clip(60 + 12 * r.communication + rng.normal(0, 6), 10, 100)
        team = _clip(64 + 7 * r.engagement + 4 * r.communication + rng.normal(0, 7), 10, 100)
        prob = _clip(57 + 10 * r.ability + 4 * r.diligence + rng.normal(0, 7), 10, 100)
        as_pct = rng.random() < 0.3
        fmt = (lambda v: f"{v:.0f}%") if as_pct else (lambda v: round(float(v), 1))
        rows.append({
            "roll_no": r.student_id,
            "technical_skill": fmt(tech),
            "communication": fmt(comm),
            "teamwork": fmt(team),
            "problem_solving": fmt(prob),
            "assessed_on": "2026-08-20",
        })
    return pd.DataFrame(rows)


def _feedback(lat: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for r in lat.itertuples():
        if rng.random() < 0.12:  # did not respond to the survey
            continue
        sat = _clip(round(3.5 + 0.7 * r.wellbeing + 0.2 * r.engagement + rng.normal(0, 0.5)), 1, 5)
        stress = _clip(round(2.8 - 0.7 * r.wellbeing + rng.normal(0, 0.6)), 1, 5)
        mentor = _clip(round(3.3 + 0.6 * r.diligence + 0.4 * r.engagement + rng.normal(0, 0.5), 1), 1, 5)
        concern = r.wellbeing < -0.9 or (r.disengaging and rng.random() < 0.6)
        if concern and rng.random() < 0.85:
            note = rng.choice(CONCERN_NOTES)
        elif r.engagement + r.diligence > 1.5:
            note = rng.choice(POSITIVE_NOTES)
        else:
            note = rng.choice(NEUTRAL_NOTES)
        rows.append({
            "roll": r.student_id,
            "satisfaction_1to5": int(sat),
            "stress_1to5": int(stress),
            "mentor_rating_1to5": float(mentor),
            "mentor_remark": note,
        })
    return pd.DataFrame(rows)


def simulate(n: int, seed: int, years: list[int], id_year: dict[int, int],
             placement_coverage: dict[int, float]) -> Cohort:
    rng = np.random.default_rng(seed)
    lat = _latent(n, rng, years, id_year)
    sis, marks = _academic(lat, rng)
    tables = {
        "sis_academic_records": sis,
        "exam_internal_marks": marks,
        "biometric_attendance": _attendance(lat, rng),
        "lms_weekly_activity": _lms(lat, rng),
        "engagement_activity_log": _engagement(lat, rng),
        "placement_cell_assessments": _placement(lat, rng, placement_coverage),
        "skills_assessment": _skills(lat, rng),
        "student_feedback_survey": _feedback(lat, rng),
    }
    return Cohort(lat, tables)


def historical_outcomes(lat: pd.DataFrame, sis: pd.DataFrame, rng) -> pd.DataFrame:
    """Known end-of-programme outcomes for last year's graduating batch."""
    s = sis.drop_duplicates("Roll No").set_index("Roll No")
    cg = pd.to_numeric(s["CGPA"], errors="coerce")
    out = []
    for r in lat.itertuples():
        cgpa = cg.get(r.student_id, np.nan)
        if np.isnan(cgpa):
            cgpa = 6.9 + 0.95 * r.ability
        drift = 0.35 * r.diligence + 0.2 * r.wellbeing - (0.9 if r.disengaging else 0) + rng.normal(0, 0.45)
        final_cgpa = float(_clip(cgpa + drift, 4, 10))
        bl = int(s.at[r.student_id, "Active Backlogs"]) if r.student_id in s.index else 0
        cleared = rng.binomial(bl, 1 / (1 + np.exp(-(0.3 + 1.0 * r.diligence))))
        final_bl = int(bl - cleared + (rng.random() < 0.15 * r.disengaging))
        academic_poor = int(final_cgpa < 6.0 or final_bl > 0)
        logit = (0.7 + 1.1 * r.career + 0.6 * r.ability + 0.4 * r.communication
                 - 1.4 * (final_bl > 0) - 0.8 * (final_cgpa < 6.0) + rng.normal(0, 0.6))
        placed = int(rng.random() < 1 / (1 + np.exp(-logit)))
        out.append({"roll_no": r.student_id, "final_cgpa": round(final_cgpa, 2),
                    "backlogs_at_graduation": final_bl, "academic_outcome_poor": academic_poor,
                    "placed_within_6_months": placed})
    return pd.DataFrame(out)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    hist_dir = RAW / "historical_batch_2022"
    hist_dir.mkdir(parents=True, exist_ok=True)

    # Current students: 2nd, 3rd and 4th year across five departments (600).
    current = simulate(600, seed=2026, years=[2, 3, 4], id_year={2: 2025, 3: 2024, 4: 2023},
                       placement_coverage={3: 0.65, 4: 0.93})
    # Last year's graduating batch, as they looked at the start of final year.
    hist = simulate(900, seed=1977, years=[4], id_year={4: 2022}, placement_coverage={4: 0.93})
    outcomes = historical_outcomes(hist.latent, hist.tables["sis_academic_records"], np.random.default_rng(7))

    for name, df in current.tables.items():
        df.to_csv(RAW / f"{name}.csv", index=False)
    for name, df in hist.tables.items():
        df.to_csv(hist_dir / f"{name}.csv", index=False)
    outcomes.to_csv(hist_dir / "graduation_outcomes.csv", index=False)

    manifest = {
        "generated_by": "pipeline/generate_data.py",
        "note": "Synthetic data. No real student information.",
        "current_students": len(current.latent),
        "historical_students": len(hist.latent),
        "sources": {name: len(df) for name, df in current.tables.items()},
    }
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
