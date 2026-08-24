from __future__ import annotations

import pytest

from aws_cost_analyser.tools.identity import get_caller_identity


def test_get_caller_identity_returns_expected_fields(monkeypatch: pytest.MonkeyPatch, sts_stub):
    client, stubber = sts_stub
    stubber.add_response(
        "get_caller_identity",
        {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/readonly-cost-viewer",
            "UserId": "AIDAEXAMPLE",
        },
    )
    monkeypatch.setattr("aws_cost_analyser.tools.identity.sts_client", lambda: client)

    result = get_caller_identity()

    assert result["account"] == "123456789012"
    assert result["arn"].endswith("readonly-cost-viewer")
    stubber.assert_no_pending_responses()
