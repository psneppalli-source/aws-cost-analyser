"""Optional future model interface. DISABLED by default and not used anywhere in scoring.

Today every score, risk flag, segment and summary is produced by transparent rules (scoring.py) and is
labelled that way. If a college later validates a predictive model, it can be plugged in here:

* set PREDICTION_PROVIDER to "package.module:factory" (a function returning a RiskModel);
* the provider must run inside this account's free allowances (no paid AI service) and must be
  reviewed for cost, bias and data protection before it is enabled;
* its output would be shown next to — never instead of — the rules-based results, labelled as a
  model estimate with its version, and it must never lower a score or trigger an action by itself.

Nothing calls get_model() yet; the API exposes only whether a model is enabled (always False by default).
"""

from __future__ import annotations

import importlib
import os
from typing import Protocol


class RiskModel(Protocol):
    name: str
    version: str

    def estimate(self, features: dict[str, float | None]) -> dict:
        """Return {"probability": 0..1, "label": str, "explanation": [str, ...]} for one student-period.
        Missing features are None and must not be treated as zero."""
        ...


def get_model() -> RiskModel | None:
    spec = os.environ.get("PREDICTION_PROVIDER", "").strip()
    if not spec:
        return None
    module, _, factory = spec.partition(":")
    return getattr(importlib.import_module(module), factory or "create")()


def status() -> dict:
    return {"enabled": bool(os.environ.get("PREDICTION_PROVIDER", "").strip()), "method": "rules",
            "note": "Scores and risks are rules-based. No predictive model is in use."}
