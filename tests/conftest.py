from __future__ import annotations

import boto3
import pytest
from botocore.stub import Stubber

from aws_cost_analyser.aws_client import _session
from aws_cost_analyser.config import get_settings


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch):
    """Settings and the boto3 session are process-cached (lru_cache); clear
    them around every test so env var changes in one test never leak into
    another."""
    monkeypatch.delenv("ASSUME_ROLE_ARN", raising=False)
    monkeypatch.delenv("ASSUME_ROLE_EXTERNAL_ID", raising=False)
    get_settings.cache_clear()
    _session.cache_clear()
    yield
    get_settings.cache_clear()
    _session.cache_clear()


@pytest.fixture
def ce_stub():
    """A Cost Explorer client backed by botocore's Stubber -- no real AWS
    calls, no real credentials required."""
    client = boto3.client(
        "ce",
        region_name="us-east-1",
        aws_access_key_id="AKIAFAKEFAKEFAKEFAKE",
        aws_secret_access_key="fake-secret-not-real-0000000000000000",
    )
    stubber = Stubber(client)
    stubber.activate()
    yield client, stubber
    stubber.deactivate()


@pytest.fixture
def sts_stub():
    client = boto3.client(
        "sts",
        region_name="us-east-1",
        aws_access_key_id="AKIAFAKEFAKEFAKEFAKE",
        aws_secret_access_key="fake-secret-not-real-0000000000000000",
    )
    stubber = Stubber(client)
    stubber.activate()
    yield client, stubber
    stubber.deactivate()
