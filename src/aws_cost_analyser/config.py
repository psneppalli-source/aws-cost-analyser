"""Server configuration.

All values are read exclusively from environment variables / an optional
local .env file. AWS credentials are never read here -- they come from the
boto3 default credential provider chain (see aws_client.py). This module
only holds non-secret operational settings and the optional, statically
configured cross-account role.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aws_profile: str | None = Field(default=None)

    # Cross-account access: fixed at process startup from server-side config
    # only. Never accept a role ARN as MCP tool input -- that would let a
    # malicious or compromised client pivot into an arbitrary AWS account.
    assume_role_arn: str | None = Field(default=None)
    assume_role_external_id: str | None = Field(default=None)

    # DoS / cost-control caps. These bound how much data any single tool
    # call can pull from AWS, regardless of what a client requests.
    max_result_pages: int = Field(default=10, ge=1, le=50)
    max_results_per_page: int = Field(default=100, ge=1, le=1000)
    max_time_range_days: int = Field(default=366, ge=1, le=1096)

    aws_connect_timeout_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    aws_read_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    aws_max_retry_attempts: int = Field(default=3, ge=0, le=10)

    log_level: str = Field(default="INFO")

    @field_validator("assume_role_arn")
    @classmethod
    def _validate_role_arn(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _ROLE_ARN_RE.match(v):
            raise ValueError("ASSUME_ROLE_ARN is not a well-formed IAM role ARN")
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
