from __future__ import annotations

from typing import Any, cast

from aws_cost_analyser.aws_client import cost_explorer_client
from aws_cost_analyser.security.untrusted import sanitize
from aws_cost_analyser.validation import CostForecastRequest


def get_cost_forecast(request: CostForecastRequest) -> dict[str, Any]:
    """ce:GetCostForecast -- AWS's own predicted spend for a future date
    range, with a confidence interval. Single bounded API call, no
    pagination."""
    client = cost_explorer_client()
    # request.metric/granularity are already validated against the fixed
    # FORECAST_METRICS / ("DAILY","MONTHLY") allowlists in validation.py --
    # the cast here only tells mypy what Pydantic + our own validator have
    # already enforced at runtime, it does not widen what is accepted.
    response = client.get_cost_forecast(
        TimePeriod={
            "Start": request.start_date.isoformat(),
            "End": request.end_date.isoformat(),
        },
        Metric=cast(Any, request.metric),
        Granularity=cast(Any, request.granularity),
        PredictionIntervalLevel=request.prediction_interval_level,
    )
    return cast(
        "dict[str, Any]",
        sanitize(
            {
                "total": response.get("Total"),
                "forecast_results_by_time": response.get("ForecastResultsByTime", []),
            }
        ),
    )
