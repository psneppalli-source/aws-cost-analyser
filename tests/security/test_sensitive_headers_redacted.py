"""Section 14: Authorization / SigV4 headers must never survive into a log
line or a client-facing error message.

Note: this server does not enable botocore's wire-level debug logging by
default (doing so would log full request/response headers, including
Authorization) -- see docs/security.md. This test covers the case where an
Authorization-shaped string ends up inside application-level log output or
an error message anyway (e.g. echoed inside a caught exception)."""

from __future__ import annotations

from aws_cost_analyser.errors import to_safe_error
from aws_cost_analyser.security.redaction import redact


def test_sigv4_authorization_header_redacted():
    header = (
        "Authorization: AWS4-HMAC-SHA256 "
        "Credential=AKIAABCDEFGHIJKLMNOP/20260101/us-east-1/ce/aws4_request, "
        "SignedHeaders=host;x-amz-date, Signature=deadbeef"
    )
    result = redact(header)
    assert "AKIAABCDEFGHIJKLMNOP" not in result


def test_bearer_token_redacted():
    header = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.super-secret-payload.signature"
    result = redact(header)
    assert "super-secret-payload" not in result


def test_authorization_header_never_reaches_client_facing_error():
    exc = RuntimeError(
        "request failed: Authorization: AWS4-HMAC-SHA256 Credential=AKIAABCDEFGHIJKLMNOP/..."
    )
    message = to_safe_error(exc)
    assert "AKIAABCDEFGHIJKLMNOP" not in message
    # Unknown exceptions are fully generic -- no request detail at all.
    assert message == "An internal error occurred while processing the request."
