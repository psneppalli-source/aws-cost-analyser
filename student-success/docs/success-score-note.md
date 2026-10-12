# Student Success Score and risk rules: a short note

Everything below is defined in one versioned file, [`config/scoring.json`](../config/scoring.json) (rules version `2026.1`). An administrator can change weights, thresholds and rules from the **Scoring rules** page. Each change:

- must have a new version number and a reason
- is checked for errors before it is accepted
- re-scores every student
- is recorded in the audit log

Scores calculated under earlier versions are kept, so any past result can be reproduced.

## 1. Indicators and weights

There are 23 indicators from seven data categories, grouped into seven pillars. An indicator's overall weight is its pillar's weight × its weight within the pillar.

| Pillar (weight) | Indicators (weight within pillar) | Source upload |
|---|---|---|
| **Academic (30%)** | CGPA (45%), active backlogs (25%), internal marks average (15%), SGPA trend (15%) | Semester results, internal marks |
| **Attendance (15%)** | Overall % (60%), lowest-subject % (20%), change within the term (20%) | Attendance |
| **LMS (15%)** | Assignments submitted (40%), logins per week (20%), quiz average (20%), activity in the last 4 weeks vs the first 4 (20%) | LMS activity |
| **Placement readiness (15%)** | Aptitude (35%), coding (40%), mock interview (25%). Placement years only | Placement assessments |
| **Skills (10%)** | Technical (50%), communication (25%), problem solving (25%) | Skills assessments |
| **Engagement (10%)** | Events (30%), clubs (20%), projects and hackathons (25%), certifications (25%), all over the last 12 months | Activity log |
| **Feedback (5%)** | Student satisfaction (50%), faculty/mentor rating (50%) | Feedback survey |

## 2. Normalisation and combination

1. **Normalise.** Each indicator is converted to 0–100 between a fixed "worst" and "best" value, and anything outside that range is clipped. For example, attendance of 60% scores 0 and 95% scores 100. For backlogs, 4 or more scores 0 and none scores 100. Fixed reference values are used rather than class rank, so a score means the same thing every term.
2. **Weight.** Points for an indicator = (its weight ÷ the total weight of indicators that have data) × its 0–100 score.
3. **Add up.** The Success Score is the sum of the points, so it can be traced exactly. A student's profile lists every indicator with its value, its 0–100 score and its points against the maximum possible. The points add up to the score shown.

**Bands:** Thriving ≥ 70 · On track 55–70 · Needs attention 40–55 · Critical < 40.

## 3. Missing information

- **Missing is never treated as zero.** An indicator with no data is excluded, the remaining weights are rescaled, and the indicator appears as "missing" on the profile.
- **Coverage** is the share of applicable indicator weight that has data:
  - Below 75%, or with no academic or no attendance data at all, the score is shown as **Provisional**.
  - Below 40%, the score is **withheld** ("Not enough data") and the student isn't placed in a segment.
- **Year and course.** Placement indicators apply only in the placement years: B.Tech year 3 onwards, MCA year 2. For other years they are marked "not applicable" and don't count against coverage.
- **Activity log.** Once the log has been uploaded, a student with no rows genuinely took part in nothing, so their counts are 0. Before the log is uploaded at all, the counts are missing.
- **Freshness.** Each profile shows, for every source, the file, reporting period and last-updated date of the data used. Sources older than their configured age are marked stale.

## 4. Risk rules

Academic and placement risk are assessed separately, using point-based rules. Every rule that fires is shown with:
- the student's value and the threshold it crossed
- the points it adds
- the source file, reporting period and date

| Academic rule | Points | | Placement rule (placement years only) | Points |
|---|---|---|---|---|
| CGPA < 6.0 | 3 | | Coding score < 40 | 3 |
| CGPA 6.0–6.5 | 1 | | Coding score 40–55 | 1 |
| 1–2 active backlogs | 2 | | Aptitude score < 45 | 2 |
| 3+ active backlogs | 4 | | Mock interview < 2.5/5 | 2 |
| Attendance < 75% (exam-eligibility rule) | 3 | | Any active backlog (recruiters' rule) | 3 |
| Attendance < 65% | +2 | | CGPA < 6.0 (common recruiter cut-off) | 2 |
| Attendance fell 10+ points in the term | 1 | | Communication < 45 | 1 |
| Internal marks average < 45% | 2 | | No projects, hackathons or certifications | 1 |
| Any subject < 35% in internals | 1 | | | |
| Fewer than 60% of assignments submitted | 2 | | | |
| LMS activity dropped below 60% of its starting level | 1 | | | |
| Latest SGPA 0.5+ below the student's earlier average | 1 | | | |
| Wellbeing concern in survey or mentor remarks | 1 | | | |

**Levels:** High ≥ 7 points · Medium ≥ 3 · otherwise Low.

**Insufficient data.** Academic risk requires CGPA and attendance. Placement risk requires an aptitude or coding test. If required evidence is missing, the level is **Insufficient data**, which is shown differently from Low, and a "collect the data" action is suggested. The one exception: if the evidence that is available already reaches High, the student is flagged High.

**Recalculation.** Every committed upload, rule change or manual request recalculates every student's score and risk for every review period.

**Who sees what.** Wellbeing evidence is visible to administrators, HODs and mentors. Placement officers and students see that a concern exists, not its details.

## 5. Segments (bonus)

Rules are checked in order, and each student lands in the first segment that fits:

1. Critical support needed
2. Declining attendance and academic performance
3. Strong academics, low placement readiness
4. Strong skills, academic support needed
5. Disengaging (early warning)
6. Thriving
7. Steady

Each student's profile lists the exact conditions that placed them in their segment. Each segment has an owner and a playbook.

## 6. Validation against real outcomes

`python -m ssp.validate` scores last year's batch as it looked at the start of its final year: 900 synthetic B.Tech students, loaded through the normal import path. It then compares those scores with what happened at graduation. Results for rules version 2026.1:

| | Poor academic outcome* | Not placed within 6 months |
|---|---|---|
| Academic risk **High** (208 students) | 88% | 75% |
| Academic risk **Low** (519) | 5% | 30% |
| Placement risk **High** (143) | 81% | 84% |
| Placement risk **Low** (392) | 7% | 20% |
| Placement risk **Insufficient data** (198) | 41% | 56% |
| Score band **Critical** / **Thriving** | 96% / 0% | 82% / 13% |

\*Final CGPA below 6.0, or backlogs still outstanding at graduation.

AUC measures how well a ranking separates outcomes: 1.0 is perfect and 0.5 is no better than chance.

| | Poor academic outcome | Not placed |
|---|---|---|
| Success Score | 0.95 | 0.79 |
| Risk-rule points | 0.92 (academic rules) | 0.79 (placement rules) |

Students with no placement test on record fared markedly worse than those flagged Low. This supports treating missing evidence as a reason to act, not as reassurance.

## 7. Limitations

- **Synthetic data.** The weights and thresholds are informed defaults. They should be reviewed by the academic council and re-checked on the college's own past batches before real use.
- **Rule-based risk.** Risk comes from transparent rules, as the brief asks for this prototype. A trained predictive model can be added later; the validation report gives the baseline it would need to beat.
- **Advisory only.** Flags prompt a conversation with the student. They are not automated decisions.
