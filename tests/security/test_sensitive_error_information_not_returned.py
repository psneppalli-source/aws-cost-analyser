"""Section 15 & 31 (test_sensitive_error_information_not_returned): stack
traces, internal file paths, environment variables, and credentials must
never reach the MCP client, end-to-end through a real tool call."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


def test_boto_client_error_surfaces_only_code_and_message(
    monkeypatch: pytest.MonkeyPatch, ce_stub
):
    client, stubber = ce_stub
    stubber.add_client_error(
        "get_cost_and_usage",
        service_error_code="AccessDeniedException",
        service_message="User arn:aws:iam::123456789012:user/bob is not authorized",
        http_status_code=403,
    )
    monkeypatch.setattr(
        "aws_cost_analyser.tools.cost_and_usage.cost_explorer_client", lambda: client
    )

    from aws_cost_analyser.server import get_cost_and_usage

    with pytest.raises(ValueError) as exc_info:
        get_cost_and_usage(start_date=LAST_MONTH, end_date=TODAY)

    message = str(exc_info.value)
    assert "AccessDeniedException" in message
    assert "Traceback" not in message
    assert "site-packages" not in message
    assert ".py" not in message
    assert "botocore" not in message


def test_unexpected_internal_exception_never_leaks_traceback_or_paths(
    monkeypatch: pytest.MonkeyPatch,
):
    def _boom():
        raise RuntimeError(
            "unexpected failure at C:\\Users\\pragn\\.aws\\credentials line 42, "
            "env AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        )

    monkeypatch.setattr("aws_cost_analyser.tools.identity.sts_client", _boom)

    from aws_cost_analyser.server import get_caller_identity

    with pytest.raises(ValueError) as exc_info:
        get_caller_identity()

    message = str(exc_info.value)
    assert message == "An internal error occurred while processing the request."
    assert ".aws" not in message
    assert "AWS_SECRET_ACCESS_KEY" not in message
    assert "wJalrXUtnFEMI" not in message
    assert "C:\\Users" not in message


def test_validation_error_message_is_safe_but_still_useful(monkeypatch: pytest.MonkeyPatch):
    from aws_cost_analyser.server import get_cost_and_usage

    with pytest.raises(ValueError) as exc_info:
        get_cost_and_usage(start_date=TODAY, end_date=LAST_MONTH)  # end before start

    message = str(exc_info.value)
    assert "Invalid request" in message
    assert "Traceback" not in message


def test_output_is_valid_json_with_no_stray_debug_fields(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    stubber.add_response(
        "get_cost_and_usage",
        {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": str(LAST_MONTH), "End": str(TODAY)},
                    "Total": {"UnblendedCost": {"Amount": "1.00", "Unit": "USD"}},
                    "Groups": [],
                    "Estimated": False,
                }
            ],
            "GroupDefinitions": [],
        },
    )
    monkeypatch.setattr(
        "aws_cost_analyser.tools.cost_and_usage.cost_explorer_client", lambda: client
    )

    from aws_cost_analyser.server import get_cost_and_usage

    raw = get_cost_and_usage(start_date=LAST_MONTH, end_date=TODAY)
    payload = json.loads(raw)
    assert set(payload.keys()) == {"results_by_time", "group_definitions", "truncated"}
