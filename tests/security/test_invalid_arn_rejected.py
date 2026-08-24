"""Section 12 & 31 (test_invalid_arn_rejected): a malformed or
non-role ARN must never be accepted, whether it's the statically
configured cross-account role or a per-request monitor ARN."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from aws_cost_analyser.config import Settings
from aws_cost_analyser.validation import CostAnomaliesRequest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


@pytest.mark.parametrize(
    "bad_arn",
    [
        "arn:aws:iam::123456789012:user/NotARole",
        "arn:aws:s3:::my-bucket",
        "*",
        "arn:aws:iam::*:role/*",
        "'; DROP TABLE roles;--",
        "arn:aws:iam::123:role/TooShortAccount",
    ],
)
def test_assume_role_arn_rejects_non_role_or_malformed_arns(bad_arn: str):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, assume_role_arn=bad_arn)


@pytest.mark.parametrize(
    "bad_monitor_arn",
    [
        "arn:aws:iam::123456789012:role/SomeRole",
        "*",
        "not-an-arn-at-all",
        "arn:aws:ce::123456789012:anomalymonitor/not-a-uuid",
    ],
)
def test_anomaly_monitor_arn_rejects_malformed_input(bad_monitor_arn: str):
    with pytest.raises(ValidationError):
        CostAnomaliesRequest(start_date=LAST_MONTH, end_date=TODAY, monitor_arn=bad_monitor_arn)


def test_wildcard_role_can_never_be_assumed():
    """A wildcard/arbitrary role selection is exactly the confused-deputy
    / privilege-escalation path section 12 prohibits."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, assume_role_arn="*")
