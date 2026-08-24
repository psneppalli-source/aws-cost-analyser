from __future__ import annotations

from typing import Any, cast

from aws_cost_analyser.aws_client import cost_explorer_client
from aws_cost_analyser.pagination import max_pages
from aws_cost_analyser.security.untrusted import sanitize
from aws_cost_analyser.validation import CostAndUsageRequest


def get_cost_and_usage(request: CostAndUsageRequest) -> dict[str, Any]:
    """ce:GetCostAndUsage -- actual/historical spend, optionally grouped by
    service/account/region/tag/cost-category, over a bounded date range."""
    client = cost_explorer_client()

    params: dict[str, Any] = {
        "TimePeriod": request.date_range.as_aws_time_period(),
        "Granularity": request.granularity,
        "Metrics": request.metrics,
    }
    if request.group_by:
        params["GroupBy"] = [g.as_aws_group_by() for g in request.group_by]
    if request.filter:
        params["Filter"] = request.filter.as_aws_filter()

    results_by_time: list[Any] = []
    group_definitions: list[Any] = []
    token: str | None = None

    for _ in range(max_pages()):
        call_params = dict(params)
        if token:
            call_params["NextPageToken"] = token
        response = client.get_cost_and_usage(**call_params)
        results_by_time.extend(response.get("ResultsByTime", []))
        group_definitions = response.get("GroupDefinitions", group_definitions)
        token = response.get("NextPageToken")
        if not token or len(results_by_time) >= request.max_results:
            break

    # True whenever AWS indicated more data exists that we chose not to
    # fetch -- whether because max_results was reached or because the
    # server-wide max_result_pages cap was hit first (see pagination.py).
    truncated = token is not None
    return cast(
        "dict[str, Any]",
        sanitize(
            {
                "results_by_time": results_by_time[: request.max_results],
                "group_definitions": group_definitions,
                "truncated": truncated,
            }
        ),
    )
