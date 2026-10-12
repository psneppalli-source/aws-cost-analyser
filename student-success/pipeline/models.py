"""At-risk prediction models trained on last year's graduating batch.

Two logistic-regression models (implemented in NumPy, no black boxes):
  * academic risk  -> P(final CGPA < 6.0 or backlogs outstanding at graduation)
  * placement risk -> P(not placed within 6 months of graduation)

Logistic regression is chosen deliberately: it is accurate enough on tabular
campus data and is *exactly* explainable. On standardised inputs, each
feature's term coef * z is its additive push on the log-odds of risk, so the
dashboard can show "why is this student flagged" without approximation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ACADEMIC_FEATURES = {
    "cgpa": "CGPA",
    "backlogs": "Active backlogs",
    "sgpa_trend": "SGPA trend",
    "internal_pct": "Current internal marks",
    "attendance_pct": "Overall attendance",
    "attendance_trend": "Attendance trend",
    "lms_completion_pct": "Assignment completion",
    "lms_login_trend": "LMS activity trend",
    "lms_quiz_avg": "Quiz average",
    "satisfaction": "Student satisfaction",
    "mentor_rating": "Mentor rating",
}
PLACEMENT_FEATURES = {
    "cgpa": "CGPA",
    "backlogs": "Active backlogs",
    "aptitude_score": "Aptitude score",
    "coding_score": "Coding score",
    "mock_interview_rating": "Mock interview rating",
    "placement_skipped": "Skipped placement tests",
    "technical_skill": "Technical skill",
    "communication": "Communication",
    "hackathons": "Hackathons",
    "certifications": "Certifications",
    "resume_reviewed": "Resume reviewed",
}
# Domain direction of each feature: +1 = higher value means MORE risk.
# A feature whose learned coefficient contradicts this (usually collinearity
# or noise in a small cohort) is dropped and the model refit, so every
# explanation shown to faculty points in a direction they can act on.
EXPECTED_SIGN = {
    "backlogs": 1, "placement_skipped": 1,
}


@dataclass
class LogisticModel:
    name: str
    features: dict[str, str]
    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray
    intercept: float
    metrics: dict

    def _z(self, df: pd.DataFrame) -> np.ndarray:
        x = df[list(self.features)].astype(float).to_numpy()
        return (x - self.mean) / self.std

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._z(df) @ self.coef + self.intercept)

    def contributions(self, df: pd.DataFrame) -> pd.DataFrame:
        """Additive log-odds contribution of each feature vs. the average student."""
        return pd.DataFrame(self._z(df) * self.coef, index=df.index, columns=list(self.features))

    def importance(self) -> list[dict]:
        order = np.argsort(-np.abs(self.coef))
        return [{"feature": list(self.features)[i], "label": list(self.features.values())[i],
                 "coef": round(float(self.coef[i]), 3)} for i in order]


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC AUC via the rank-sum (Mann-Whitney) formulation."""
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(p, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / counts)[inv]
    pos = y == 1
    n_pos, n_neg = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _irls(z: np.ndarray, y: np.ndarray, l2: float) -> tuple[np.ndarray, float]:
    """Newton-Raphson (IRLS) with an L2 penalty; converges in a handful of steps."""
    w = np.zeros(z.shape[1])
    b = float(np.log(y.mean() / (1 - y.mean())))
    for _ in range(50):
        p = _sigmoid(z @ w + b)
        s = p * (1 - p)
        g = np.append(z.T @ (p - y) + l2 * w, np.sum(p - y))
        h_ww = (z.T * s) @ z + l2 * np.eye(len(w))
        h_wb = z.T @ s
        h = np.block([[h_ww, h_wb[:, None]], [h_wb[None, :], np.array([[s.sum()]])]])
        step = np.linalg.solve(h, g)
        w, b = w - step[:-1], b - step[-1]
        if np.abs(step).max() < 1e-8:
            break
    return w, float(b)


def fit(name: str, df: pd.DataFrame, y: np.ndarray, features: dict[str, str],
        l2: float = 1.0, seed: int = 0, high: float = 0.5, medium: float = 0.25) -> LogisticModel:
    features = dict(features)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(df))
    cut = int(0.75 * len(df))
    tr, te = idx[:cut], idx[cut:]

    dropped = []
    while True:
        x = df[list(features)].astype(float).to_numpy()
        mean, std = x[tr].mean(axis=0), x[tr].std(axis=0) + 1e-9
        z = (x - mean) / std
        w, b = _irls(z[tr], y[tr], l2)
        wrong = {f: abs(c) for f, c in zip(features, w) if np.sign(c) == -EXPECTED_SIGN.get(f, -1)}
        if not wrong:
            break
        worst = max(wrong, key=wrong.get)
        dropped.append(features.pop(worst))

    p_te = _sigmoid(z[te] @ w + b)
    flagged = p_te >= medium
    metrics = {
        "train_size": int(len(tr)),
        "test_size": int(len(te)),
        "base_rate": round(float(y.mean()), 3),
        "auc_test": round(auc(y[te], p_te), 3),
        "recall_at_medium": round(float((flagged & (y[te] == 1)).sum() / max(1, (y[te] == 1).sum())), 3),
        "precision_at_medium": round(float((flagged & (y[te] == 1)).sum() / max(1, flagged.sum())), 3),
        "thresholds": {"high": high, "medium": medium},
        "dropped_features": dropped,
    }
    return LogisticModel(name, features, mean, std, w, b, metrics)


def tier(p: float, model: LogisticModel) -> str:
    t = model.metrics["thresholds"]
    if p >= t["high"]:
        return "High"
    if p >= t["medium"]:
        return "Medium"
    return "Low"
