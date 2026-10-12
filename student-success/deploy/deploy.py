"""One-command deployment to an AWS account (free-tier architecture).

    pip install boto3
    python deploy/deploy.py --region ap-south-1 --seed

Steps: create/update the CloudFormation stack, package and upload the Lambda
code, publish the frontend to S3 with its Cognito settings, invalidate the
CloudFront cache, and (with --seed) load the synthetic demo data and users.
Uses the standard AWS credential chain; see deploy/deployer-policy.json for
the permissions the deploying identity needs.
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, WaiterError

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "template.yaml"
PURE_PY_DEPS = ["openpyxl==3.1.5", "et_xmlfile==2.0.0"]


def log(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


def stack_outputs(cfn, name: str) -> dict:
    s = cfn.describe_stacks(StackName=name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in s.get("Outputs", [])}


def deploy_stack(cfn, name: str, params: dict) -> dict:
    body = TEMPLATE.read_text()
    p = [{"ParameterKey": k, "ParameterValue": v} for k, v in params.items()]
    try:
        cfn.describe_stacks(StackName=name)
        exists = True
    except ClientError:
        exists = False
    try:
        if exists:
            log(f"updating stack {name}")
            cfn.update_stack(StackName=name, TemplateBody=body, Parameters=p, Capabilities=["CAPABILITY_IAM"])
            waiter = cfn.get_waiter("stack_update_complete")
        else:
            log(f"creating stack {name} (CloudFront takes 3-6 minutes)")
            cfn.create_stack(StackName=name, TemplateBody=body, Parameters=p, Capabilities=["CAPABILITY_IAM"],
                             OnFailure="ROLLBACK", Tags=[{"Key": "app", "Value": "student-success"}])
            waiter = cfn.get_waiter("stack_create_complete")
        waiter.wait(StackName=name, WaiterConfig={"Delay": 15, "MaxAttempts": 120})
    except ClientError as e:
        if "No updates are to be performed" not in str(e):
            raise
        log("stack already up to date")
    except WaiterError:
        events = cfn.describe_stack_events(StackName=name)["StackEvents"]
        failed = [f"{e['LogicalResourceId']}: {e.get('ResourceStatusReason', '')}" for e in events if "FAILED" in e["ResourceStatus"]][:8]
        raise SystemExit("Stack deployment failed:\n  " + "\n  ".join(failed))
    return stack_outputs(cfn, name)


def build_lambda_zip() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--target", tmp, *PURE_PY_DEPS], check=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for base, prefix in ((ROOT / "ssp", "ssp"), (ROOT / "config", "config")):
                for f in base.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        z.write(f, f"{prefix}/{f.relative_to(base)}")
            for f in Path(tmp).rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and ".dist-info" not in str(f):
                    z.write(f, str(f.relative_to(tmp)))
        return buf.getvalue()


def deploy_lambda(lam, name: str, client_id: str) -> None:
    code = build_lambda_zip()
    log(f"uploading Lambda code ({len(code) / 1024:.0f} KB)")
    lam.update_function_code(FunctionName=name, ZipFile=code)
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)
    env = lam.get_function_configuration(FunctionName=name)["Environment"]["Variables"]
    env["SSP_USER_POOL_CLIENT_ID"] = client_id
    lam.update_function_configuration(FunctionName=name, Handler="ssp.lambda_handler.handler", Environment={"Variables": env})
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)


def deploy_web(s3, cf, out: dict) -> None:
    bucket = out["WebBucket"]
    site = out["SiteUrl"]
    cfg = {"mode": "cognito", "domain": out["CognitoDomain"], "clientId": out["UserPoolClientId"], "redirectUri": site}
    files = [(f, f.relative_to(ROOT / "web").as_posix()) for f in (ROOT / "web").rglob("*") if f.is_file()]
    for f, key in files:
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        s3.put_object(Bucket=bucket, Key=key, Body=f.read_bytes(), ContentType=ctype, CacheControl="no-cache")
    s3.put_object(Bucket=bucket, Key="config.js", Body=f"window.SSP_CONFIG = {json.dumps(cfg)};\n".encode(),
                  ContentType="application/javascript", CacheControl="no-cache")
    cf.create_invalidation(DistributionId=out["DistributionId"],
                           InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": str(time.time())})
    log(f"published {len(files) + 1} frontend files")


def seed(out: dict, region: str) -> None:
    env = {**os.environ, "SSP_MODE": "aws", "SSP_DATA_BUCKET": out["DataBucket"], "SSP_TABLE": out["TableName"],
           "SSP_USER_POOL_ID": out["UserPoolId"], "SSP_USER_POOL_CLIENT_ID": out["UserPoolClientId"], "AWS_REGION": region}
    log("seeding synthetic data and demo users (takes a few minutes on 5 WCU)")
    subprocess.run([sys.executable, "-m", "ssp.seed"], cwd=ROOT, env=env, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default="ssp")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"))
    ap.add_argument("--domain-prefix", help="Cognito hosted sign-in prefix (globally unique)")
    ap.add_argument("--seed", action="store_true", help="load synthetic demo data and users")
    ap.add_argument("--skip-stack", action="store_true", help="only redeploy code and frontend")
    a = ap.parse_args()
    sess = boto3.Session(region_name=a.region)
    account = sess.client("sts").get_caller_identity()["Account"]
    log(f"account {account[:4]}******** region {a.region}")
    cfn = sess.client("cloudformation")
    if a.skip_stack:
        out = stack_outputs(cfn, a.stack)
    else:
        prefix = a.domain_prefix or f"{a.stack}-{account[-6:]}"
        out = deploy_stack(cfn, a.stack, {"AppName": a.stack, "CognitoDomainPrefix": prefix})
    deploy_lambda(sess.client("lambda"), out["FunctionName"], out["UserPoolClientId"])
    deploy_web(sess.client("s3"), sess.client("cloudfront"), out)
    if a.seed:
        seed(out, a.region)
    log(f"done: {out['SiteUrl']}")


if __name__ == "__main__":
    main()
