"""Runtime settings, read from SSP_* environment variables.

SSP_MODE=aws   -> S3 + DynamoDB + Cognito (set by the CloudFormation stack)
SSP_MODE=local -> files + SQLite + local password login (development, tests, offline demo)
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DEFAULT_CONFIG = ROOT / "config" / "scoring.json"
SAMPLE_DIR = ROOT / "data" / "sample"

MODE = os.environ.get("SSP_MODE", "local")

# Local mode storage
LOCAL_DIR = Path(os.environ.get("SSP_LOCAL_DIR", ROOT / ".local"))

# AWS mode resources (injected as Lambda environment variables by the stack)
DATA_BUCKET = os.environ.get("SSP_DATA_BUCKET", "")
TABLE_NAME = os.environ.get("SSP_TABLE", "")
USER_POOL_ID = os.environ.get("SSP_USER_POOL_ID", "")
USER_POOL_CLIENT_ID = os.environ.get("SSP_USER_POOL_CLIENT_ID", "")
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))

# Local auth
LOCAL_JWT_SECRET = os.environ.get("SSP_LOCAL_JWT_SECRET", "")
SESSION_HOURS = int(os.environ.get("SSP_SESSION_HOURS", "8"))
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

MAX_UPLOAD_BYTES = 6 * 1024 * 1024  # Lambda function URL payload limit is 6 MB
