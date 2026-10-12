# Requirements traceability

Each requirement is listed with where it is implemented and how it is verified. Tests are in `tests/test_platform.py` (local mode) and `tests/test_aws_mode.py` (simulated AWS).

Status: ✅ met · ◐ partly met (see note)

## 1. User access and roles

| Requirement | Status | Implementation | Verified by |
|---|---|---|---|
| Users log in securely | ✅ | AWS: Cognito hosted sign-in with OAuth code + PKCE, a password policy (10+ characters, mixed classes), optional TOTP MFA, no self sign-up. Local: scrypt hashes and lockout after 5 failures. Tokens are kept per tab only (`web/auth.js`, `ssp/auth.py`) | `TestAuth` (lockout, tampered token, disabled user, RS256 check against OpenSSL) |
| Administrator: manage uploads, college-wide insights | ✅ | `admin` role sees every student and has the Data uploads, Scoring rules, Audit log and Users pages | `test_scopes_per_role`, `test_cross_scope_requests_forbidden` |
| HOD: department performance, monitor interventions | ✅ | Scoped to their department (Cognito `custom:dept`). Can add notes to interventions but not change them | `test_hod_can_note_but_not_change` |
| Faculty / Mentor: assigned students, manage support actions | ✅ | Scoped to students whose roster `mentor_username` is theirs. Can create and update their mentees' interventions | `test_lifecycle` |
| Placement Officer: readiness, manage training | ✅ | Scoped to students in placement years. Can create only placement-type actions. Wellbeing details are hidden | `test_placement_officer_limited_to_placement_actions`, `test_placement_officer_cannot_see_wellbeing_details` |
| Student (optional): own progress and recommendations | ✅ | Sees only their own profile. No mentor remarks, wellbeing details, staff notes or drafts | `test_scopes_per_role`, browser check |
| Authorisation enforced by the backend | ✅ | Every route except health and login authenticates. Scope and permission checks live in `ssp/access.py` and are applied in every handler. Users can't edit their own `dept` or `student_id` (Cognito client `WriteAttributes: [name]`) | `test_cross_scope_requests_forbidden`, `test_tampered_token_rejected` |

## 2. Student data integration

| Requirement | Status | Implementation | Verified by |
|---|---|---|---|
| Import Excel or CSV for all seven categories | ✅ | 9 templates in `ssp/schemas.py`: roster, semester results, internal marks, attendance, LMS, engagement, placement, skills, feedback. `.xlsx` is read with openpyxl | `test_reupload_is_idempotent_and_excel_works` |
| Combine records on a unique student ID | ✅ | Roll numbers are normalised (`24-cse-7`, emails and lower case all map to `24CSE007`) and matched against the roster | `test_error_file_is_classified` |
| Validate required fields, formats, ranges | ✅ | Per-field type, format and range checks, plus cross-field rules (attended ≤ held, submitted ≤ due, marks ≤ max) | `test_error_file_is_classified`, `test_missing_required_column_rejects_file` |
| Highlight duplicates, unmatched IDs, missing values | ✅ | Exact duplicates are ignored. Conflicting duplicates are rejected. Unmatched IDs are listed. Blank optional values are counted per field | `test_error_file_is_classified` |
| Upload summary of accepted and rejected records | ✅ | The validation step reports accepted, rejected, duplicate, new, changed and unchanged counts, with problems row by row, before anything is imported | Browser check (upload page) |
| Keep source, reporting period, last-updated date | ✅ | Every row stores its upload ID, file, reporting period and update time. These are shown as evidence and freshness | Profile "Data freshness" card |
| Re-uploading the same records adds no duplicates | ✅ | Upserts on each category's natural key. Identical rows count as "unchanged", and a re-uploaded file triggers a warning | `test_reupload_is_idempotent_and_excel_works` |

## 3. Unified student profile

| Requirement | Status | Where on the profile |
|---|---|---|
| ID, name, department, course, year | ✅ | Header |
| Academic, attendance, engagement, placement information | ✅ | "Unified record" card, subject tables, trend sparklines |
| Current Success Score and previous scores | ✅ | Score box and "Progress across reviews" |
| Academic and placement risk flags | ✅ | Two risk cards |
| Reasons behind scores and risks | ✅ | "Why this score" (points per indicator) and the rule evidence lists |
| Assigned mentor and intervention history | ✅ | Header; interventions table with notes |
| Data freshness and completeness | ✅ | Coverage bar, missing indicators, per-source file, period, date and stale flag |

## 4. Student Success Score

| Requirement | Status | Implementation | Verified by |
|---|---|---|---|
| 0–100 score from documented indicators and weights | ✅ | `config/scoring.json`, `docs/success-score-note.md` | `test_points_add_up_and_missing_excluded` |
| Normalise before combining | ✅ | Fixed worst and best reference values per indicator (`engine.success_score`) | same |
| Show each indicator's contribution | ✅ | Points and maximum possible per indicator; they add up to the score | same |
| Missing information handled explicitly, not as zero | ✅ | Excluded and listed, with weights rescaled | `test_missing_data_makes_score_provisional_not_zero` |
| Provisional when coverage is insufficient | ✅ | Provisional below 75% coverage; withheld below 40% | same |
| Indicators appropriate to year and course | ✅ | Placement indicators only in placement years (B.Tech 3+, MCA 2+), configured per course | `test_year_appropriate_indicators` |
| Record the scoring version | ✅ | Version stored with each snapshot; earlier versions kept | `test_new_version_rescoring_keeps_old_snapshots` |

## 5. Risk identification

| Requirement | Status | Implementation | Verified by |
|---|---|---|---|
| Academic and placement risk assessed separately | ✅ | Two rule sets in the config | `test_risk_evidence_and_levels` |
| Configurable levels | ✅ | `risk.levels` (High ≥ 7, Medium ≥ 3) | `test_new_version_rescoring_keeps_old_snapshots` |
| Declining marks, backlogs, low attendance, incomplete assignments, weak placement tests | ✅ | Rules `A-SGPA-DECLINE`, `A-BACKLOG*`, `A-ATT-*`, `A-ASSIGN`, `P-CODING-*`, `P-APTITUDE-LOW`, `P-MOCK-LOW` and more | same |
| Show evidence and rule for every flag | ✅ | Rule ID, explanation, value against threshold, points, source file, period and date | Profile risk cards |
| Distinguish insufficient data from low risk | ✅ | Separate "Insufficient data" level, drawn as a dashed badge, with a "collect the data" action | `test_insufficient_data_is_not_low_risk` |
| Recalculate when data changes | ✅ | Every committed upload triggers recalculation; also after rule changes or on demand | `test_commit_triggers_recalculation` |

## 6. Interactive dashboard

| Requirement | Status | Where |
|---|---|---|
| Student counts, score distribution, risk breakdowns | ✅ | KPI tiles, histogram, academic and placement risk by department (separate charts) |
| Performance and participation trends over time | ✅ | Average score and high-risk share by review period; attendance by month; LMS logins by week; participation by month |
| Filter by department, course, year, cohort, risk level | ✅ | Filter bar on Dashboard, Students and Segments (plus segment and score band) |
| Search by name or ID | ✅ | Search box (`test_dashboard_and_filters`) |
| Open a profile from any relevant result | ✅ | Names in tables, chart clicks lead to filtered lists, KPI tiles are links |
| Highlight students needing review | ✅ | "Need review" KPI and list: high risk with no open action, overdue actions, declining or disengaging, missing data |
| Show when data was last updated | ✅ | Header ("Data updated …") and the per-source data freshness panel |

## 7. Interventions and follow-up

| Requirement | Status | Implementation | Verified by |
|---|---|---|---|
| Suggest actions linked to risk factors | ✅ | Each rule names an action; suggestions show the triggering rule IDs | Profile "Suggested actions" |
| Staff review and select an action | ✅ | "Create" opens an editable form | Browser check |
| Owner, due date, review date | ✅ | Required; the review date can't be before the due date | `test_lifecycle` |
| Notes and statuses: Open, In Progress, Completed | ✅ | Status history kept in notes; completing requires an outcome | `test_lifecycle` |
| Highlight overdue actions | ✅ | Overdue rows highlighted with days overdue; dashboard KPI | `test_lifecycle` |
| Record outcomes and compare progress across reviews | ✅ | Outcome and note recorded; baseline score and risk are stored when the action is opened and compared with the latest | Interventions "Progress" column |

## 8. Bonus

| Requirement | Status | Note |
|---|---|---|
| Meaningful support groups (the three named in the brief and others) | ✅ | Seven configurable segments, each with an owner and playbook |
| Explain why each student is in a segment | ✅ | The exact conditions met are listed on the profile |
| AI-drafted summaries grounded in records, with staff review | ◐ | Drafts are generated deterministically from the student's own records, so they cost nothing and can't invent facts. Staff edit and approve before saving, and students never see drafts. An LLM can replace the generator later behind the same review step; one isn't used because it would add cost |

## 9. Non-functional requirements

| Area | Status | Implementation |
|---|---|---|
| Privacy | ✅ | Server-side scoping and field redaction; profile views are audited; no third-party scripts or CDNs |
| Security | ✅ | TLS 1.2+ everywhere (CloudFront, Lambda URL, S3 bucket policies deny non-TLS; local `--tls`). Encrypted at rest (S3 SSE, DynamoDB). Passwords are held by Cognito (local: scrypt). Strict CSP, HSTS, frame-deny and no-sniff headers. Least-privilege IAM role. Demo passwords are random and kept out of git |
| Auditability | ✅ | Uploads, rule changes, recalculations, intervention changes, sign-ins (local mode), user changes, profile views and exports (`ssp/audit.py`) |
| Usability | ✅ | Clear labels; risk badges pair colour with text and shape; keyboard-operable tables and sorting; skip link; visible focus; light and dark themes; works at phone width |
| Performance | ✅ | On the demo data (660 students) with warm caches: dashboard 21 ms, search 1 ms, profile 3 ms (measured locally) |
| Reliability | ✅ | Validation is separate from import; each category is written as a single object; an import lock prevents concurrent writes; a failed import leaves records untouched and can be retried (`test_failed_commit_leaves_records_untouched`); S3 versioning |
| Maintainability | ✅ | All rules and thresholds live in versioned JSON, validated before activation and documented in the score note |

## 10. Deliverables

| Deliverable | Status | Where |
|---|---|---|
| Working prototype with all seven categories | ✅ | `python -m ssp.seed && python -m ssp.server`; AWS via `deploy/deploy.py` |
| Dashboard with filtering, drill-down and separate risk views | ✅ | Dashboard, Students and profile pages |
| Scoring note (indicators, weights, missing data, risk rules) | ✅ | `docs/success-score-note.md` |
| Synthetic, clearly labelled sample data | ✅ | `data/sample/` (manifest says SYNTHETIC) |
| Demo or slides from upload to follow-up | ✅ | `docs/slides.html` |
| Every score and flag traceable to source indicators | ✅ | Points per indicator; each rule's evidence names the file, period and upload |

## Known gaps

- **Live AWS deployment not yet verified.** The template passes `cfn-lint` and the AWS code paths pass against simulated AWS (moto). The stack still needs deploying to a real account with working credentials.
- **Cognito sign-in events.** In AWS mode, sign-in events are recorded by Cognito itself, not by the app's audit log. Cognito's user activity logging needs the Plus tier, which is not free.
