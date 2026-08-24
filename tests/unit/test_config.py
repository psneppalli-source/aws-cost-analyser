from __future__ import annotations

import pytest
from pydantic import ValidationError

from aws_cost_analyser.config import Settings


def test_default_settings_have_no_assume_role():
    settings = Settings(_env_file=None)
    assert settings.assume_role_arn is None


def test_valid_assume_role_arn_accepted():
    settings = Settings(_env_file=None, assume_role_arn="arn:aws:iam::123456789012:role/CostReadOnly")
    assert settings.assume_role_arn == "arn:aws:iam::123456789012:role/CostReadOnly"


@pytest.mark.parametrize(
    "bad_arn",
    [
        "not-an-arn",
        "arn:aws:iam::123:role/TooShortAccountId",
        "arn:aws:s3:::some-bucket",
        "arn:aws:iam::123456789012:role/`rm -rf /`",
        "arn:aws:iam::123456789012:user/NotARole",
    ],
)
def test_malformed_assume_role_arn_rejected(bad_arn: str):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, assume_role_arn=bad_arn)


def test_invalid_log_level_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="TRACE")


def test_max_time_range_days_bounds_enforced():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_time_range_days=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_time_range_days=10_000)
