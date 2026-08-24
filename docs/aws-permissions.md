# AWS Permissions

The complete IAM policy is [`iam/read-only-policy.json`](../iam/read-only-policy.json).
It is regression-tested by `tests/security/test_iam_policy_is_read_only.py`
to guarantee it never drifts to include a wildcard action, a mutating
action, or an out-of-scope service.

## Required permissions

| Permission | AWS API | Why required | Used by |
|---|---|---|---|
| `ce:GetCostAndUsage` | Cost Explorer | Core historical spend query -- the primary purpose of this server | `get_cost_and_usage` |
| `ce:GetCostForecast` | Cost Explorer | AWS's own predicted future spend | `get_cost_forecast` |
| `ce:GetAnomalies` | Cost Anomaly Detection | Read existing anomaly-detection findings | `get_cost_anomalies` |
| `ce:GetDimensionValues` | Cost Explorer | Discover valid values (services, regions, linked accounts, ...) for use as filters | `get_dimension_values` |
| `ce:GetTags` | Cost Explorer | Discover cost allocation tag keys/values | `get_cost_tags` |
| `sts:GetCallerIdentity` | STS | Confirm which AWS account/principal is in use before/while querying cost data | `get_caller_identity` |

## Optional permissions

| Permission | Why optional | Notes |
|---|---|---|
| `sts:AssumeRole` (on the *source* identity, granted implicitly by having any IAM identity -- the actual authorization is the *target* role's trust policy) | Only needed if `ASSUME_ROLE_ARN` is configured for cross-account cost analysis | See `iam/assume-role-trust-policy.example.json` for the trust policy to attach in the **target** account. The source identity needs no extra grant beyond what it already has; AWS authorizes `AssumeRole` via the target role's trust policy, not a source-side permission. |

## Why `Resource: "*"`

AWS Cost Explorer (`ce:*`) and STS `GetCallerIdentity` do not support
resource-level permissions -- AWS does not expose ARNs for individual cost
reports, forecasts, or anomaly monitors that a `Resource` element could
scope to. `Resource: "*"` is the only value AWS's own policy grammar
accepts for these actions; this is an accepted, documented limitation of
the AWS API surface, not an oversight. Least privilege is instead achieved
by restricting the **action list** to exactly the 6 read-only calls this
server makes.

## Explicitly excluded (by design, not by accident)

The following are never requested and are covered by the threat model
(T8) and the destructive-actions regression test:

- Any `iam:*` action (user/role/policy creation or modification)
- Any mutating `ce:*`/billing-control action
- CloudTrail/logging-control actions (`cloudtrail:StopLogging`, etc.)
- `sts:AssumeRole` toward any role other than the one fixed in server
  configuration (the server never accepts a role ARN as tool input)
- Any EC2/S3/RDS/other-service permission -- this server only ever calls
  Cost Explorer and STS

## Attaching the policy

```bash
aws iam create-policy \
  --policy-name AwsCostAnalyserReadOnly \
  --policy-document file://iam/read-only-policy.json

aws iam attach-role-policy \
  --role-name <your-role> \
  --policy-arn arn:aws:iam::<account-id>:policy/AwsCostAnalyserReadOnly
```

For cross-account use, deploy `iam/assume-role-trust-policy.example.json`
(with the placeholders replaced) as the trust policy on a role in the
**target** account, and attach `iam/read-only-policy.json` as that role's
permissions policy.
