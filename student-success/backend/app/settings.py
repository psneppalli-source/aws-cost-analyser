"""Runtime settings from environment variables.

AUTH_MODE=local-demo is for local development only. It is refused whenever
the code runs inside AWS Lambda, and the deploy script refuses to package it.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("SSP_CONFIG_DIR", ROOT / "config"))


class Settings:
    def __init__(self):
        self.auth_mode = os.environ.get("AUTH_MODE", "local-demo")
        self.storage = os.environ.get("STORAGE", "sqlite")  # sqlite | dynamodb
        self.sqlite_path = os.environ.get("SQLITE_PATH", str(ROOT / ".local" / "ssp.db"))
        self.table_name = os.environ.get("TABLE_NAME", "ssp")
        self.region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"))
        self.dynamodb_endpoint = os.environ.get("DYNAMODB_ENDPOINT") or None
        self.cognito_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
        self.cognito_client_id = os.environ.get("COGNITO_CLIENT_ID", "")
        self.local_secret = os.environ.get("LOCAL_DEMO_SECRET", "")
        self.in_lambda = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
        self.verify_payload_hash = os.environ.get("VERIFY_PAYLOAD_HASH", "1") == "1"
        # CloudFront OAC already signs the viewer's x-amz-content-sha256 into the request, so Lambda rejects a
        # mismatched body before this code runs. Requiring the header here as well is optional.
        self.require_payload_hash = os.environ.get("REQUIRE_PAYLOAD_HASH", "0") == "1"
        self.cache_seconds = int(os.environ.get("INSIGHT_CACHE_SECONDS", "20"))
        if self.in_lambda and self.auth_mode != "cognito":
            raise RuntimeError("AUTH_MODE must be 'cognito' in AWS Lambda; local demo authentication is disabled there.")
        if self.auth_mode not in ("cognito", "local-demo"):
            raise RuntimeError(f"Unknown AUTH_MODE {self.auth_mode}")


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def load_json(name: str) -> dict:
    return json.loads((CONFIG_DIR / name).read_text())


def role_matrix() -> dict:
    return load_json("role-matrix.json")


def curriculum() -> dict:
    return load_json("curriculum.json")


def default_scoring() -> dict:
    return load_json("scoring.json")
