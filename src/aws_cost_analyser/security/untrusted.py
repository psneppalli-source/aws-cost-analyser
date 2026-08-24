"""Handling for AWS-returned string data (service names, tag keys/values,
account descriptions, anomaly monitor names, ...).

Trust boundary: everything this module touches originates from the AWS
Cost Explorer API response, which in turn can reflect values a third party
set (tags, cost category names, resource names). Those strings are DATA,
never instructions -- they must never be interpolated into a prompt, used
to select code paths, or passed to eval/exec/subprocess/dynamic import.

`sanitize` neutralizes control characters and caps length (defense against
log injection and unbounded response size) but deliberately does NOT try
to detect or strip "prompt injection" phrasing -- that would imply the
string might otherwise be treated as an instruction somewhere, which it
must not be. The correct control is architectural, not content-filtering.
"""

from __future__ import annotations

import re
from typing import Any

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MAX_STRING_LEN = 512


def sanitize_string(value: str, max_len: int = _MAX_STRING_LEN) -> str:
    cleaned = _CONTROL_CHARS.sub("", value)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "...[truncated]"
    return cleaned


def sanitize(value: Any, max_len: int = _MAX_STRING_LEN) -> Any:
    """Recursively sanitize strings inside dicts/lists returned from AWS."""
    if isinstance(value, str):
        return sanitize_string(value, max_len)
    if isinstance(value, dict):
        return {sanitize_string(str(k), 128): sanitize(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, max_len) for v in value]
    return value
