"""Structured logging to stderr only.

The MCP stdio transport uses stdout for the protocol stream -- writing any
log output to stdout would corrupt it, so this is a correctness requirement
as well as a hygiene one. A redaction filter is attached to every handler
so credential-shaped substrings never reach a log line, even if they show
up inside a caught exception's message.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from aws_cost_analyser.security.redaction import redact


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args)
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RedactionFilter())
    root.addHandler(handler)
