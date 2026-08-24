"""Section 16 & 31 (test_invalid_region_rejected)."""

from __future__ import annotations

import pytest

from aws_cost_analyser.validation import is_valid_region


@pytest.mark.parametrize(
    "region",
    [
        "not-a-region",
        "169.254.169.254",
        "us-east-1 OR 1=1",
        "../../etc/passwd",
        "",
        "US-EAST-1",  # AWS region codes are lowercase only
        "us-east-1; cat /etc/shadow",
    ],
)
def test_malformed_regions_rejected(region: str):
    assert is_valid_region(region) is False


@pytest.mark.parametrize(
    "region",
    ["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1", "sa-east-1", "us-gov-east-1"],
)
def test_well_formed_regions_accepted(region: str):
    assert is_valid_region(region) is True
