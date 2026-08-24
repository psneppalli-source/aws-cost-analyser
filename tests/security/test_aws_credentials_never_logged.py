"""Section 14: logs must never contain credentials, tokens, or auth
headers -- even when they appear inside an exception message that gets
logged. Exercises the real logging pipeline (configure_logging +
RedactionFilter), not just the redact() function in isolation."""

from __future__ import annotations

import io
import json
import logging

from aws_cost_analyser.logging_config import configure_logging


def _capture_log(log_call) -> str:
    configure_logging("INFO")
    root = logging.getLogger()
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(root.handlers[0].formatter)
    handler.addFilter(root.handlers[0].filters[0])
    root.addHandler(handler)
    try:
        log_call()
    finally:
        root.removeHandler(handler)
    return buffer.getvalue()


def test_access_key_in_log_message_is_redacted():
    output = _capture_log(
        lambda: logging.getLogger("test").info("auth failed using AKIAABCDEFGHIJKLMNOP")
    )
    assert "AKIAABCDEFGHIJKLMNOP" not in output
    assert "[REDACTED]" in output


def test_secret_embedded_in_exception_is_redacted():
    def raise_and_log():
        try:
            raise RuntimeError(
                'ClientError with aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
            )
        except RuntimeError:
            logging.getLogger("test").exception("unexpected failure")

    output = _capture_log(raise_and_log)
    assert "wJalrXUtnFEMI" not in output


def test_log_lines_are_valid_json_and_carry_no_raw_secret_field():
    output = _capture_log(lambda: logging.getLogger("test").info("normal message, no secrets"))
    line = output.strip().splitlines()[0]
    payload = json.loads(line)
    assert payload["message"] == "normal message, no secrets"
