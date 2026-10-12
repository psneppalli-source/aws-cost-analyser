# Data dictionary

One DynamoDB table (`{AppName}-data`), provisioned capacity, two global secondary indexes (`gsi1`, `gsi2`,
projection ALL). Locally the same API runs on SQLite (`backend/app/store.py`). Keys are designed around the
access patterns below; no dashboard scans the table.

## Access patterns and keys

| Access pattern | Key |
|---|---|
| Student master, latest insight, detail, history, records, interventions, notes, corrections | `pk = STU#{dataset}#{student_id}` |
| — master | `sk = MASTER` |
| — latest insight (small; listed) | `sk = INSIGHT`, `gsi1 = DEPT#{ds}#{dept} / Y{year}#{id}` |
| — insight detail (components, flags, summary) | `sk = INSIGHTD` |
| — score history per period | `sk = SCORE#{period}` |
| — a record | `sk = REC#{category}#{period}#{subkey}` |
| — submissions awaiting verification (sparse) | `gsi1 = VERIFY#{ds} / {ts}#{id}#{sk}` |
| — intervention | `sk = INT#{id}`, `gsi1 = DEPTINT#{ds}#{dept} / {status}#{due}#{id}`, `gsi2 = OWNER#{sub} / {status}#{due}#{id}` |
| — note | `sk = NOTE#{intervention}#{ts}#{id}` |
| — correction request | `sk = CORR#{id}`, `gsi1 = DEPTCORR#{ds}#{dept} / {status}#{ts}#{id}` |
| — recalculation pending (sparse) | `sk = STALE`, `gsi2 = STALE#{ds} / {id}` |
| Account profile and assignments | `pk = USER#{sub}`; `sk = PROFILE` (`gsi2 = USERS / {username}`), `ROLE#{role}[#scope]`, `MENTEE#{ds}#{id}`, `SUBJ#{dept}#{year}#{subject}` (`gsi1 = SUBJECT#{dept}#{year}#{subject} / {sub}`) |
| Imports | `pk = IMPORT#{id}`; `sk = META` (`gsi2 = IMPORTS / {ts}#{id}`), `BATCH#{nnnn}`, `PROBLEMS` |
| Scoring configuration versions | `pk = CONFIG#SCORING`; `sk = V#{version}` and `ACTIVE` |
| Platform settings | `pk = CONFIG#SYSTEM`, `sk = CURRENT` |
| Audit history | `pk = AUDIT#{yyyy-mm-dd}`, `sk = {ts}#{id}`, `gsi2 = AUDITCAT#{academic|technical} / {ts}#{id}` |
| Dataset metadata | `pk = DATASET#{ds}`, `sk = META` (seed, generator and dataset versions) |

Items are bounded: the listed `INSIGHT` item holds only summary fields and a slim per-period map; large
detail lives in `INSIGHTD`; import rows are stored 25 per `BATCH` item; problem rows are capped at 500.

## Common record attributes

Every `REC#` item carries: `student_id`, `dataset`, `department`, `year`, `category`, `period` (YYYY-MM),
`subkey`, the category fields below, `source` (`manual`, `import:{id}`, `correction:{id}`, `seed`),
`created_at`, `created_by`, `updated_at`, `updated_by` (Cognito `sub`), `version` (optimistic concurrency),
and for imports `import_id` + `row_hash` (makes retries idempotent). Verified categories add
`verification` (`pending`/`verified`/`rejected`), `verified_by`, `verified_at`. Seeded items add
`seed_version`, `dataset_version`. Absent values are omitted, never stored as zero.

## Record categories

| Category | Fields (required*) | Natural key | Entered by | Rules |
|---|---|---|---|---|
| `academic_result` | semester*, sgpa, cgpa* (0–10), backlogs* | student, period | College Admin (import or form) | Changes after saving go to the HOD as corrections |
| `marks` | subject*, assessment*, score*, max_score* | + subject, assessment | Faculty for subjects they teach | Corrections after saving |
| `attendance` | subject*, classes_held*, classes_attended* | + subject | Faculty for subjects they teach | Corrections after saving |
| `lms` | assignments_due*, assignments_submitted*, logins* | student, period | Mentor for mentees | — |
| `engagement` | activity_type* (event/club/project), name*, role | + type, name | Activity Coordinator | Staff entries are verified on entry |
| `certification` | name*, issuer*, evidence_ref | + name | Student submits | Counts only after verification |
| `placement_assessment` | assessment_type* (aptitude/coding/mock_interview), score*, readiness_note | + type | Placement Officer | — |
| `skills` | technical*, communication* (0–100) | student, period | Placement Officer | — |
| `feedback` | satisfaction* (1–5), stress* (1–5), support_needed, comment (sensitive) | student, period | Student submits | Context only; never lowers a score; comment visible to the student, mentor, HOD, admin |

Student master (`MASTER`): `student_id` (e.g. `CSE24007`: department, admission year, number), `name`,
`department` (CSE, ECE, MECH), `year` (1–4), `programme`, `email`, `status`, `mentor_sub`, `mentor_name`,
`version`. Curriculum and reporting periods: `config/curriculum.json`.

## Derived items

`SCORE#{period}`: `score` (absent when insufficient), `indicative_score`, `status`
(`complete`/`provisional`/`insufficient_data`), `band`, `coverage`, `profile`, `rows` (component, value,
configured weight, applied weight, contribution, status), `indicators`, `sources`, `missing`, `risks`,
`segments`, `scoring_version`, `calculated_at`. `INSIGHT`/`INSIGHTD`: the latest period plus
`by_period`, `trend`, `support_needs`, `eligibility`, `summary`, `recalc_status`.

## Interventions and notes

Intervention: `title`, `category` (academic, attendance, wellbeing, placement_training, other),
`recommendation_key`, `evidence` (rule, label, observed, threshold, period), `detail`, `owner_sub`,
`owner_name`, `due_date`, `review_date`, `status` (Open / In Progress / Completed), `outcome`
(`result` improved/no_change/declined/not_assessed, `note`, `after` snapshot), `baseline` snapshot,
`reviewed_by` (the person who confirmed the recommendation), `version`. Overdue and review-due flags are
computed on read. Note: `visibility` (`staff` or `confidential`), `text`, `author`, `created_at`; students
never see notes; confidential notes are limited to mentors, HODs and the College Admin.

## Retention and backups

No point-in-time recovery or AWS Backup (both paid). See [deployment](deployment.md#backups) for the
limitations and the manual export in `infra/teardown.py --export-dir`.
