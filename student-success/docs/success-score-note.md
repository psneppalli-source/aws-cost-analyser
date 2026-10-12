# The Student Success Score: a short note

## What it is

One number from 0 to 100 that sums up how a student is doing across
academics, attendance, LMS activity, engagement, placement readiness, skills
and wellbeing. Faculty use it to sort and compare students. The risk flags
(below) are what trigger interventions.

## Indicators and weights

23 indicators from 7 source systems, grouped into 7 pillars.

| Pillar (weight) | Indicators (weight within pillar) | Source |
|---|---|---|
| **Academic (30%)** | CGPA (45%), active backlogs (25%), current internal marks (15%), SGPA trend (15%) | SIS, exam cell |
| **Attendance (15%)** | Overall % (60%), weakest-subject % (20%), Jul→Sep trend (20%) | Biometric register |
| **LMS (15%)** | Assignment completion (40%), logins/week (20%), quiz average (20%), activity trend (last 4 weeks vs first 4) (20%) | LMS export |
| **Placement readiness (15%)** | Aptitude (35%), coding (40%), mock interview (25%) | Placement cell |
| **Skills (10%)** | Technical (50%), communication (25%), problem solving (25%) | Skills assessment |
| **Engagement (10%)** | Events (30%), clubs (20%), hackathons (25%), certifications (25%) | Activity logs |
| **Feedback & wellbeing (5%)** | Student satisfaction (50%), mentor rating (50%) | Survey, mentors |

Why these weights: academics carry the most weight because they decide
eligibility (exams, recruiters' CGPA and backlog cut-offs). Attendance, LMS
and placement readiness are the levers faculty can move this semester.
Wellbeing is weighted low in the score because survey data is
self-reported and incomplete. Its free-text signal works better as a flag,
and the dashboard uses it that way.

## How indicators are combined

1. **Normalise each indicator to 0-100 with fixed anchors.** For example,
   attendance 60% → 0 and 95% → 100. CGPA 5.0 → 0 and 9.0 → 100. Backlogs
   4+ → 0 and none → 100. Values outside the anchors are clipped.
   The anchors are fixed rather than percentile-based, so a score means the
   same thing every semester and does not drop just because classmates
   improved.
2. **Average indicators into pillar scores** using the within-pillar weights.
3. **Combine pillars** using the pillar weights:
   `Success Score = Σ pillar weight × pillar score`.
4. **Missing by design is not missing by neglect.** 2nd-year students have no
   placement data yet, so the 15% placement weight is shared out
   proportionally across their other pillars. If a 3rd- or 4th-year student
   *skipped* the placement tests, their scores are imputed at the
   department's 10th percentile and flagged, because no evidence of
   readiness should not count as average readiness.
5. **Bands:** Thriving ≥ 70 · On track 55-70 · Needs attention 40-55 · Critical < 40.

## Explainability

Every score is decomposed exactly:

```
score = baseline (the campus-average student) + Σ contribution of each indicator
contribution = effective weight × (student's indicator score − campus average indicator score)
```

The student profile shows these contributions as a diverging bar chart, so
a mentor can see which indicators add points and which take them away.
The test suite checks that the parts add back up to the score.

## Does it work? Validation against real outcomes

We computed the score for last year's graduating batch (900 students) as
they looked at the start of their final year, then compared it with what
actually happened:

| Band | Poor academic outcome* | Placed within 6 months |
|---|---|---|
| Thriving | 1% | 86% |
| On track | 6% | 67% |
| Needs attention | 43% | 44% |
| Critical | 96% | 16% |

\*Final CGPA < 6.0 or backlogs still outstanding at graduation.

AUC: 0.93 for poor academic outcome, 0.78 for not being placed. The
hand-set weights rank students well without having been fitted to outcomes.

## Risk flags (separate from the score)

The score is designed to be understandable. The risk flags are designed to
be accurate. Two logistic-regression models are trained on last year's
batch, with a 75/25 train/test split:

| Model | Target | Holdout AUC | Recall / precision at "Medium" |
|---|---|---|---|
| Academic risk | Final CGPA < 6 or outstanding backlogs | 0.96 | 95% / 83% |
| Placement risk (3rd/4th years) | Not placed within 6 months | 0.87 | 86% / 70% |

Logistic regression was chosen because on standardised inputs each feature's
term (coefficient × z-score) is its exact additive effect on the log-odds of
risk. That makes "why is this student flagged?" exact rather than
approximate. If a feature's learned direction contradicts domain knowledge
(for example, "more certifications → more risk", which comes from
collinearity), the feature is dropped and the model is refit. That way every
explanation points in a direction a mentor can act on.

Rules that come from campus policy sit alongside the models. The main one
is the 75% attendance rule for exam eligibility.

## Limitations

- The data is **synthetic**: it was generated to mimic real campus systems,
  including their quality problems. The weights and anchors should be
  reviewed with the academic council and re-validated on the institution's
  own historical outcomes before use.
- The models are trained on one past batch. They should be retrained each
  year and checked for drift and for fairness across departments and
  genders.
- Flags are prompts for a human conversation, not automated decisions.
