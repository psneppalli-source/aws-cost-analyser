"""Input validation for every MCP tool.

Every field an MCP client can influence is validated here against an
explicit allowlist, regex, or bound -- dates, dimensions, metrics,
granularity, ARNs, account IDs, and result-size caps. Nothing free-form
reaches the AWS SDK call. This is the primary defense against malformed or
adversarial tool-call parameters (a compromised or malicious MCP client is
in-scope per the threat model) and against accidental excessive AWS API
usage (cost/DoS).
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, model_validator

from aws_cost_analyser.config import get_settings

# --- Shared allowlists -------------------------------------------------

GRANULARITIES = ("DAILY", "MONTHLY", "HOURLY")

METRICS = (
    "AmortizedCost",
    "BlendedCost",
    "NetAmortizedCost",
    "NetUnblendedCost",
    "NormalizedUsageAmount",
    "UnblendedCost",
    "UsageQuantity",
)

FORECAST_METRICS = (
    "AMORTIZED_COST",
    "BLENDED_COST",
    "NET_AMORTIZED_COST",
    "NET_UNBLENDED_COST",
    "UNBLENDED_COST",
    "USAGE_QUANTITY",
)

DIMENSIONS = (
    "AZ",
    "INSTANCE_TYPE",
    "LEGAL_ENTITY_NAME",
    "LINKED_ACCOUNT",
    "LINKED_ACCOUNT_NAME",
    "OPERATION",
    "PLATFORM",
    "PURCHASE_TYPE",
    "SERVICE",
    "SERVICE_CODE",
    "USAGE_TYPE",
    "USAGE_TYPE_GROUP",
    "RECORD_TYPE",
    "OPERATING_SYSTEM",
    "TENANCY",
    "SCOPE",
    "SUBSCRIPTION_ID",
    "DEPLOYMENT_OPTION",
    "DATABASE_ENGINE",
    "CACHE_ENGINE",
    "INSTANCE_TYPE_FAMILY",
    "REGION",
    "BILLING_ENTITY",
    "RESERVATION_ID",
    "SAVINGS_PLAN_ARN",
    "PAYMENT_OPTION",
    "INVOICING_ENTITY",
)

GROUP_BY_TYPES = ("DIMENSION", "TAG", "COST_CATEGORY")

_TAG_OR_COST_CATEGORY_KEY_RE = re.compile(r"^[A-Za-z0-9_:./=+@-]{1,128}$")
_REGION_RE = re.compile(r"^[a-z]{2}(-gov|-iso[a-z]?)?-[a-z]+-\d$")
_ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
_MONITOR_ARN_RE = re.compile(r"^arn:aws:ce::\d{12}:anomalymonitor/[a-f0-9-]{36}$")

_MAX_GROUP_BY = 2  # AWS Cost Explorer's own limit on GroupBy entries.


def _max_results_field(default: int = 25) -> int:
    settings = get_settings()
    return min(default, settings.max_results_per_page)


class DateRange(BaseModel):
    start_date: date = Field(..., description="Inclusive start date, YYYY-MM-DD.")
    end_date: date = Field(..., description="Exclusive end date, YYYY-MM-DD.")

    @model_validator(mode="after")
    def _validate_range(self) -> DateRange:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        span_days = (self.end_date - self.start_date).days
        max_days = get_settings().max_time_range_days
        if span_days > max_days:
            raise ValueError(
                f"Requested range spans {span_days} days; the maximum allowed is {max_days}"
            )
        # AWS rejects future end dates for actuals; keep the check local so
        # the caller gets an immediate, clear validation error.
        if self.end_date > date.today():
            raise ValueError("end_date cannot be in the future")
        return self

    def as_aws_time_period(self) -> dict[str, str]:
        return {"Start": self.start_date.isoformat(), "End": self.end_date.isoformat()}


class GroupBySpec(BaseModel):
    type: str = Field(..., description=f"One of {GROUP_BY_TYPES}.")
    key: str = Field(..., description="Dimension name, tag key, or cost category name.")

    @model_validator(mode="after")
    def _validate(self) -> GroupBySpec:
        if self.type not in GROUP_BY_TYPES:
            raise ValueError(f"type must be one of {GROUP_BY_TYPES}")
        if self.type == "DIMENSION":
            if self.key not in DIMENSIONS:
                raise ValueError(f"key must be one of {DIMENSIONS} when type is DIMENSION")
        else:
            if not _TAG_OR_COST_CATEGORY_KEY_RE.match(self.key):
                raise ValueError("key contains characters not allowed in a tag/cost-category key")
        return self

    def as_aws_group_by(self) -> dict[str, str]:
        return {"Type": self.type, "Key": self.key}


class DimensionFilter(BaseModel):
    """A single-dimension equality filter -- deliberately not the full AWS
    Expression DSL (Or/And/Not-nested filter trees), to keep the input
    surface small and fully validated rather than exposing an
    attacker-composable boolean expression grammar."""

    dimension: str = Field(..., description=f"One of {DIMENSIONS}.")
    values: list[str] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def _validate(self) -> DimensionFilter:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"dimension must be one of {DIMENSIONS}")
        for v in self.values:
            if not v or len(v) > 256:
                raise ValueError("each filter value must be 1-256 characters")
        return self

    def as_aws_filter(self) -> dict[str, dict[str, object]]:
        return {"Dimensions": {"Key": self.dimension, "Values": self.values}}


class CostAndUsageRequest(BaseModel):
    start_date: date
    end_date: date
    granularity: str = Field(default="MONTHLY", description=f"One of {GRANULARITIES}.")
    metrics: list[str] = Field(default_factory=lambda: ["UnblendedCost"], max_length=len(METRICS))
    group_by: list[GroupBySpec] = Field(default_factory=list, max_length=_MAX_GROUP_BY)
    filter: DimensionFilter | None = None
    max_results: int = Field(default_factory=_max_results_field, ge=1, le=1000)

    @model_validator(mode="after")
    def _validate(self) -> CostAndUsageRequest:
        DateRange(start_date=self.start_date, end_date=self.end_date)
        if self.granularity not in GRANULARITIES:
            raise ValueError(f"granularity must be one of {GRANULARITIES}")
        if not self.metrics:
            raise ValueError("metrics must contain at least one entry")
        for m in self.metrics:
            if m not in METRICS:
                raise ValueError(f"metrics entries must be one of {METRICS}")
        settings = get_settings()
        if self.max_results > settings.max_results_per_page:
            raise ValueError(f"max_results cannot exceed {settings.max_results_per_page}")
        return self

    @property
    def date_range(self) -> DateRange:
        return DateRange(start_date=self.start_date, end_date=self.end_date)


class CostForecastRequest(BaseModel):
    start_date: date
    end_date: date
    granularity: str = Field(default="MONTHLY", description=f"One of {GRANULARITIES[:2]}.")
    metric: str = Field(default="UNBLENDED_COST", description=f"One of {FORECAST_METRICS}.")
    prediction_interval_level: int = Field(default=80, ge=51, le=99)

    @model_validator(mode="after")
    def _validate(self) -> CostForecastRequest:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.start_date < date.today():
            raise ValueError("Forecast start_date must not be in the past")
        span_days = (self.end_date - self.start_date).days
        max_days = get_settings().max_time_range_days
        if span_days > max_days:
            raise ValueError(f"Requested range spans {span_days} days; max is {max_days}")
        if self.granularity not in ("DAILY", "MONTHLY"):
            raise ValueError("granularity must be DAILY or MONTHLY for forecasts")
        if self.metric not in FORECAST_METRICS:
            raise ValueError(f"metric must be one of {FORECAST_METRICS}")
        return self


class CostAnomaliesRequest(BaseModel):
    start_date: date
    end_date: date
    monitor_arn: str | None = Field(default=None)
    max_results: int = Field(default_factory=lambda: _max_results_field(25), ge=1, le=100)

    @model_validator(mode="after")
    def _validate(self) -> CostAnomaliesRequest:
        DateRange(start_date=self.start_date, end_date=self.end_date)
        if self.monitor_arn is not None and not _MONITOR_ARN_RE.match(self.monitor_arn):
            raise ValueError("monitor_arn is not a well-formed Cost Anomaly Monitor ARN")
        return self

    @property
    def date_range(self) -> DateRange:
        return DateRange(start_date=self.start_date, end_date=self.end_date)


class DimensionValuesRequest(BaseModel):
    dimension: str = Field(..., description=f"One of {DIMENSIONS}.")
    start_date: date
    end_date: date
    search_string: str | None = Field(default=None, max_length=256)
    max_results: int = Field(default_factory=lambda: _max_results_field(50), ge=1, le=1000)

    @model_validator(mode="after")
    def _validate(self) -> DimensionValuesRequest:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"dimension must be one of {DIMENSIONS}")
        DateRange(start_date=self.start_date, end_date=self.end_date)
        return self

    @property
    def date_range(self) -> DateRange:
        return DateRange(start_date=self.start_date, end_date=self.end_date)


class CostTagsRequest(BaseModel):
    start_date: date
    end_date: date
    tag_key: str | None = Field(default=None, max_length=128)
    search_string: str | None = Field(default=None, max_length=256)
    max_results: int = Field(default_factory=lambda: _max_results_field(50), ge=1, le=1000)

    @model_validator(mode="after")
    def _validate(self) -> CostTagsRequest:
        DateRange(start_date=self.start_date, end_date=self.end_date)
        if self.tag_key is not None and not _TAG_OR_COST_CATEGORY_KEY_RE.match(self.tag_key):
            raise ValueError("tag_key contains disallowed characters")
        return self

    @property
    def date_range(self) -> DateRange:
        return DateRange(start_date=self.start_date, end_date=self.end_date)


def validate_account_id(value: str) -> str:
    if not _ACCOUNT_ID_RE.match(value):
        raise ValueError("account id must be exactly 12 digits")
    return value


def is_valid_region(value: str) -> bool:
    return bool(_REGION_RE.match(value))
