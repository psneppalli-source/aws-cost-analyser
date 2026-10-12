# Smart Campus Analytics: Student Success Platform

An analytics and AI platform that joins seven disconnected campus systems into
one student view. It then scores every student, flags who is at risk
academically or for placement (and explains why), groups students into
segments with clear owners, and recommends the next action.

> All data is **synthetic**. It was generated to mimic real campus exports,
> including their quality problems. No real student information is used.

## Quick start

```bash
# View the dashboard: no server or install needed
open dashboard/index.html          # or double-click it

# Rebuild everything from the raw sources
pip install -r requirements.txt    # numpy, pandas
python -m pipeline.build           # add --regenerate to re-simulate raw data
python -m unittest discover -s tests -v
```

Deliverables:

| | |
|---|---|
| Working dashboard | [`dashboard/index.html`](dashboard/index.html) |
| Success Score note | [`docs/success-score-note.md`](docs/success-score-note.md) |
| Slides (open in a browser, arrow keys to navigate) | [`docs/slides.html`](docs/slides.html) |

## What's inside

```
data/raw/                         7 source systems as exported (messy on purpose)
data/raw/historical_batch_2022/   last year's batch + real graduation outcomes (training data)
data/processed/                   unified_student_view.csv (one row per student, all features + scores)
pipeline/
  generate_data.py   simulates the campus: hidden traits → correlated, messy source tables
  integrate.py       cleaning, ID reconciliation, feature engineering, data-quality log
  scoring.py         Student Success Score: 23 indicators → 7 pillars, exact per-indicator explanation
  models.py          academic and placement risk models (NumPy logistic regression, AUC, sign checks)
  analytics.py       segmentation, next-best-action rules, auto-generated insights
  build.py           runs everything and writes dashboard/data.js
dashboard/           static HTML/CSS/JS, hand-built SVG charts, light and dark mode
docs/                score note, slides, screenshots
tests/               20 unit and integration tests
```

## How it maps to the brief

| Brief | Where |
|---|---|
| **Data integration** (academic, attendance, LMS, engagement, placement, skills, feedback) | `integrate.py`. 26.7K raw rows from 8 tables → 600 students; 4 ID formats reconciled; 15 kinds of quality fix, each logged and shown in *Data & model* |
| **Student Success Score** | `scoring.py` and the [note](docs/success-score-note.md). Fixed-anchor normalisation, weighted pillars, validated on last year's outcomes |
| **At-risk identification** (academic and placement) | `models.py`. Logistic models trained on last year's batch: holdout AUC 0.96 (academic) and 0.87 (placement). Plus the 75% attendance rule |
| **Interactive dashboard** | Filters by department, year, segment, risk flag and search. Clickable KPIs, histogram, department bars and scatter. Sortable student table, CSV export, student profile drawer |
| **Bonus: segmentation** | `analytics.py`. Six segments, including *Academic achiever, placement-unready*, each with a rule, owner and playbook |
| **Bonus: explainable score** | Every profile shows why the score is what it is (indicator contributions vs the campus average) and why the risk flag fired (model contributions). Both are exact decompositions, not approximations |

## Key results (synthetic campus of 600 students)

- Students below 75% attendance are **3.5×** as likely to be high academic risk.
- **126** students show a disengagement signal (LMS logins or attendance falling).
  A third of them still have CGPA 7+, so a CGPA-only report would miss them.
- **59** high-CGPA students are not placement-ready: their coding average is
  36, vs 58 campus-wide.
- **89** 3rd/4th-year students have never taken a placement test, and 58% of
  them are high placement risk.
- Success Score bands separate real outcomes: 96% of "Critical" students had
  a poor academic outcome, vs 1% of "Thriving".
