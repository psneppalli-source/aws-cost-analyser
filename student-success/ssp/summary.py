"""Draft student summaries grounded only in the student's own records.

Deterministic natural-language generation: every sentence is built from a
value in the snapshot, so nothing can be invented. Drafts are never shown to
students and must be reviewed (and can be edited) by staff before saving.
A hosted LLM can replace `draft()` later; the review-before-save workflow
stays the same.
"""

from __future__ import annotations

import uuid

from . import audit
from .audit import now_iso
from .storage import get_store


def _fmt(v, unit=""):
    if v is None:
        return "not recorded"
    if isinstance(v, float):
        v = round(v, 1)
    return f"{v}{unit}"


def draft(student: dict, snap: dict, history: list[dict], cfg: dict, sensitive: bool) -> str:
    f, sc, risk = snap["features"], snap["score"], snap["risk"]
    name = student["name"].split()[0]
    lines = []
    s = sc["score"]
    if s is None:
        lines.append(f"{name}'s Success Score is withheld because only {sc['coverage']:.0%} of the expected data is available "
                     f"(missing: {', '.join(sc['missing'][:4])}).")
    else:
        prov = " (provisional, data coverage " + f"{sc['coverage']:.0%})" if sc["status"] == "provisional" else ""
        trend = ""
        prev = [h for h in history if h["score"] is not None and h["period"] != snap.get("period")]
        if prev:
            d = s - prev[-1]["score"]
            trend = f", {'up' if d > 0 else 'down'} {abs(d):.1f} points since {prev[-1]['period']}" if abs(d) >= 1 else ", about the same as last review"
        lines.append(f"{name} ({student['department']}, year {snap['year']}) has a Success Score of {s:.1f}, "
                     f"in the '{sc['band']}' band{prov}{trend}.")
    pillars = {k: v for k, v in sc["pillars"].items() if v is not None}
    if pillars:
        best = sorted(pillars, key=pillars.get, reverse=True)[:2]
        worst = sorted(pillars, key=pillars.get)[:2]
        lab = lambda k: cfg["pillars"][k]["label"].lower()
        lines.append(f"Strongest areas: {lab(best[0])} ({pillars[best[0]]:.0f}/100)"
                     + (f" and {lab(best[1])} ({pillars[best[1]]:.0f}/100)" if len(best) > 1 else "") + ". "
                     f"Weakest: {lab(worst[0])} ({pillars[worst[0]]:.0f}/100).")
    for kind, label in (("academic", "Academic risk"), ("placement", "Placement risk")):
        r = risk[kind]
        if r["level"] == "Not applicable":
            continue
        ev = [e for e in sorted(r["evidence"], key=lambda e: -e["points"]) if sensitive or not e.get("sensitive")][:3]
        if r["level"] == "Insufficient data":
            lines.append(f"{label} can't be assessed yet: no {', '.join(r['missing'])} on record.")
        elif ev:
            reasons = "; ".join(f"{e['label'].lower()} {_fmt(e['value'], e.get('unit', ''))}" for e in ev)
            lines.append(f"{label} is {r['level'].lower()}, mainly because of: {reasons}.")
        else:
            lines.append(f"{label} is {r['level'].lower()}; no risk rules are triggered.")
    if f.get("attendance_pct") is not None:
        lines.append(f"Attendance this term is {f['attendance_pct']:.0f}%"
                     + (f" (lowest in {f['attendance_min_subject']} at {f['attendance_min_subject_pct']:.0f}%)" if f.get("attendance_min_subject") else "")
                     + (f", changing {f['attendance_trend']:+.0f} points since the first month." if f.get("attendance_trend") is not None else "."))
    if sensitive and snap.get("detail", {}).get("concern_tags"):
        lines.append(f"Mentor notes mention: {', '.join(snap['detail']['concern_tags']).lower()} concerns.")
    if snap.get("actions"):
        lines.append("Suggested next steps: " + "; ".join(a["title"] for a in snap["actions"][:3]) + ".")
    return " ".join(lines)


def save(principal, student_id: str, text: str, generated: str) -> dict:
    ts = now_iso()
    item = {"id": uuid.uuid4().hex[:10], "student_id": student_id, "text": text.strip(), "edited": text.strip() != generated.strip(),
            "approved_by": principal.username, "approved_at": ts}
    get_store().table.put(f"SUMMARY#{student_id}", ts, item)
    audit.log(principal, "summary.approved", "student", student_id, {"edited": item["edited"]})
    return item


def saved(student_id: str) -> list[dict]:
    return get_store().table.query(f"SUMMARY#{student_id}", newest_first=True, limit=5)
