from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "aws_cost_analyser"


def iter_source_files():
    yield from SRC_ROOT.rglob("*.py")
