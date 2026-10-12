# AWS cost assumptions and preflight checklist

**Target: £0 per month. This is a target, not a guarantee.** AWS prices and free terms change, allowances are
shared with everything else in the account, and some limits depend on the account's plan. Deployment is
gated on the checks below and on explicit approval (`infra/deploy.py --approve --pricing-verified <date>`).
AWS bills in USD.

## Verification status (read this first)

The figures below were assembled on **2026-10-12**. The official AWS pricing and documentation sites could
not be reached from the build environment (its network policy blocks them), so they come from
secondary sources and from the AWS SDK's own API models. **Each one must be confirmed on the official page
before deploying.** `infra/preflight.py` prints the links and checks the account's actual state.

| Allowance assumed | Status | Official page to confirm |
|---|---|---|
| Lambda: 1,000,000 requests and 400,000 GB-seconds per month, always free | Secondary sources agree | aws.amazon.com/lambda/pricing |
| DynamoDB: 25 provisioned RCU + 25 WCU + 25 GB storage per account per region, always free; shared by all tables and GSIs | Secondary sources agree; some disagree on on-demand terms (not used here) | aws.amazon.com/dynamodb/pricing/provisioned |
| Cognito Lite / Essentials: 10,000 monthly active users free (direct sign-in), not time-limited | Secondary sources agree; **some say Lite is no longer offered to new user pools** → template parameter `UserPoolTier` can be `ESSENTIALS` (same free MAU) | aws.amazon.com/cognito/pricing |
| CloudFront flat-rate **Free** plan: USD 0/month, 1M requests and 100 GB/month, no overage charges (throttled instead) | Secondary sources; eligibility for Lambda Function URL origins **not confirmed** | aws.amazon.com/cloudfront/pricing |
| CloudFront pay-as-you-go always-free allowance (applies if not on a flat-rate plan) | Not confirmed in this review | aws.amazon.com/cloudfront/pricing |
| CloudWatch Logs: 5 GB ingestion/storage free | Not confirmed in this review | aws.amazon.com/cloudwatch/pricing |
| AWS Budgets: monitoring budgets free within a small number per account | Not confirmed in this review | aws.amazon.com/aws-cost-management/aws-budgets/pricing |
| Account plans (since 15 July 2025): new accounts choose a **Free** or **Paid** plan with up to USD 200 credits; the Free plan ends after 6 months or when credits run out | Secondary sources agree; the SDK exposes `freetier:GetAccountPlanState` (type, status, expiry, credits) which preflight reads | aws.amazon.com/free |
| CloudFront OAC for Function URLs needs `lambda:InvokeFunctionUrl` **and** `lambda:InvokeFunction` (with `InvokedViaFunctionUrl`) | AWS docs (via search) and SDK/CloudFormation schema (`InvokedViaFunctionUrl` property) | CloudFront developer guide, “Restrict access to a Lambda function URL origin” |
| A CloudFront flat-rate subscription must include exactly one distribution **and one WAF web ACL** | From the AWS SDK model for `pricing-plan-manager:CreateSubscription` | CloudFront pricing / flat-rate plan docs |

## Exact resources created (`infra/template.yaml`, one region, default `eu-west-2`)

| Resource | Configuration | Expected cost |
|---|---|---|
| DynamoDB table `{app}-data` | Provisioned 8 RCU / 8 WCU; GSIs `gsi1`, `gsi2` at 3/3 each → **14 RCU / 14 WCU total**; no autoscaling, no PITR, no backups, no streams, AWS-owned encryption | Within the shared 25/25 always-free allowance **only if other tables in the region use ≤ 11 RCU / 11 WCU** (preflight checks) |
| Lambda `{app}-api` | Python 3.12, arm64, 512 MB, 20 s timeout, reserved concurrency 5, on demand | Within free requests/compute at campus-demo volumes |
| Lambda `{app}-web` | Python 3.12, arm64, 128 MB, 5 s timeout, reserved concurrency 2 | Same |
| Two Lambda Function URLs | `AuthType: AWS_IAM`, invoked only by the distribution | No separate charge |
| Four Lambda permissions | CloudFront principal, `SourceArn` = the distribution | None |
| CloudFront distribution | Default `*.cloudfront.net` domain and certificate, PriceClass_100, `/api/*` uncached | Pay-as-you-go always-free allowance, or Free flat-rate plan if you subscribe (optional, console) |
| Origin access control, origin request policy | — | None |
| Cognito user pool + domain + app client | Lite (or Essentials), admin-created users only, TOTP optional, no SMS, default email sender | Within 10,000 free MAU |
| Two IAM roles | Least privilege | None |
| Two CloudWatch log groups | 3-day retention | Within free log allowance at expected volume |
| Optional AWS Budget | USD 1/month, email alerts (only with `--budget-email`) | Expected free (confirm budget pricing) |

Not created: S3, EC2, NAT, load balancers, API Gateway, RDS, provisioned concurrency, WAF, Route 53,
certificates, SMS, X-Ray, alarms, backups.

## Costs, by kind

**Recurring (accrue every hour whether used or not)**
* DynamoDB provisioned capacity (14 RCU / 14 WCU). Free only while the region's total stays ≤ 25 / 25.
  Raising capacity, adding autoscaling or adding tables can make this billable.
* Nothing else in this stack has an hourly charge.

**Usage-dependent (only when used beyond free allowances)**
* Lambda requests and compute beyond the monthly free tier (all functions in the account count).
* CloudFront requests and data transfer beyond the always-free allowance (or throttling, not charges, on the
  Free flat-rate plan).
* Cognito monthly active users beyond 10,000 (all pools on Lite/Essentials count); federated users have a
  much smaller allowance (not used here).
* DynamoDB storage beyond 25 GB; CloudWatch Logs beyond the free amount; data transfer out.

**Credit-dependent (hidden while credits last)**
* On new accounts, credits (up to USD 200) absorb charges. A month that shows “USD 0.00” may still have
  used credits. Check *Billing → Credits*. Usage that is free only because of credits will cost money once
  credits run out or expire.

## What happens when the plan ends

* **Free account plan**: after 6 months or when the credits are used up, the account is closed unless it is
  upgraded to the Paid plan (resources become inaccessible; data may be lost after the grace period).
  Export data first (`infra/teardown.py --export-dir`) or upgrade.
* **Paid plan**: the account continues; anything beyond the always-free allowances is billed.
* **Always-free allowances** (Lambda, DynamoDB 25/25, Cognito 10k MAU) are not time-limited (confirm), so
  this stack is designed to stay inside them on either plan.

## Expected usage (demonstration scale)

| Activity | Estimate |
|---|---|
| Page view | 1 web request + 3–8 API requests |
| 30 staff × 40 page views × 22 days | ≈ 26,000 web + ≈ 160,000 API requests/month (well under 1M) |
| API compute | ≈ 160,000 × ~0.3 s × 0.5 GB ≈ 24,000 GB-s (6 % of 400,000) |
| Data size | Demo dataset ≈ 10,000 items, well under 1 GB |
| Initial demo seed | ≈ 10,000 writes; at 8 WCU it takes roughly 20–30 minutes (adaptive retries absorb throttling) |
| Dashboards | Read per-department listings (no scans), cached for 20 s per Lambda instance |

## Preflight checklist

Automated (`python infra/preflight.py --region <region>`; deploy runs it and stops on any STOP):

- [ ] Template and operator shell cannot enable local demo sign-in (`AUTH_MODE` is `cognito`; no secret)
- [ ] No forbidden resource types (EC2/ECS/EKS/RDS, NAT, load balancers, API Gateway, provisioned
      concurrency, WAF, custom domain, SMS, backups, S3)
- [ ] Account plan type, status, expiry and remaining credits reported
- [ ] Free Tier usage from other workloads below 80 % of each allowance
- [ ] Lambda account concurrency leaves ≥ 10 unreserved after the 5 + 2 caps (else deploy with 0 and
      rely on the account limit)
- [ ] DynamoDB provisioned capacity in the region, including this app, ≤ 25 RCU and ≤ 25 WCU; on-demand
      tables flagged
- [ ] Existing Cognito pools, CloudFront distributions, flat-rate subscriptions, log storage and budgets listed

Manual (a person, before `--pricing-verified <date>`):

- [ ] Confirm every row of the *Verification status* table on the official pages
- [ ] Confirm the account plan (Free or Paid) and what happens at expiry; decide whether to upgrade
- [ ] Decide the region (single region; default `eu-west-2`)
- [ ] Decide whether to subscribe the distribution to the CloudFront Free flat-rate plan after deploying
      (optional; requires eligibility; the plan's WAF web ACL is included only while subscribed —
      cancelling the plan later requires deleting that web ACL to avoid WAF charges)
- [ ] Optionally provide `--budget-email` for a USD 1 alert

**Stop if** any automated check is STOP, any official page contradicts an assumption that this design
relies on, the account has other workloads that consume the shared allowances, or zero spend cannot be
met for any other reason. Report it rather than deploying.

## Things that would introduce cost (need review before enabling)

PITR or AWS Backup; DynamoDB autoscaling or higher capacity; on-demand tables; SMS MFA or SMS messages;
Cognito Plus; custom domains and certificates; WAF outside a flat-rate plan; provisioned concurrency;
CloudWatch alarms, dashboards, X-Ray or detailed metrics; CloudFront invalidations beyond the free number
(the design avoids them: `index.html` is revalidated, assets are content-hashed); log retention longer than
a few days; paid AI services; any second region.
