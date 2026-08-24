from __future__ import annotations

from datetime import date, timedelta

import pytest

from aws_cost_analyser.tools.cost_forecast import get_cost_forecast
from aws_cost_analyser.validation import CostForecastRequest

TODAY = date.today()
NEXT_MONTH = TODAY + timedelta(days=30)


def test_forecast_returns_total_and_series(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    stubber.add_response(
        "get_cost_forecast",
        {
            "Total": {"Amount": "500.00", "Unit": "USD"},
            "ForecastResultsByTime": [
                {
                    "TimePeriod": {"Start": str(TODAY), "End": str(NEXT_MONTH)},
                    "MeanValue": "500.00",
                    "PredictionIntervalLowerBound": "450.00",
                    "PredictionIntervalUpperBound": "550.00",
                }
            ],
        },
    )
    monkeypatch.setattr("aws_cost_analyser.tools.cost_forecast.cost_explorer_client", lambda: client)

    request = CostForecastRequest(start_date=TODAY, end_date=NEXT_MONTH)
    result = get_cost_forecast(request)

    assert result["total"]["Amount"] == "500.00"
    assert len(result["forecast_results_by_time"]) == 1
    stubber.assert_no_pending_responses()
