"""boto3 session/client construction.

Credentials come exclusively from boto3's standard provider chain (env
vars, shared config/profile, SSO, EC2/ECS/Lambda role, web identity). This
module never accepts, stores, or logs a credential value. The only
"identity" decision made here is an optional, statically configured
cross-account AssumeRole -- fixed at process startup, never selectable by
tool input.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from aws_cost_analyser.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_ce.client import CostExplorerClient
    from mypy_boto3_sts.client import STSClient

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _boto_config() -> Config:
    settings = get_settings()
    return Config(
        connect_timeout=settings.aws_connect_timeout_seconds,
        read_timeout=settings.aws_read_timeout_seconds,
        retries={"max_attempts": settings.aws_max_retry_attempts, "mode": "standard"},
        user_agent_extra="aws-cost-analyser-mcp/0.1.0",
    )


def _base_session() -> boto3.Session:
    settings = get_settings()
    return boto3.Session(profile_name=settings.aws_profile or None)


@lru_cache(maxsize=1)
def _session() -> boto3.Session:
    """Return the session to build service clients from.

    If ASSUME_ROLE_ARN is configured, assumes it once at startup via STS and
    returns a session backed by those temporary credentials. Otherwise
    returns the default-chain session directly.
    """
    settings = get_settings()
    base = _base_session()
    if not settings.assume_role_arn:
        return base

    sts = base.client("sts", config=_boto_config())
    logger.info("Assuming configured cross-account role for Cost Explorer access")
    if settings.assume_role_external_id:
        response = sts.assume_role(
            RoleArn=settings.assume_role_arn,
            RoleSessionName="aws-cost-analyser-mcp",
            ExternalId=settings.assume_role_external_id,
        )
    else:
        response = sts.assume_role(
            RoleArn=settings.assume_role_arn,
            RoleSessionName="aws-cost-analyser-mcp",
        )
    creds = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def cost_explorer_client() -> CostExplorerClient:
    with _lock:
        session = _session()
    # Cost Explorer is a single global endpoint hosted in us-east-1
    # regardless of which region's resources it reports on.
    return session.client("ce", region_name="us-east-1", config=_boto_config())


def sts_client() -> STSClient:
    with _lock:
        session = _session()
    return session.client("sts", config=_boto_config())
