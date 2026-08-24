from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from aws_cost_analyser.validation import (
    CostAndUsageRequest,
    CostAnomaliesRequest,
    CostForecastRequest,
    DimensionFilter,
    DimensionValuesRequest,
    GroupBySpec,
    is_valid_region,
    validate_account_id,
)

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)
NEXT_MONTH = TODAY + timedelta(days=30)


def test_cost_and_usage_accepts_valid_request():
    req = CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY)
    assert req.granularity == "MONTHLY"
    assert req.metrics == ["UnblendedCost"]


def test_cost_and_usage_rejects_end_before_start():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=TODAY, end_date=LAST_MONTH)


def test_cost_and_usage_rejects_future_end_date():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=TODAY, end_date=NEXT_MONTH)


def test_cost_and_usage_rejects_excessive_time_range(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_TIME_RANGE_DAYS", "10")
    from aws_cost_analyser.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=TODAY - timedelta(days=20), end_date=TODAY)
    get_settings.cache_clear()


def test_cost_and_usage_rejects_unknown_metric():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY, metrics=["NotARealMetric"])


def test_cost_and_usage_rejects_max_results_over_cap():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY, max_results=100_000)


def test_group_by_dimension_must_be_allowlisted():
    with pytest.raises(ValidationError):
        GroupBySpec(type="DIMENSION", key="'; DROP TABLE users;--")


def test_group_by_tag_rejects_unsafe_characters():
    with pytest.raises(ValidationError):
        GroupBySpec(type="TAG", key="bad key\nwith\nnewlines")


def test_group_by_tag_accepts_normal_key():
    spec = GroupBySpec(type="TAG", key="CostCenter-01")
    assert spec.as_aws_group_by() == {"Type": "TAG", "Key": "CostCenter-01"}


def test_group_by_rejects_more_than_two_entries():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(
            start_date=LAST_MONTH,
            end_date=TODAY,
            group_by=[
                {"type": "DIMENSION", "key": "SERVICE"},
                {"type": "DIMENSION", "key": "REGION"},
                {"type": "DIMENSION", "key": "LINKED_ACCOUNT"},
            ],
        )


def test_dimension_filter_rejects_unknown_dimension():
    with pytest.raises(ValidationError):
        DimensionFilter(dimension="NOT_A_DIMENSION", values=["x"])


def test_dimension_filter_rejects_empty_values():
    with pytest.raises(ValidationError):
        DimensionFilter(dimension="SERVICE", values=[])


def test_cost_forecast_rejects_past_start_date():
    with pytest.raises(ValidationError):
        CostForecastRequest(start_date=LAST_MONTH, end_date=NEXT_MONTH)


def test_cost_forecast_rejects_hourly_granularity():
    with pytest.raises(ValidationError):
        CostForecastRequest(start_date=TODAY, end_date=NEXT_MONTH, granularity="HOURLY")


def test_cost_forecast_rejects_out_of_range_prediction_interval():
    with pytest.raises(ValidationError):
        CostForecastRequest(start_date=TODAY, end_date=NEXT_MONTH, prediction_interval_level=5)


def test_cost_anomalies_rejects_malformed_monitor_arn():
    with pytest.raises(ValidationError):
        CostAnomaliesRequest(
            start_date=LAST_MONTH,
            end_date=TODAY,
            monitor_arn="arn:aws:iam::123456789012:role/NotAMonitor",
        )


def test_dimension_values_rejects_unknown_dimension():
    with pytest.raises(ValidationError):
        DimensionValuesRequest(dimension="DROP TABLE", start_date=LAST_MONTH, end_date=TODAY)


@pytest.mark.parametrize(
    "region,expected",
    [
        ("us-east-1", True),
        ("eu-west-2", True),
        ("ap-southeast-1", True),
        ("us-gov-west-1", True),
        ("not-a-region", False),
        ("169.254.169.254", False),
        ("us-east-1; rm -rf /", False),
    ],
)
def test_region_allowlist(region: str, expected: bool):
    assert is_valid_region(region) is expected


def test_account_id_must_be_twelve_digits():
    assert validate_account_id("123456789012") == "123456789012"
    with pytest.raises(ValueError):
        validate_account_id("not-an-account-id")
    with pytest.raises(ValueError):
        validate_account_id("12345")
