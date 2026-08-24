"""Section 9/20: the repository must contain no real (or real-shaped)
hardcoded AWS credentials anywhere in the shipped source."""

from __future__ import annotations

import re

from tests.security._paths import iter_source_files

_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}\b")
_HARDCODED_SECRET_ASSIGNMENT_RE = re.compile(
    r'(?i)aws_secret_access_key\s*=\s*["\'][A-Za-z0-9/+=]{20,}["\']'
)


def test_no_access_key_literals_in_source():
    offenders = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8")
        if _ACCESS_KEY_RE.search(text):
            offenders.append(str(path))
    assert offenders == [], f"AWS access-key-shaped literals found in: {offenders}"


def test_no_hardcoded_secret_key_assignment():
    offenders = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8")
        if _HARDCODED_SECRET_ASSIGNMENT_RE.search(text):
            offenders.append(str(path))
    assert offenders == [], f"Hardcoded secret-key assignment found in: {offenders}"


def test_credentials_are_never_accepted_as_tool_parameters():
    """No tool function may take a parameter that looks like it accepts a
    raw credential -- credentials must come only from the boto3 provider
    chain (aws_client.py)."""
    forbidden_param_names = {
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "access_key",
        "secret_key",
        "password",
        "api_key",
    }
    offenders = []
    for path in (iter_source_files()):
        if path.name in {"aws_client.py", "config.py"}:
            continue  # these read from env/settings, not from tool input
        text = path.read_text(encoding="utf-8")
        for name in forbidden_param_names:
            if re.search(rf"\bdef\s+\w+\([^)]*\b{name}\b", text):
                offenders.append((str(path), name))
    assert offenders == [], f"Credential-shaped tool parameters found: {offenders}"
