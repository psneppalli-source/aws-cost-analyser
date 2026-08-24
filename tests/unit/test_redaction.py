from __future__ import annotations

from aws_cost_analyser.security.redaction import redact


def test_redacts_access_key_id():
    text = "failed using key AKIAABCDEFGHIJKLMNOP for the call"
    result = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert "[REDACTED]" in result


def test_redacts_secret_access_key_kv():
    text = 'aws_secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    result = redact(text)
    assert "wJalrXUtnFEMI" not in result


def test_redacts_session_token_kv():
    text = "session_token=" + "A" * 200
    result = redact(text)
    assert "A" * 200 not in result


def test_redacts_authorization_header():
    text = "Authorization: AWS4-HMAC-SHA256 Credential=AKIAABCDEFGHIJKLMNOP/..., Signature=abc123"
    result = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in result


def test_leaves_ordinary_text_untouched():
    text = "Cost Explorer returned 42 results for service EC2"
    assert redact(text) == text


def test_empty_string_is_safe():
    assert redact("") == ""
