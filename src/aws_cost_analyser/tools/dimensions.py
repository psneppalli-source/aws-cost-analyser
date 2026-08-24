from __future__ import annotations

from typing import Any, cast

from aws_cost_analyser.aws_client import cost_explorer_client
from aws_cost_analyser.pagination import max_pages
from aws_cost_analyser.security.untrusted import sanitize
from aws_cost_analyser.validation import DimensionValuesRequest


def get_dimension_values(request: DimensionValuesRequest) -> dict[str, Any]:
    """ce:GetDimensionValues -- valid values AWS has billed under a given
    dimension (e.g. SERVICE, REGION, LINKED_ACCOUNT) in a bounded date
    range. Useful for discovering what values to pass as filters elsewhere."""
    client = cost_explorer_client()

    params: dict[str, Any] = {
        "Dimension": request.dimension,
        "TimePeriod": request.date_range.as_aws_time_period(),
        "Context": "COST_AND_USAGE",
    }
    if request.search_string:
        params["SearchString"] = request.search_string

    values: list[Any] = []
    total_size: int | None = None
    token: str | None = None

    for _ in range(max_pages()):
        call_params = dict(params)
        if token:
            call_params["NextPageToken"] = token
        response = client.get_dimension_values(**call_params)
        values.extend(response.get("DimensionValues", []))
        total_size = response.get("TotalSize", total_size)
        token = response.get("NextPageToken")
        if not token or len(values) >= request.max_results:
            break

    truncated = token is not None
    return cast(
        "dict[str, Any]",
        sanitize(
            {
                "dimension_values": values[: request.max_results],
                "total_size": total_size,
                "truncated": truncated,
            }
        ),
    )
