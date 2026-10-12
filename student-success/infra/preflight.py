"""Preflight: decide whether this deployment can run at zero spend, and stop if it can't.

    python infra/preflight.py --region eu-west-2

Read-only. Prints PASS / INFO / WARN / STOP lines; exits 1 if anything is STOP. It checks:
  * the template and the operator shell can't enable the local demo sign-in bypass;
  * the template contains no forbidden paid resource types;
  * the account plan (Free or Paid), its expiry and remaining credits;
  * Free Tier usage already consumed by other workloads this month;
  * Lambda account concurrency (reserved caps must leave the 10 unreserved Lambda requires);
  * DynamoDB provisioned capacity already used in the region (the always-free 25 RCU / 25 WCU is shared);
  * other Cognito pools, CloudFront distributions and flat-rate subscriptions, log storage, budgets.
It cannot read AWS's price list for free-tier terms: the official pages are listed for a human to check,
and deploy.py requires --pricing-verified with the date that was done.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys

from common import FREE_DYNAMO, OFFICIAL_PAGES, PLANNED_RCU, PLANNED_WCU, RESERVED, TEMPLATE, boto, parser

FORBIDDEN = [r"AWS::EC2::", r"AWS::ECS::", r"AWS::EKS::", r"AWS::RDS::", r"AWS::ElasticLoadBalancing", r"AWS::ApiGateway",
             r"AWS::Lambda::Version", r"ProvisionedConcurrencyConfig", r"NatGateway", r"AWS::WAFv2::", r"AWS::Route53::",
             r"AWS::CertificateManager::", r"SmsConfiguration", r"AWS::Backup::", r"PointInTimeRecoveryEnabled: true",
             r"AWS::ElastiCache::", r"AWS::OpenSearch", r"AWS::Bedrock", r"AWS::SageMaker", r"AWS::S3::Bucket"]

results: list[tuple[str, str, str]] = []


def say(level: str, check: str, detail: str = "") -> None:
    results.append((level, check, detail))
    print(f"{level:5} {check}" + (f" — {detail}" if detail else ""))


def local_safety() -> None:
    text = TEMPLATE.read_text()
    if "AUTH_MODE: cognito" not in text or re.search(r"local-demo|LOCAL_DEMO_SECRET", text):
        say("STOP", "Template authentication", "AWS functions must run with AUTH_MODE=cognito and no local demo secret")
    else:
        say("PASS", "Template authentication", "Cognito only; the API also refuses any other mode inside Lambda")
    if os.environ.get("AUTH_MODE", "cognito") != "cognito" or os.environ.get("LOCAL_DEMO_SECRET"):
        say("STOP", "Operator shell", "unset AUTH_MODE=local-demo / LOCAL_DEMO_SECRET before deploying")
    for pat in FORBIDDEN:
        if re.search(pat, text):
            say("STOP", "Forbidden resource", f"template matches {pat}")
    if not any(r[0] == "STOP" and r[1] == "Forbidden resource" for r in results):
        say("PASS", "Resource types", "no EC2/ECS/EKS/RDS, NAT, load balancer, API Gateway, provisioned concurrency, WAF, "
                                      "custom domain, SMS, backups or S3")


def account(region: str) -> None:
    sts = boto("sts", region)
    ident = sts.get_caller_identity()
    say("INFO", "Account", f"{ident['Account']} as {ident['Arn'].split(':')[-1]} in {region}")
    ft = boto("freetier", "us-east-1")
    try:
        st = ft.get_account_plan_state()
        plan, status = st.get("accountPlanType"), st.get("accountPlanStatus")
        exp = st.get("accountPlanExpirationDate")
        cred = st.get("accountPlanRemainingCredits") or {}
        detail = f"plan {plan}, status {status}, credits left {cred.get('amount', '?')} {cred.get('unit', '')}"
        if exp:
            days = (exp - dt.datetime.now(exp.tzinfo)).days
            detail += f", expires {exp:%Y-%m-%d} ({days} days)"
            if plan == "FREE" and days < 30:
                say("WARN", "Account plan", detail + ". A Free plan account closes at expiry unless upgraded; "
                                                     "upgrading makes usage beyond always-free allowances billable")
                return
        say("INFO", "Account plan", detail + (". Free plan: closes at expiry or when credits run out unless upgraded."
                                               if plan == "FREE" else ". Paid plan: usage beyond always-free allowances and "
                                                                       "credits is billed."))
    except Exception as e:
        say("WARN", "Account plan", f"could not read (freetier:GetAccountPlanState): {type(e).__name__}. Check the "
                                    "Billing console")
    try:
        usage = ft.get_free_tier_usage().get("freeTierUsages", [])
        hot = [u for u in usage if u.get("limit") and (u.get("forecastedUsageAmount") or u.get("actualUsageAmount") or 0) > 0.8 * u["limit"]]
        for u in hot:
            say("WARN", "Free Tier usage", f"{u.get('service')} {u.get('usageType')}: forecast {u.get('forecastedUsageAmount')} "
                                           f"of {u.get('limit')} {u.get('unit')} this month (other workloads)")
        say("PASS" if not hot else "WARN", "Free Tier usage", f"{len(usage)} tracked allowances; {len(hot)} above 80% forecast")
    except Exception as e:
        say("WARN", "Free Tier usage", f"could not read: {type(e).__name__}")


def reservations_possible(region: str, app: str) -> bool:
    """True if the per-function caps can be reserved while leaving the 10 unreserved Lambda requires."""
    lam = boto("lambda", region)
    unreserved = lam.get_account_settings()["AccountLimit"]["UnreservedConcurrentExecutions"]
    ours = 0
    for fn in (f"{app}-api", f"{app}-web"):
        try:
            ours += lam.get_function_concurrency(FunctionName=fn).get("ReservedConcurrentExecutions") or 0
        except Exception:
            pass
    return unreserved + ours - sum(RESERVED.values()) >= 10


def lambda_limits(region: str, app: str) -> None:
    lam = boto("lambda", region)
    s = lam.get_account_settings()["AccountLimit"]
    limit, unreserved = s["ConcurrentExecutions"], s["UnreservedConcurrentExecutions"]
    ours = 0
    for fn in (f"{app}-api", f"{app}-web"):
        try:
            ours += lam.get_function_concurrency(FunctionName=fn).get("ReservedConcurrentExecutions") or 0
        except Exception:
            pass
    left = unreserved + ours - sum(RESERVED.values())
    if left >= 10:
        say("PASS", "Lambda concurrency", f"account limit {limit}; {left} unreserved after caps of "
                                          f"{RESERVED['api']} (API) and {RESERVED['web']} (web)")
    elif limit <= 50:
        say("PASS", "Lambda concurrency", f"account limit {limit} is too low to reserve per-function caps (Lambda keeps 10 "
                                          f"unreserved); deploy.py will deploy without reservations and the account limit "
                                          f"of {limit} caps total concurrency")
    else:
        say("STOP", "Lambda concurrency", f"account limit {limit} but only {unreserved} unreserved: other functions reserve "
                                          f"capacity; review them before deploying")
    cw = boto("cloudwatch", region)
    end = dt.datetime.now(dt.timezone.utc)
    m = cw.get_metric_statistics(Namespace="AWS/Lambda", MetricName="Invocations", StartTime=end - dt.timedelta(days=30),
                                 EndTime=end, Period=86400 * 30, Statistics=["Sum"])
    inv = sum(p["Sum"] for p in m.get("Datapoints", []))
    say("WARN" if inv > 600_000 else "PASS", "Lambda invocations (all workloads, 30 days, this region)",
        f"{int(inv):,} of the 1,000,000 free requests per month (shared across regions; verify)")


def dynamo(region: str, app: str) -> None:
    ddb = boto("dynamodb", region)
    rcu = wcu = 0
    on_demand, size = [], 0
    for page in ddb.get_paginator("list_tables").paginate():
        for name in page["TableNames"]:
            if name == f"{app}-data":
                continue
            t = ddb.describe_table(TableName=name)["Table"]
            size += t.get("TableSizeBytes", 0)
            if (t.get("BillingModeSummary") or {}).get("BillingMode") == "PAY_PER_REQUEST":
                on_demand.append(name)
                continue
            rcu += t["ProvisionedThroughput"]["ReadCapacityUnits"]
            wcu += t["ProvisionedThroughput"]["WriteCapacityUnits"]
            for g in t.get("GlobalSecondaryIndexes", []):
                rcu += g["ProvisionedThroughput"]["ReadCapacityUnits"]
                wcu += g["ProvisionedThroughput"]["WriteCapacityUnits"]
    total_r, total_w = rcu + PLANNED_RCU, wcu + PLANNED_WCU
    if total_r > FREE_DYNAMO or total_w > FREE_DYNAMO:
        say("STOP", "DynamoDB capacity", f"other tables use {rcu} RCU / {wcu} WCU; with ours ({PLANNED_RCU}/{PLANNED_WCU}) "
                                         f"that is {total_r}/{total_w}, above the always-free {FREE_DYNAMO}/{FREE_DYNAMO}")
    else:
        say("PASS", "DynamoDB capacity", f"{total_r} RCU / {total_w} WCU provisioned in {region} including this app "
                                         f"(always-free {FREE_DYNAMO}/{FREE_DYNAMO} per region; verify)")
    if on_demand:
        say("WARN", "DynamoDB on-demand tables", f"{', '.join(on_demand)}: their usage is billed per request beyond free terms")
    if size > 20 * 1024 ** 3:
        say("WARN", "DynamoDB storage", f"{size / 1024 ** 3:.1f} GB already stored (25 GB free)")


def others(region: str) -> None:
    cog = boto("cognito-idp", region)
    pools = cog.list_user_pools(MaxResults=60).get("UserPools", [])
    say("INFO", "Cognito", f"{len(pools)} existing user pool(s); the 10,000 free monthly active users are shared by all pools "
                           "on Lite/Essentials (verify). This app never uses SMS")
    cf = boto("cloudfront", "us-east-1")
    dists = cf.list_distributions().get("DistributionList", {}).get("Items", []) or []
    say("INFO", "CloudFront", f"{len(dists)} existing distribution(s); pay-as-you-go always-free data transfer and requests "
                              "are shared by all of them (verify)")
    try:
        subs = boto("pricing-plan-manager", "us-east-1").list_subscriptions().get("subscriptionSummaries", [])
        tiers = [f"{s.get('planFamily')}:{s.get('planTier')}" for s in subs]
        say("INFO", "Flat-rate plans", f"{len(subs)} subscription(s) {tiers}. Subscribing this distribution to the "
                                       "CloudFront Free plan is optional and done in the console (it needs a WAF web ACL "
                                       "that is only included while the plan is active)")
    except Exception as e:
        say("INFO", "Flat-rate plans", f"could not list ({type(e).__name__})")
    logs = boto("logs", region)
    stored, forever = 0, 0
    for page in logs.get_paginator("describe_log_groups").paginate():
        for g in page["logGroups"]:
            stored += g.get("storedBytes", 0)
            forever += "retentionInDays" not in g
    say("WARN" if stored > 4 * 1024 ** 3 else "PASS", "CloudWatch Logs",
        f"{stored / 1024 ** 2:.0f} MB stored in {region}; {forever} group(s) never expire (5 GB free; verify)")
    try:
        acct = boto("sts", region).get_caller_identity()["Account"]
        n = len(boto("budgets", "us-east-1").describe_budgets(AccountId=acct).get("Budgets", []))
        say("INFO", "Budgets", f"{n} existing budget(s); adding one more only if --budget-email is given (verify budget pricing)")
    except Exception:
        say("INFO", "Budgets", "could not list budgets")


def main() -> int:
    p = parser("Zero-spend preflight (read-only)")
    a = p.parse_args()
    print(f"Preflight for stack {a.stack} in {a.region} — {dt.date.today()}\n")
    local_safety()
    try:
        account(a.region)
        lambda_limits(a.region, a.stack)
        dynamo(a.region, a.stack)
        others(a.region)
    except Exception as e:
        say("STOP", "AWS access", f"{type(e).__name__}: {e}. Configure credentials for the target account first")
    print("\nVerify on the official pages (prices and free terms change; this script can't read them):")
    for k, v in OFFICIAL_PAGES.items():
        print(f"  - {k}: {v}")
    stops = [r for r in results if r[0] == "STOP"]
    print(f"\n{'STOP' if stops else 'OK'}: {len(stops)} blocking issue(s). Zero cost is a target, never a guarantee.")
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main())
