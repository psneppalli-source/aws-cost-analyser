"""Secret redaction for anything that might reach a log line or an error
message: AWS access keys, secret keys, session tokens, and Authorization
headers. Applied as a logging filter (logging_config.py) and again
defensively wherever exception text is turned into a client-facing message
(errors.py).
"""

from __future__ import annotations

import re

_PATTERNS: list[re.Pattern[str]] = [
    # AWS access key IDs (all known prefixes), 20 chars total.
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}\b"),
    # key=value / "key": "value" style secret access keys, session tokens.
    re.compile(
        r'(?i)(aws_secret_access_key|secret[_-]?access[_-]?key)("?\s*[:=]\s*"?)'
        r"[A-Za-z0-9/+=]{20,}"
    ),
    re.compile(
        r'(?i)(aws_session_token|session[_-]?token|x-amz-security-token)("?\s*[:=]\s*"?)'
        r"[A-Za-z0-9/+=]{20,}"
    ),
    # Authorization headers (SigV4 or Bearer).
    re.compile(r"(?i)authorization(\"?\s*[:=]\s*\"?)(AWS4-HMAC-SHA256|Bearer)\s+\S+"),
]

_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Return `text` with any credential-shaped substrings replaced."""
    if not text:
        return text
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result
