from __future__ import annotations

from datetime import date, timedelta

import pytest

from aws_cost_analyser.tools.dimensions import get_dimension_values
from aws_cost_analyser.validation import DimensionValuesRequest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


def test_dimension_values_returned_and_capped(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    stubber.add_response(
        "get_dimension_values",
        {
            "DimensionValues": [
                {"Value": "Amazon Elastic Compute Cloud - Compute", "Attributes": {}},
                {"Value": "Amazon Simple Storage Service", "Attributes": {}},
            ],
            "ReturnSize": 2,
            "TotalSize": 2,
        },
    )
    monkeypatch.setattr(
        "aws_cost_analyser.tools.dimensions.cost_explorer_client", lambda: client
    )

    request = DimensionValuesRequest(
        dimension="SERVICE", start_date=LAST_MONTH, end_date=TODAY, max_results=1
    )
    result = get_dimension_values(request)

    assert len(result["dimension_values"]) == 1
    assert result["total_size"] == 2
    assert result["truncated"] is False  # no NextPageToken was returned
    stubber.assert_no_pending_responses()
