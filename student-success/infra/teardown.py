"""Remove everything this app created, after an optional local export of the data.

    python infra/teardown.py --confirm smartcampus [--export-dir ./export]
    python infra/teardown.py --export-only --export-dir ./export     # manual backup; deletes nothing

Steps: refuse if the distribution is still in a CloudFront flat-rate subscription (cancel it in the
console first, and delete the WAF web ACL it created); optionally export every table item to a local
JSON Lines file (a slow, capacity-friendly scan); switch off deletion protection; delete the stack
(CloudFront takes a while to disable); delete the retained DynamoDB table.
Cognito users, all data and logs are gone afterwards. This cannot be undone.
"""

from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

from common import boto, outputs, parser, stack


def export(ddb, table: str, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    f = dest / f"{table}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    n, kw = 0, {"TableName": table, "Limit": 100}
    from boto3.dynamodb.types import TypeDeserializer
    des = TypeDeserializer()
    with f.open("w") as fh:
        while True:
            r = ddb.scan(**kw)
            for it in r["Items"]:
                fh.write(json.dumps({k: des.deserialize(v) for k, v in it.items()},
                                    default=lambda o: float(o) if isinstance(o, Decimal) else str(o)) + "\n")
                n += 1
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
            time.sleep(0.5)  # stay well inside the provisioned read capacity
    print(f"  exported {n} items to {f} (contains personal data: store it securely)")
    return n


def main() -> int:
    p = parser("Delete the deployment")
    p.add_argument("--confirm", help="type the stack name to confirm")
    p.add_argument("--export-dir", help="export all table items here first")
    p.add_argument("--export-only", action="store_true", help="export to --export-dir and stop (deletes nothing)")
    a = p.parse_args()
    if a.export_only:
        if not a.export_dir:
            p.error("--export-only needs --export-dir")
        out = outputs(boto("cloudformation", a.region), a.stack)
        export(boto("dynamodb", a.region), out["TableName"], Path(a.export_dir))
        return 0
    if a.confirm != a.stack:
        sys.exit(f"Refusing: pass --confirm {a.stack} to delete everything in that stack.")
    cfn = boto("cloudformation", a.region)
    s = stack(cfn, a.stack)
    if not s:
        sys.exit("Stack not found.")
    out = outputs(cfn, a.stack)
    acct = boto("sts", a.region).get_caller_identity()["Account"]
    dist_arn = f"arn:aws:cloudfront::{acct}:distribution/{out['DistributionId']}"
    try:
        subs = boto("pricing-plan-manager", "us-east-1").list_subscriptions().get("subscriptionSummaries", [])
        if any(dist_arn in (x.get("resourceArns") or []) for x in subs):
            sys.exit("The distribution is in a CloudFront flat-rate subscription. Cancel it in the CloudFront console and "
                     "delete the plan's WAF web ACL first, then run this again.")
    except SystemExit:
        raise
    except Exception:
        print("  (could not check flat-rate subscriptions; make sure none includes this distribution)")
    ddb = boto("dynamodb", a.region)
    table = out["TableName"]
    if a.export_dir:
        export(ddb, table, Path(a.export_dir))
    print("Switching off deletion protection")
    params = [{"ParameterKey": x["ParameterKey"], "UsePreviousValue": True} for x in s["Parameters"]
              if x["ParameterKey"] not in ("TableDeletionProtection", "UserPoolDeletionProtection")]
    params += [{"ParameterKey": "TableDeletionProtection", "ParameterValue": "false"},
               {"ParameterKey": "UserPoolDeletionProtection", "ParameterValue": "INACTIVE"}]
    try:
        cfn.update_stack(StackName=a.stack, UsePreviousTemplate=True, Parameters=params, Capabilities=["CAPABILITY_IAM"])
        cfn.get_waiter("stack_update_complete").wait(StackName=a.stack, WaiterConfig={"Delay": 15, "MaxAttempts": 240})
    except Exception as e:
        if "No updates" not in str(e):
            raise
    print("Deleting the stack (CloudFront distributions take several minutes to disable and delete)")
    cfn.delete_stack(StackName=a.stack)
    cfn.get_waiter("stack_delete_complete").wait(StackName=a.stack, WaiterConfig={"Delay": 20, "MaxAttempts": 270})
    print(f"Deleting retained table {table}")
    try:
        ddb.update_table(TableName=table, DeletionProtectionEnabled=False)
        ddb.get_waiter("table_exists").wait(TableName=table)
        ddb.delete_table(TableName=table)
    except ddb.exceptions.ResourceNotFoundException:
        pass
    print("Teardown complete. Check the Billing console and remove any budget or flat-rate plan you created manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
