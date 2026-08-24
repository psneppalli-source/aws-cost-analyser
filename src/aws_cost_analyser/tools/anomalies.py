from __future__ import annotations

from typing import Any, cast

from aws_cost_analyser.aws_client import cost_explorer_client
from aws_cost_analyser.pagination import max_pages
from aws_cost_analyser.security.untrusted import sanitize
from aws_cost_analyser.validation import CostAnomaliesRequest


def get_cost_anomalies(request: CostAnomaliesRequest) -> dict[str, Any]:
    """ce:GetAnomalies -- AWS Cost Anomaly Detection findings for a bounded
    date range, optionally scoped to one monitor."""
    client = cost_explorer_client()

    params: dict[str, Any] = {
        "DateInterval": {
            "StartDate": request.start_date.isoformat(),
            "EndDate": request.end_date.isoformat(),
        }
    }
    if request.monitor_arn:
        params["MonitorArn"] = request.monitor_arn

    anomalies: list[Any] = []
    token: str | None = None

    for _ in range(max_pages()):
        call_params = dict(params)
        if token:
            call_params["NextPageToken"] = token
        response = client.get_anomalies(**call_params)
        anomalies.extend(response.get("Anomalies", []))
        token = response.get("NextPageToken")
        if not token or len(anomalies) >= request.max_results:
            break

    truncated = token is not None
    return cast(
        "dict[str, Any]",
        sanitize(
            {
                "anomalies": anomalies[: request.max_results],
                "truncated": truncated,
            }
        ),
    )
