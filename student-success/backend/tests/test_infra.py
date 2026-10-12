"""Infrastructure invariants (zero-spend shape, OAC wiring) and the operator account script against simulated AWS."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TPL = (ROOT / "infra" / "template.yaml").read_text()


def test_function_urls_are_iam_only_and_both_oac_permissions_exist():
    assert len(re.findall(r"^\s+AuthType: AWS_IAM", TPL, re.M)) == 2 and "AuthType: NONE" not in TPL
    # CloudFront needs InvokeFunctionUrl and InvokeFunction (via function URL), each scoped to the distribution
    assert TPL.count("Action: lambda:InvokeFunctionUrl") == 2
    assert TPL.count("Action: lambda:InvokeFunction\n") == 2 and TPL.count("InvokedViaFunctionUrl: true") == 2
    assert TPL.count(":distribution/${Distribution}") == 4
    assert "OriginAccessControlOriginType: lambda" in TPL and "SigningBehavior: always" in TPL


def test_api_is_never_cached_and_app_token_is_forwarded_separately():
    api = TPL[TPL.index("PathPattern: /api/*"):TPL.index("PathPattern: /config.json")]
    assert "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" in api  # Managed-CachingDisabled
    headers = re.search(r"Headers: \[(.*)\]", TPL).group(1)
    assert "x-app-authorization" in headers and "x-amz-content-sha256" not in headers  # restricted; OAC signs it
    assert not re.search(r"Headers:.*\bauthorization\b", TPL.replace("x-app-authorization", ""))


def test_zero_spend_shape():
    from app.tools.table_spec import GSI_CAPACITY, TABLE_CAPACITY
    sys.path.insert(0, str(ROOT / "infra"))
    from common import FREE_DYNAMO, PLANNED_RCU, PLANNED_WCU
    assert PLANNED_RCU == TABLE_CAPACITY["read"] + 2 * GSI_CAPACITY["read"] <= FREE_DYNAMO
    assert PLANNED_WCU == TABLE_CAPACITY["write"] + 2 * GSI_CAPACITY["write"] <= FREE_DYNAMO
    for bad in ("AWS::EC2::", "AWS::RDS::", "AWS::ApiGateway", "ProvisionedConcurrencyConfig", "NatGateway", "AWS::WAFv2::",
                "SmsConfiguration", "AWS::S3::Bucket", "AutoScaling"):
        assert bad not in TPL
    assert "BillingMode: PROVISIONED" in TPL and "PointInTimeRecoveryEnabled: false" in TPL
    assert "AllowAdminCreateUserOnly: true" in TPL and "GenerateSecret: false" in TPL and "SOFTWARE_TOKEN_MFA" in TPL
    assert "RetentionInDays: !Ref LogRetentionDays" in TPL and "AUTH_MODE: cognito" in TPL


def test_setup_accounts_against_simulated_aws(tmp_path):
    """Run the real operator script against a moto server: Cognito users, profiles and roles; idempotent rerun."""
    moto_server = pytest.importorskip("moto.server")
    import boto3

    from app.tools.table_spec import create_table
    server = moto_server.ThreadedMotoServer(port=0, verbose=False)
    server.start()
    try:
        host, port = server.get_host_and_port()
        url = f"http://{host}:{port}"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AUTH_MODE", "LOCAL_DEMO", "SQLITE", "STORAGE"))}
        env.update(AWS_ENDPOINT_URL=url, AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_REGION="eu-west-2",
                   AWS_DEFAULT_REGION="eu-west-2", DYNAMODB_ENDPOINT=url)
        env.pop("AWS_CA_BUNDLE", None)
        kw = dict(region_name="eu-west-2", endpoint_url=url, aws_access_key_id="testing", aws_secret_access_key="testing")
        create_table(boto3.client("dynamodb", **kw), "sc-data")
        pool = boto3.client("cognito-idp", **kw).create_user_pool(PoolName="sc")["UserPool"]["Id"]
        driver = (
            "import sys; sys.path.insert(0, 'infra'); import common, setup_accounts\n"
            f"o = {{'TableName': 'sc-data', 'UserPoolId': '{pool}', 'UserPoolClientId': 'client', 'SiteUrl': 'https://d1.cloudfront.net'}}\n"
            "setup_accounts.outputs = lambda c, n: o\n"
            "sys.argv = ['x'] + sys.argv[1:]\nsys.exit(setup_accounts.main())\n")
        args = [sys.executable, "-c", driver, "--admin", "it.admin", "--name", "IT", "--college-admin", "office"]
        first = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert first.returncode == 0, first.stderr[-2000:]
        lines = [x for x in first.stdout.splitlines() if x.strip().startswith(("it.admin", "office"))]
        assert len(lines) == 2 and all("existing" not in x for x in lines)  # temporary passwords shown once
        users = boto3.client("cognito-idp", **kw).list_users(UserPoolId=pool)["Users"]
        assert {u["Username"] for u in users} == {"it.admin", "office"}
        tbl = boto3.resource("dynamodb", **kw).Table("sc-data")
        profiles = tbl.query(IndexName="gsi2", KeyConditionExpression="gsi2pk = :u", ExpressionAttributeValues={":u": "USERS"})["Items"]
        roles = {p["username"]: p["roles"] for p in profiles}
        assert roles == {"it.admin": ["system_admin"], "office": ["college_admin"]}
        again = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert again.returncode == 0 and again.stdout.count("existing account") == 2  # idempotent, no new passwords
    finally:
        server.stop()
