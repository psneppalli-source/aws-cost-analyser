"""Offline check of the scoring rules against real outcomes.

Loads last year's batch (2022 B.Tech, as it looked at the start of final
year, 2025-ODD) through the normal import pipeline into a throwaway store,
scores it with the active rules, and compares with what actually happened at
graduation. Writes config/validation_report.json, shown on the Scoring page.

    python -m ssp.validate
"""

from __future__ import annotations

import copy
import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from . import config, engine, importer, settings
from .auth import Principal
from .storage import LocalBlobs, LocalTable, Store, get_store, set_store

FILES = [("roster.csv", "students"), ("academic.csv", "academic"), ("internal_marks.csv", "internal_marks"),
         ("attendance.csv", "attendance"), ("lms.csv", "lms"), ("engagement.csv", "engagement"),
         ("placement.csv", "placement"), ("skills.csv", "skills"), ("feedback.csv", "feedback")]


def auc(pairs: list[tuple[float, int]]) -> float | None:
    """P(random positive ranks above random negative); ties count half."""
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def run(cfg: dict | None = None) -> dict:
    cfg = copy.deepcopy(cfg or json.loads(settings.DEFAULT_CONFIG.read_text()))
    hist = settings.SAMPLE_DIR / "history"
    cfg["version"] = cfg["version"] + "-validation"
    cfg["review_periods"] = [{"id": "2025-ODD", "label": "Start of final year (2025-ODD)", "start": "2025-07-01", "end": "2025-11-30"}]
    cfg["current_period"] = "2025-ODD"
    previous = get_store()
    with tempfile.TemporaryDirectory() as tmp:
        set_store(Store(LocalBlobs(Path(tmp) / "blobs"), LocalTable(Path(tmp) / "items.db")))
        try:
            who = Principal("validation", "Validation run", "admin")
            config.activate(cfg, who, "validation")
            for name, cat in FILES:
                s = importer.validate(cat, name, (hist / name).read_bytes(), "2025-ODD", who)
                importer.commit(s["id"], who, recalc=False)
            engine.recalculate(who, "validation")
            snap = engine.snapshot("2025-ODD")["students"]
        finally:
            set_store(previous)
            config._cache["version"] = None
    outcomes = {r["student_id"]: r for r in csv.DictReader((hist / "graduation_outcomes.csv").open())}
    rows = [(snap[sid], int(o["academic_outcome_poor"]), 1 - int(o["placed_within_6_months"]))
            for sid, o in outcomes.items() if sid in snap and snap[sid]["score"]["score"] is not None]

    def rates(key):
        g = defaultdict(lambda: [0, 0, 0])
        for s, poor, unplaced in rows:
            k = key(s)
            g[k][0] += 1
            g[k][1] += poor
            g[k][2] += unplaced
        return {k: {"students": n, "poor_academic_rate": round(a / n, 3), "not_placed_rate": round(b / n, 3)} for k, (n, a, b) in g.items()}

    report = {
        "rules_version": cfg["version"].removesuffix("-validation"),
        "batch": "2022 B.Tech batch, scored at the start of final year (2025-ODD), compared with graduation outcomes",
        "students": len(rows),
        "base_rates": {"poor_academic": round(sum(r[1] for r in rows) / len(rows), 3),
                       "not_placed": round(sum(r[2] for r in rows) / len(rows), 3)},
        "score_auc": {"poor_academic": auc([(-s["score"]["score"], p) for s, p, _ in rows]),
                      "not_placed": auc([(-s["score"]["score"], u) for s, _, u in rows])},
        "risk_points_auc": {"academic": auc([(s["risk"]["academic"]["points"], p) for s, p, _ in rows]),
                            "placement": auc([(s["risk"]["placement"]["points"], u) for s, _, u in rows])},
        "by_band": rates(lambda s: s["score"]["band"]),
        "by_academic_level": rates(lambda s: s["risk"]["academic"]["level"]),
        "by_placement_level": rates(lambda s: s["risk"]["placement"]["level"]),
    }
    return report


def main():
    rep = run(config.active() if (settings.LOCAL_DIR / "items.db").exists() else None)
    out = settings.ROOT / "config" / "validation_report.json"
    out.write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
