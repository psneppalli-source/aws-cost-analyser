#!/usr/bin/env python3
"""Local security gate (brief section 34).

Runs the full local check suite and prints a PASS/FAIL table. This is a
developer/CI-only script -- it invokes a fixed, hardcoded list of trusted
dev-tool commands (never user- or model-supplied input) via argument
arrays with no shell, so it is not subject to the "no arbitrary command
execution" rule that applies to the MCP server's own runtime code.

Usage: uv run python scripts/security_gate.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _run(name: str, args: list[str], allow_nonzero_as_findings: bool = False) -> CheckResult:
    try:
        proc = subprocess.run(
            args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        return CheckResult(name, False, f"tool not found: {args[0]}")

    passed = proc.returncode == 0
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
    return CheckResult(name, passed, tail or "(no output)")


def main() -> int:
    results: list[CheckResult] = []

    results.append(_run("unit tests", ["uv", "run", "pytest", "tests/unit", "-q"]))
    results.append(_run("security tests", ["uv", "run", "pytest", "tests/security", "-q"]))
    results.append(_run("ruff (lint)", ["uv", "run", "ruff", "check", "."]))
    results.append(_run("bandit (SAST)", ["uv", "run", "bandit", "-r", "src", "-q"]))
    results.append(_run("mypy (types)", ["uv", "run", "mypy", "src"]))
    results.append(_run("pip-audit (deps)", ["uv", "run", "pip-audit", "--skip-editable"]))
    results.append(
        _run(
            "detect-secrets (secret scan)",
            ["uv", "run", "detect-secrets", "scan", "--baseline", ".secrets.baseline"],
        )
    )

    print("\n=== Security Gate Results ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name}")
        if not r.passed:
            print("  " + r.detail.replace("\n", "\n  "))

    all_passed = all(r.passed for r in results)
    print("\nOverall:", "PASS" if all_passed else "FAIL")
    print(
        "\nAutomated security checks completed. "
        "Independent penetration testing has not yet been performed."
    )

    summary_path = REPO_ROOT / "docs" / "_gate_last_run.json"
    summary_path.write_text(
        json.dumps([r.__dict__ for r in results], indent=2), encoding="utf-8"
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
