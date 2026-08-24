from __future__ import annotations

from datetime import date, timedelta

import pytest

from aws_cost_analyser.tools.tags import get_cost_tags
from aws_cost_analyser.validation import CostTagsRequest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


def test_tag_keys_are_sanitized(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    stubber.add_response(
        "get_tags",
        {"Tags": ["CostCenter", "Team\x00", "Environment"], "ReturnSize": 3, "TotalSize": 3},
    )
    monkeypatch.setattr("aws_cost_analyser.tools.tags.cost_explorer_client", lambda: client)

    request = CostTagsRequest(start_date=LAST_MONTH, end_date=TODAY)
    result = get_cost_tags(request)

    assert result["tags"] == ["CostCenter", "Team", "Environment"]
    stubber.assert_no_pending_responses()


def test_tag_key_lookup_forwards_key(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    expected_params = {
        "TimePeriod": {"Start": str(LAST_MONTH), "End": str(TODAY)},
        "TagKey": "CostCenter",
    }
    stubber.add_response(
        "get_tags",
        {"Tags": ["engineering", "sales"], "ReturnSize": 2, "TotalSize": 2},
        expected_params,
    )
    monkeypatch.setattr("aws_cost_analyser.tools.tags.cost_explorer_client", lambda: client)

    request = CostTagsRequest(start_date=LAST_MONTH, end_date=TODAY, tag_key="CostCenter")
    get_cost_tags(request)
    stubber.assert_no_pending_responses()
