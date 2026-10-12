"""Shared helpers for the operator scripts (preflight, deploy, accounts, smoke test, rollback, teardown).

Everything runs from the operator's machine with their AWS credentials, in ONE configurable region
(--region, else AWS_REGION, else eu-west-2). CloudFront, Free Tier and pricing-plan APIs are global (us-east-1).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
BUILD = INFRA / ".build"
TEMPLATE = INFRA / "template.yaml"
DEFAULT_REGION = "eu-west-2"

# Planned DynamoDB capacity: table + two GSIs (must match template defaults; checked by tests).
PLANNED = {"table_rcu": 8, "table_wcu": 8, "gsi_rcu": 3, "gsi_wcu": 3, "gsis": 2}
PLANNED_RCU = PLANNED["table_rcu"] + PLANNED["gsi_rcu"] * PLANNED["gsis"]
PLANNED_WCU = PLANNED["table_wcu"] + PLANNED["gsi_wcu"] * PLANNED["gsis"]
FREE_DYNAMO = 25  # always-free provisioned RCU and WCU per account per region (verify on the pricing page)
RESERVED = {"api": 5, "web": 2}

OFFICIAL_PAGES = {
    "AWS Free Tier and account plans": "https://aws.amazon.com/free/",
    "CloudFront pricing and flat-rate plans": "https://aws.amazon.com/cloudfront/pricing/",
    "Lambda pricing": "https://aws.amazon.com/lambda/pricing/",
    "DynamoDB provisioned capacity pricing": "https://aws.amazon.com/dynamodb/pricing/provisioned/",
    "Cognito pricing (Lite / Essentials)": "https://aws.amazon.com/cognito/pricing/",
    "CloudWatch pricing (logs)": "https://aws.amazon.com/cloudwatch/pricing/",
    "AWS Budgets pricing": "https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/",
    "CloudFront OAC for Lambda function URLs":
        "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda.html",
}


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION)
    p.add_argument("--stack", default="smartcampus", help="CloudFormation stack name (also the AppName prefix)")
    return p


def boto(service: str, region: str):
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 is required: pip install -r backend/requirements-dev.txt")
    return boto3.client(service, region_name=region)


def stack(cfn, name: str) -> dict | None:
    try:
        return cfn.describe_stacks(StackName=name)["Stacks"][0]
    except Exception as e:  # botocore ClientError: does not exist
        if "does not exist" in str(e):
            return None
        raise


def outputs(cfn, name: str) -> dict:
    s = stack(cfn, name)
    return {o["OutputKey"]: o["OutputValue"] for o in (s or {}).get("Outputs", [])}


def app_env(out: dict, region: str) -> None:
    """Point the backend modules at the deployed table and user pool (operator-side, Cognito mode)."""
    os.environ.update(AUTH_MODE="cognito", STORAGE="dynamodb", TABLE_NAME=out["TableName"], AWS_REGION=region,
                      COGNITO_USER_POOL_ID=out["UserPoolId"], COGNITO_CLIENT_ID=out["UserPoolClientId"])
    os.environ.pop("LOCAL_DEMO_SECRET", None)
    sys.path.insert(0, str(ROOT / "backend"))
