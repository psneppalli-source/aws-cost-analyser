# Success Score, risk and segments — methodology note

All results are produced by **transparent rules** in `backend/app/scoring.py` from the active, versioned
configuration (`config/scoring.json`, changed only through *Configuration → Propose / Activate*). They are
not predictions and are labelled that way in the app. Every threshold below is a **demonstration
assumption** that a college must review and validate before relying on it.

## 1. Indicators per reporting period

For each monthly period *p* (from `config/curriculum.json`):

| Component | Indicator | Source |
|---|---|---|
| Academic | CGPA, active backlogs | latest academic result at or before *p* |
| | average marks % | mean of score / max score over *p*'s assessments |
| Attendance | attendance % | classes attended / held across *p*'s subjects |
| | attendance change | *p* minus two periods earlier (used by risk and segments) |
| LMS | assignment completion % | submitted / due in *p* |
| | logins per week | logins in *p* / 4.33 |
| Placement readiness | aptitude, coding, mock interview | latest of each within the 6-period look-back |
| Skills | technical, communication | latest assessment within the look-back |
| Engagement | events, clubs, projects, **verified** certifications | counts within the 6-period look-back |

The profile shows each raw value and the period(s) it came from.

## 2. Normalisation (0–100)

Each indicator is mapped linearly between a *worst* and a *best* value and clipped to 0–100
(e.g. CGPA 5.0 → 0 and 9.0 → 100; backlogs 4 → 0 and 0 → 100). A component's value is the weighted mean of
the indicators that are **present**; absent indicators are left out, not counted as zero.

## 3. Weights, cohort profiles and coverage

Configured weights: **Academic 30, Attendance 20, LMS 15, Placement readiness 15, Skills 10, Engagement 10.**

Cohort profiles decide which components apply:

* *Years 1–2*: Academic, Attendance, LMS, Skills, Engagement (placement not yet applicable).
* *Years 3–4*: all six.

For a student-period:

* **Coverage** = sum of configured weights of the applicable components that have data ÷ sum of the
  configured weights of all applicable components.
* **Applied weight** of an included component = its configured weight ÷ the sum of weights of the included
  components (re-normalisation). **Contribution** = applied weight × component value.
* **Final score** = sum of contributions, 0–100, one decimal.

Status:

| Coverage | Status | Shown as |
|---|---|---|
| < 80 % (configurable) | **Insufficient data** | No Success Score. An *indicative* value from the available data is shown separately and clearly labelled |
| 80 % to < 100 % | **Provisional** | Score shown with the missing components listed |
| 100 % | **Complete** | Score |

Missing data is never converted to zero. Each profile shows the component table: value, configured
weight, applied weight, contribution, final score, coverage, profile, scoring version and calculation time.

Bands (assumptions): Strong ≥ 75, On track ≥ 60, Needs attention ≥ 45, At risk < 45.

**Trends** compare periods only when both have a score calculated under the same cohort profile and scoring
version. Periods with insufficient data appear as gaps, never as zeros.

**Feedback** (satisfaction, stress, support requested, comment) never enters the score. Stress ≥ 4,
satisfaction ≤ 2 or a support request becomes a *support need* shown to staff as context.

## 4. Risk (two independent assessments)

Academic and placement risk are computed separately; neither feeds the other or the score.

Academic rules (A1–A10): CGPA < 6.0 high / < 6.5 medium; backlogs ≥ 2 high / ≥ 1 medium; attendance
< 65 % high / < 75 % medium; attendance fell ≥ 10 points over three periods (medium); average marks < 40 %
high / < 50 % medium; fewer than half of assignments submitted (medium). CGPA and attendance are required
evidence; without them the level is *insufficient data* unless a high rule already fired.

Placement rules (P1–P7, years 3–4 only): coding < 40 high / < 55 medium; aptitude < 35 high / < 50 medium;
mock interview < 2.5/5 medium; an active backlog (medium); communication < 45 (medium). At least one of
aptitude or coding is required. **No placement data means *insufficient data* (“collect placement
assessments”), never poor readiness.** Years 1–2: *not applicable*.

Level = the most severe triggered rule; *low* when none trigger. Each flag records the rule, the label, the
observed value, the operator and threshold, the period the value came from, the suggested intervention
and the calculation time. The profile shows all of them.

## 5. Segments

| Segment | Rule (configurable) |
|---|---|
| Strong academics, low placement readiness | Academic component ≥ 70 and placement component < 50 |
| Declining attendance and results | Attendance down ≥ 8 points and academic component down ≥ 5 over three periods |
| Strong skills, academic support required | Skills ≥ 70 and academic risk medium or high |
| Improving after intervention | Score up ≥ 5 since an intervention's baseline (comparable periods only) — *an association, not proof* |
| Consistently performing well | Score ≥ 75 in each of the last three periods, academic risk low, placement low or not applicable |
| Insufficient data | Coverage below the threshold |

Each membership lists its reasons.

## 6. Recommendations and interventions

Triggered rules map to suggested interventions (e.g. *Academic support plan*, *Coding bootcamp*, *Collect
placement data*) with the evidence attached. Staff must tick *“I have reviewed this recommendation and its
evidence”* before assigning; nothing is assigned automatically. Outcomes are recorded by staff; the
before/after view compares baseline and later scores only when they are comparable and says that a change
is an association, not proof of effect.

## 7. Recalculation

Any change (record, correction, verification, intervention, mentor) is written in the same transaction as
a *stale* marker; recalculation clears it. If recalculation fails the student stays marked and an
administrator's *Repair* processes the queue in bounded, resumable steps. Activating a new scoring version
marks every student for recalculation. Scores record the version used.

## 8. Limitations

* Thresholds and weights are illustrative and need institutional validation, including checks for
  differences between groups of students.
* Monthly periods are coarse; attendance and marks inside a month are aggregated.
* The rules see only recorded data; unrecorded support or circumstances are invisible to them.
* A future predictive model can be connected through `backend/app/model_interface.py` (disabled by
  default, never replacing these rules, and only after cost, bias and data-protection review).
