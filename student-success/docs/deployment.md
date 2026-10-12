# Setup, deployment, rollback and teardown

## 1. Local setup (no AWS)

Requirements: Python 3.12+, Node 22.22+, npm.

```bash
cd student-success
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
cd backend
../.venv/bin/python -m app.seed          # 150 students and 9 sign-in personas (idempotent)
../.venv/bin/python local_server.py      # http://127.0.0.1:8000
```

Local mode uses SQLite (`backend/.local/ssp.db`) and **local demonstration sign-in**: choose a persona on
the login page. That mode is refused inside AWS Lambda and never packaged. For frontend development with
live reload: `python local_server.py` in one terminal and `cd frontend && npx ng serve` (proxies `/api`).

Tests:

```bash
cd backend && ../.venv/bin/python -m pytest -q        # 80+ tests incl. DynamoDB and Cognito via moto
cd frontend && npx ng test --watch=false
node e2e/journey.mjs                                   # needs Playwright; PW=/path/to/playwright if global
```

The seed is deterministic (seed `20260401`) and idempotent: rerunning never overwrites anything a person changed.
There is no reset: once staff edit records, those edits are kept.

## 2. Before deploying

1. Read [aws-cost-and-preflight.md](aws-cost-and-preflight.md) and confirm every assumption on the official
   AWS pages.
2. Configure AWS credentials for the target account in your shell (an IAM user or SSO role allowed to
   manage CloudFormation, Lambda, DynamoDB, Cognito, CloudFront, IAM roles, CloudWatch Logs and, optionally,
   Budgets). Never commit them.
3. Run `python infra/preflight.py --region eu-west-2` and resolve every STOP.

## 3. Deploy (requires explicit approval)

```bash
python infra/deploy.py --region eu-west-2 --approve --pricing-verified YYYY-MM-DD [--budget-email you@college.example]
```

What it does: preflight → `npm run build` → packages (`infra/.build/aarch64/api.zip`, `web.zip`; checked for
any local sign-in bypass) → CloudFormation change set (printed) → stack create/update → on the first run a
second update registers the CloudFront address with Cognito → direct ZIP upload to both functions (no S3).
A new CloudFront distribution takes several minutes.

Then:

```bash
# First administrators (temporary passwords are printed once):
python infra/setup_accounts.py --admin it.admin --name "IT Administrator" --email it@college.example
python infra/setup_accounts.py --college-admin office --name "College Office" --email office@college.example
# Optional: 9 persona accounts + the 150-student dataset (20–30 min at 8 WCU)
python infra/setup_accounts.py --demo-personas
# Smoke test through CloudFront, including real writes (token: sign in as mentor.arjun, copy idToken from
# sessionStorage 'ssp.session' in the browser dev tools)
python infra/smoke_test.py --token <ID token>
# End-to-end journey against the deployment
E2E_BASE_URL=https://dxxxx.cloudfront.net E2E_ID_TOKEN=<mentor ID token> node e2e/journey.mjs
```

Further accounts are created in the app by the System Administrator (*Users and roles*). Cognito sends no
SMS; the default email sender has a low daily limit, so temporary passwords are shown to the administrator
instead of being emailed.

Optional: subscribe the distribution to the CloudFront **Free** flat-rate plan in the CloudFront console
(if eligible). Note that the plan includes a WAF web ACL; if you later cancel the plan, delete that web ACL.

Redeploying code only: run the same deploy command; unchanged infrastructure is reported as “no changes”.

### AI summaries (OpenRouter, free models)

Pages with figures (Overview, Insights, Academic risk, Placement readiness, a student's profile and the student's own
dashboard) offer an **AI summary** button. The API builds the facts from what the signed-in user may already see and
sends only numbers and category labels: names, student IDs, emails, dates of birth and free-text comments are never
sent (`app/ai.py`, `scrub`). Only completely free OpenRouter models (ids ending `:free`) are used, Meta Llama and
NVIDIA Nemotron first; the function tries several in turn when the free pool is busy. Identical requests are served
from a 24-hour cache, and each user can generate 40 new summaries a day (`AI_DAILY_LIMIT`).

Set up once (the key is never stored in the repository):

```
aws ssm put-parameter --name /smartcampus/openrouter-api-key --type SecureString --value <key>
python infra/deploy.py ... --ai-key-param /smartcampus/openrouter-api-key      # '' turns AI off
```

Three more AI helpers use the same key, privacy rules, cache and daily limit (`app/ai_tools.py`):

* **Draft with AI** on the support-plan form: drafts a title, 3-5 steps and dates from that student's evidence; the
  mentor edits every field and must still tick the review box before assigning.
* **Ask about your students** (Insights, staff only): the model only translates the question into one of four checked
  queries (average, risk count, ranking, score bands, with department/year filters). The server runs it on the rows
  the user may see and writes the answer sentence itself, so no number comes from the model. Student names and IDs
  typed in a question are replaced before it is sent. If AI is busy, a keyword reader answers common questions.
* **Your weekly plan** (student dashboard): 4-6 concrete actions for the coming week from the student's own record.

Free models are shared with every OpenRouter user, so at busy times a summary may fail with "busy, try again".
Summaries come from a small model and can be wrong; the page says so.

### Readable site address (Netlify, free)

A Lambda function URL can't be renamed. `netlify.toml` lets Netlify's free plan serve the site at an address
such as `https://smart-campus.netlify.app`: it forwards every request unchanged to AWS (nothing is built or stored
on Netlify). Set up once:

1. In Netlify: *Add new site → Import an existing project → GitHub* → choose the Smart-Campus repository and
   deploy (the settings come from `netlify.toml`).
2. *Site configuration → Change site name* → `smart-campus` (or another free name).
3. Register the address for sign-in: `python infra/deploy.py ... --alias-url https://<name>.netlify.app`.

The sign-in and sign-out redirects follow whichever address the user opened. If the AWS address changes, update
the `to` line in `netlify.toml`. Netlify's free plan has monthly usage limits; heavy use may need a paid plan.

### Sign-in address (`--auth-domain`)

The college sign-in page lives at `https://<prefix>.auth.<region>.amazoncognito.com` (free). Choose a meaningful,
unused prefix with `--auth-domain smartcampus`; later deploys keep it. A user pool holds one prefix, so to change it,
first delete the current one (`aws cognito-idp delete-user-pool-domain --domain <old> --user-pool-id <pool>`), then
deploy with the new prefix. Sign-in is unavailable for those few minutes.

### Temporary mode without CloudFront (`--edge direct`)

If CloudFront is not available yet (new accounts may need AWS Support to verify the account first):

```bash
python infra/deploy.py --region eu-west-2 --approve --pricing-verified YYYY-MM-DD --edge direct
```

One **public** function URL then serves both the web app and the API (same origin, same sign-in and role checks;
every data request still needs a Cognito token). What is lost until you switch back: the IAM-protected origins
and OAC signing, the single short `*.cloudfront.net` address and any edge protection. The Lambda account
concurrency limit caps load, but a flood of requests beyond the free monthly allowance could cost money
(the budget alert emails you). When CloudFront is available, deploy again **without** `--edge direct`: the stack
adds the distribution and the web function, makes the function URL IAM-only, and the second pass registers
the new address with Cognito (the old URL stops working).

If the operator's network blocks the site host, run the smoke test with `--via-invoke` (calls the function
through the Lambda API with Function URL events).

## 4. Rollback

* **Code**: `python infra/rollback.py --approve` re-uploads the ZIPs that the last deploy replaced
  (kept locally in `infra/.build/previous/`).
* **Infrastructure**: a failed stack update rolls back automatically. To undo a successful change, check
  out the previous `infra/template.yaml` from git and deploy again.
* **Scoring configuration**: activate the previous version under *Configuration → Versions*, then
  *Recalculate everyone*.
* **Data**: there is no automatic point-in-time restore (see Backups).

## 5. Teardown

```bash
python infra/teardown.py --region eu-west-2 --confirm smartcampus [--export-dir ./export]
```

Refuses while the distribution is in a flat-rate subscription. Optionally exports every item to a local
JSON Lines file (personal data — store securely), switches off deletion protection, deletes the stack
(CloudFront takes a while to disable), then deletes the retained table. Afterwards check the Billing
console and remove any budget or plan you created by hand.

## Backups

Backups are **off** to stay at zero cost: no DynamoDB point-in-time recovery, no on-demand backups, no AWS
Backup. Consequences and mitigations:

* A deleted or overwritten item cannot be restored by AWS. The app limits the risk: every change is
  versioned and audited, verified results are changed only through approved corrections, imports are
  previewed, and teardown can export first.
* Take manual exports before risky operations: `python infra/teardown.py --export-only --export-dir ./export`
  (a slow, capacity-friendly scan to local JSON Lines; deletes nothing). There is no import-back tool; restoring
  means re-importing records through the CSV importer or writing items back with the AWS SDK.
* Enabling PITR is a paid feature — review cost before turning it on.
* Cognito users are not backed up; they can be recreated, but passwords cannot.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Your account must be verified before you can add new CloudFront resources` | New AWS accounts must be verified by AWS Support before creating CloudFront distributions. Open a free *Account and billing* case quoting the error, wait for confirmation, then deploy again. The failed stack rolls back cleanly (protection is off on the first create) |
| Pages load but `/api` returns 403 | Lambda permissions missing for the distribution (both `InvokeFunctionUrl` and `InvokeFunction`) or the function URL was recreated — redeploy |
| Writes return 400 `payload_hash_*` | A client did not send `x-amz-content-sha256` of the exact body |
| Sign-in loops back to the login page | `SiteUrl` not registered with Cognito — rerun deploy (second pass) |
| `ThrottlingException` while seeding | Expected at 8 WCU; the client retries adaptively |
| Profile shows “recalculation pending” | *Configuration → Repair pending* |
