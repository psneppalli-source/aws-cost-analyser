# API contract

Base path `/api`, JSON. Interactive schema at `/api/docs` (OpenAPI at `/api/openapi.json`).

## Conventions

| | |
|---|---|
| Authentication | `X-App-Authorization: Bearer <Cognito ID token>`. `Authorization` is reserved for CloudFront's SigV4 (OAC). Locally `Authorization` also works. |
| Writes | `POST`/`PUT`/`PATCH` must send `x-amz-content-sha256` = lowercase hex SHA-256 of the exact body bytes (empty body: `e3b0c442…b855`). A wrong hash is rejected (by Lambda when CloudFront signs it, or `400 payload_hash_mismatch` from the API); set `REQUIRE_PAYLOAD_HASH=1` to also reject writes without it (`400 payload_hash_required`). |
| Concurrency | Updates send the `version` they started from. A changed item → `409 conflict` with `details.current`. |
| Errors | `{"error": {"code", "message", "details"}}` — 400 bad_request, 401 unauthenticated, 403 forbidden, 404 not_found, 409 conflict, 422 validation_error (`details` maps field → message), 500 server_error. |
| Lists | `limit` (≤ 200) and opaque `cursor`; responses include `next_cursor`. |
| Datasets | `dataset=real` (default) or `demo`. Never mixed in one response. |
| Caching | Every response: `Cache-Control: no-store, private`. CloudFront caching is disabled for `/api/*`. |

Authorisation is enforced on every call by the role matrix (`GET /api/role-matrix`); fields a role may not
see are removed from responses.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness; reports that prediction is disabled (`method: rules`) |
| GET | `/api/auth/config` | Sign-in mode; demo personas only in local-demo mode |
| POST | `/api/auth/local/login` | Local development only (404 in AWS) |
| GET | `/api/me` | The signed-in user, their permissions, periods, departments, datasets, scoring version |
| GET | `/api/students` | Authorised directory; filters `department, year, period, risk (academic:high…), segment, status, q`; `sort=name|student_id|score|department` |
| POST | `/api/students` | Create a student master record |
| GET / PATCH | `/api/students/{ds}/{id}` | Profile (master, insight, history, recommendations, interventions, notes, corrections, `permissions`) / update master (`{data, version}`) |
| GET | `/api/students/{ds}/{id}/records` | Records, optional `category`, `period` (each with `record_key`) |
| PUT | `/api/students/{ds}/{id}/records/{category}/{period}` | Create (201), update (200), unchanged (200) or request a correction (202). Body `{data, version?}` |
| POST | `/api/students/{ds}/{id}/verify` | Verify or reject a submission `{category, record_key, decision, version}` |
| GET | `/api/verifications` | Pending student submissions this user may verify |
| PUT | `/api/students/{ds}/{id}/mentor` | Assign or clear the mentor `{mentor_sub, version}` |
| GET | `/api/entry/categories`, `/api/entry/classes`, `/api/entry/roster` | What this user may enter; their classes; a roster with saved values for a category and period |
| GET | `/api/dashboard` | KPIs, bands, trend, risk by department, segments, students needing review |
| GET | `/api/risk/academic` | Students by academic risk (`level`) |
| GET | `/api/placement` | Years 3–4 placement readiness and levels |
| GET | `/api/segments` | Segment counts and members |
| GET | `/api/interventions` | Filters `owner=me`, `status`, `department`, `overdue` |
| POST | `/api/students/{ds}/{id}/interventions` | Assign (requires `reviewed: true`, `title`, `category`, `due_date`, `review_date`, optional `owner_sub`, `evidence`) |
| PATCH | `/api/students/{ds}/{id}/interventions/{iid}` | Status, dates, owner, outcome `{result, note}`; completing requires an outcome; needs `version` |
| POST | `/api/students/{ds}/{id}/interventions/{iid}/notes` | `{text, visibility: staff|confidential}` |
| GET | `/api/staff` | Active staff (for owner pickers) |
| GET | `/api/corrections` | Correction requests (`status=pending`) |
| POST | `/api/students/{ds}/{id}/corrections/{cid}` | Approve or reject `{approve, reason}`; the requester can't approve their own |
| GET | `/api/templates`, `/api/templates/{category}.csv` | Import templates (also in `docs/csv-templates/`) |
| GET / POST | `/api/imports`, `/api/imports/preview?category&dataset&filename` | History / upload raw CSV or XLSX (≤ 2 MB, ≤ 2,000 rows) and get a preview |
| POST | `/api/imports/{iid}/commit` | Apply accepted rows in batches for ~10 s; call again while `status` is `partial`; safe to retry |
| GET | `/api/imports/{iid}` | Import status and problem rows |
| GET | `/api/role-matrix` | The canonical policy |
| GET | `/api/config/scoring` | Active scoring configuration and versions |
| POST | `/api/config/scoring/propose`, `/api/config/scoring/activate` | Versioned changes with a reason; activation can require a second administrator |
| POST | `/api/admin/recompute` | Repair stale students or recalculate all (`{dataset, all}`), time-bounded; returns `remaining` |
| POST | `/api/admin/demo/reset` | Demo dataset only; `{confirmation: "RESET DEMO", cursor}`; bounded, resumable |
| GET | `/api/audit` | `category=academic|technical`, paginated |
| GET / PUT | `/api/system/config` | Platform settings (System Administrator) |
| GET / POST | `/api/users` | Accounts (System Administrator); creation returns a one-time temporary password in Cognito mode |
| PUT | `/api/users/{sub}/roles`, `/api/users/{sub}/status` | Role assignments (never your own) / enable or disable |
| GET | `/api/assignments/{sub}` | A mentor's mentees and subjects |
| POST | `/api/assignments/subjects` | Assign or remove a subject `{mentor_sub, department, year, subject, remove}` |
