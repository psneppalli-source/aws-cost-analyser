# Smart Campus Analytics — Predict, Optimise and Improve Student Success

Unified student profiles, explainable Success Scores, independent academic and placement risk, segments,
role-specific data entry and imports, and tracked interventions — for College Admins, HODs, Faculty/Mentors,
Placement Officers, Activity Coordinators, Students and System Administrators.

**Stack:** Angular 21 + TypeScript · Python FastAPI on AWS Lambda (Function URLs via Mangum) · DynamoDB
(single table, provisioned capacity) · Cognito (admin-provisioned, PKCE) · CloudFront with Origin Access
Control · CloudFormation. Rules-based analytics only — no paid AI; an optional model interface is disabled.

**Cost:** designed to stay within AWS always-free allowances, targeting £0/month. That is a target, not a
guarantee — read [docs/aws-cost-and-preflight.md](docs/aws-cost-and-preflight.md). Deployment requires
explicit approval and a passing preflight.

## Quick start (local, no AWS)

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
cd backend && ../.venv/bin/python -m app.seed && ../.venv/bin/python local_server.py   # http://127.0.0.1:8000
```

Choose a persona on the login page (local demonstration sign-in; refused in AWS). Switch the topbar dataset
to **Demo (synthetic)** to see the 150 fictional students.

## Deliverables

| | |
|---|---|
| Frontend | `frontend/` — 15 screens: login, overview, students, profile with trends, academic risk, placement, segments, data entry, imports, interventions, approvals & verification, role matrix, configuration (scoring, recalculation, demo reset, platform settings), audit, users & assignments |
| Backend | `backend/app/`, Lambda handlers `backend/lambda_api.py`, `backend/web_handler.py` |
| Infrastructure | `infra/template.yaml`; `infra/preflight.py`, `deploy.py`, `setup_accounts.py`, `smoke_test.py`, `rollback.py`, `teardown.py` |
| Seed generator | `backend/app/seed.py` (`python -m app.seed`; deterministic, idempotent, labelled synthetic) |
| Role matrix | `config/role-matrix.json` (canonical) → [docs/role-matrix.md](docs/role-matrix.md) (generated) |
| CSV templates | [docs/csv-templates/](docs/csv-templates/) (also downloadable in the app) |
| Tests | `backend/tests/` (pytest, incl. moto DynamoDB/Cognito), `frontend/src/**/*.spec.ts`, `e2e/journey.mjs` |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Data dictionary | [docs/data-dictionary.md](docs/data-dictionary.md) |
| API contract | [docs/api.md](docs/api.md) |
| Scoring and risk note | [docs/scoring-methodology.md](docs/scoring-methodology.md) |
| Cost assumptions and preflight | [docs/aws-cost-and-preflight.md](docs/aws-cost-and-preflight.md) |
| Deploy, rollback, teardown, backups | [docs/deployment.md](docs/deployment.md) |
| Five-minute demo | [docs/demo-script.md](docs/demo-script.md) |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q
cd frontend && npx ng test --watch=false
node e2e/journey.mjs        # seed → sign in → dashboard → enter data → score → intervention → outcome
```

Regenerate derived docs after changing config: `python -m app.tools.render_role_matrix` and
`python -m app.tools.export_templates` (from `backend/`; tests fail if they are out of date).
