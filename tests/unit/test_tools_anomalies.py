from __future__ import annotations

from datetime import date, timedelta

import pytest

from aws_cost_analyser.tools.anomalies import get_cost_anomalies
from aws_cost_analyser.validation import CostAnomaliesRequest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


_MONITOR_UUID = "12345678-1234-1234-1234-123456789012"


def _anomaly(impact: str = "42.00") -> dict:
    return {
        "AnomalyId": "abc-123",
        "AnomalyStartDate": str(LAST_MONTH),
        "AnomalyEndDate": str(TODAY),
        "DimensionValue": "SERVICE",
        "MonitorArn": f"arn:aws:ce::123456789012:anomalymonitor/{_MONITOR_UUID}",
        "Impact": {"MaxImpact": float(impact), "TotalImpact": float(impact)},
        "AnomalyScore": {"CurrentScore": 75.0, "MaxScore": 90.0},
    }


def test_anomalies_bounded_by_max_results(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    stubber.add_response("get_anomalies", {"Anomalies": [_anomaly(), _anomaly()], "NextPageToken": "next"})
    monkeypatch.setattr("aws_cost_analyser.tools.anomalies.cost_explorer_client", lambda: client)

    request = CostAnomaliesRequest(start_date=LAST_MONTH, end_date=TODAY, max_results=1)
    result = get_cost_anomalies(request)

    assert len(result["anomalies"]) == 1
    assert result["truncated"] is True
    stubber.assert_no_pending_responses()


def test_anomalies_monitor_arn_forwarded(monkeypatch: pytest.MonkeyPatch, ce_stub):
    client, stubber = ce_stub
    monitor_arn = f"arn:aws:ce::123456789012:anomalymonitor/{_MONITOR_UUID}"
    expected_params = {
        "DateInterval": {"StartDate": str(LAST_MONTH), "EndDate": str(TODAY)},
        "MonitorArn": monitor_arn,
    }
    stubber.add_response("get_anomalies", {"Anomalies": []}, expected_params)
    monkeypatch.setattr("aws_cost_analyser.tools.anomalies.cost_explorer_client", lambda: client)

    request = CostAnomaliesRequest(start_date=LAST_MONTH, end_date=TODAY, monitor_arn=monitor_arn)
    get_cost_anomalies(request)
    stubber.assert_no_pending_responses()
