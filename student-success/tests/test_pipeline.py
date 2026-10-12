"""Pipeline tests. Run: python -m unittest discover -s tests -v (from student-success/)."""

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import analytics, models, scoring
from pipeline.build import build
from pipeline.integrate import canonical_id, integrate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


class TestIds(unittest.TestCase):
    def test_canonical_id_variants(self):
        for raw in ["24CSE007", "24cse007", " 24CSE007 ", "24-cse-007", "24CSE7", "24cse007@campus.edu.in"]:
            self.assertEqual(canonical_id(raw), "24CSE007", raw)

    def test_canonical_id_rejects_garbage(self):
        self.assertIsNone(canonical_id("not-an-id"))
        self.assertIsNone(canonical_id(float("nan")))


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, cls.log, cls.stats = integrate(RAW)

    def test_one_row_per_student(self):
        self.assertEqual(len(self.df), 600)
        self.assertTrue(self.df["student_id"].is_unique)

    def test_every_source_links_to_master(self):
        for name, info in self.stats["lineage"].items():
            self.assertEqual(info.get("unmatched", 0), 0, name)

    def test_cleaned_ranges(self):
        self.assertTrue(self.df["attendance_pct"].between(0, 100).all())
        self.assertTrue(self.df["cgpa"].between(0, 10).all())
        self.assertTrue(self.df["technical_skill"].dtype.kind == "f")
        self.assertFalse(self.df["dept"].isna().any())

    def test_placement_only_for_senior_years(self):
        juniors = self.df[self.df["year"] == 2]
        self.assertTrue(juniors["aptitude_score"].isna().all())
        seniors = self.df[self.df["year"] >= 3]
        self.assertFalse(seniors["aptitude_score"].isna().any())

    def test_quality_log_records_fixes(self):
        issues = {e["issue"] for e in self.log.entries}
        self.assertTrue(any("duplicate" in i.lower() for i in issues))
        self.assertTrue(all(e["rows"] > 0 for e in self.log.entries))


class TestScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, _, _ = integrate(RAW)
        cls.scores, cls.contrib, cls.meta = scoring.compute(cls.df)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(p["weight"] for p in self.meta["pillars"]), 1.0)
        for pillar in scoring.PILLARS:
            w = sum(i[5] for i in scoring.INDICATORS if i[0] == pillar)
            self.assertAlmostEqual(w, 1.0, msg=pillar)
        w = scoring.effective_weights(self.df)
        np.testing.assert_allclose(w.sum(axis=1), 1.0)

    def test_score_bounds(self):
        self.assertTrue(self.scores["success_score"].between(0, 100).all())

    def test_explanation_adds_up(self):
        # baseline + sum(contributions) must reproduce the score exactly.
        recon = self.scores["score_baseline"] + self.contrib.sum(axis=1)
        np.testing.assert_allclose(recon, self.scores["success_score"], atol=0.11)

    def test_indicator_anchor_direction(self):
        s = scoring.indicator_score(pd.Series([0, 2, 4, 9]), 4, 0)  # backlogs: fewer is better
        self.assertEqual(list(s), [100, 50, 0, 0])

    def test_second_years_not_penalised_for_missing_placement(self):
        juniors = self.df["year"] == 2
        self.assertTrue(self.scores.loc[juniors, "pillar_placement"].isna().all())
        self.assertTrue((scoring.effective_weights(self.df).loc[juniors, "coding_score"] == 0).all())


class TestModels(unittest.TestCase):
    def test_auc_known_values(self):
        y = np.array([0, 0, 1, 1])
        self.assertEqual(models.auc(y, np.array([0.1, 0.2, 0.8, 0.9])), 1.0)
        self.assertEqual(models.auc(y, np.array([0.9, 0.8, 0.2, 0.1])), 0.0)
        self.assertEqual(models.auc(y, np.array([0.5, 0.5, 0.5, 0.5])), 0.5)

    def test_fit_recovers_signal_and_respects_signs(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"cgpa": rng.normal(7, 1, 800), "backlogs": rng.poisson(0.5, 800)})
        logit = -2 * (df["cgpa"] - 7) + 0.8 * df["backlogs"] - 1
        y = (rng.random(800) < 1 / (1 + np.exp(-logit))).astype(int).to_numpy()
        m = models.fit("t", df, y, {"cgpa": "CGPA", "backlogs": "Backlogs"})
        self.assertGreater(m.metrics["auc_test"], 0.8)
        coef = dict(zip(m.features, m.coef))
        self.assertLess(coef["cgpa"], 0)
        self.assertGreater(coef["backlogs"], 0)


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build()

    def test_every_student_has_one_segment_and_actions(self):
        keys = {s["key"] for s in self.payload["segments"]}
        for s in self.payload["students"]:
            self.assertIn(s["segment"], keys)
            self.assertTrue(1 <= len(s["actions"]) <= 5)
        self.assertEqual(sum(s["students"] for s in self.payload["segments"]), 600)

    def test_models_beat_chance(self):
        self.assertGreater(self.payload["models"]["academic"]["auc_test"], 0.75)
        self.assertGreater(self.payload["models"]["placement"]["auc_test"], 0.7)
        self.assertGreater(self.payload["validation"]["score_auc_academic"], 0.75)

    def test_score_bands_are_monotonic_against_outcomes(self):
        rates = [b["poor_academic_rate"] for b in self.payload["validation"]["by_band"]]  # Thriving -> Critical
        self.assertEqual(rates, sorted(rates))

    def test_placement_risk_only_for_seniors(self):
        for s in self.payload["students"]:
            self.assertEqual(s["place_tier"] is None, s["year"] == 2)

    def test_dashboard_data_is_valid_js_json(self):
        text = (ROOT / "dashboard" / "data.js").read_text()
        body = text.split("window.SSP_DATA = ", 1)[1].rstrip().rstrip(";")
        # Strict JSON: NaN/Infinity are not valid and must never leak into the payload.
        data = json.loads(body, parse_constant=lambda c: self.fail(f"invalid JSON constant {c}"))
        self.assertEqual(len(data["students"]), 600)

    def test_segment_rules_priority(self):
        df = pd.DataFrame({"backlogs": [0, 0], "lms_login_trend": [0.3, 1.0], "attendance_trend": [0, 0],
                           "attendance_shortage": [False, False]})
        sc = pd.DataFrame({"pillar_placement": [80, 20], "pillar_skills": [80, 20], "pillar_academic": [90, 90],
                           "success_score": [75, 65], "acad_tier": ["Low", "Low"]})
        seg = analytics.segment(df, sc)
        self.assertEqual(list(seg), ["disengaging", "achiever_unready"])


if __name__ == "__main__":
    unittest.main()
