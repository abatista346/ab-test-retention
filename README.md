# A/B Test Readout — Does Moving a Progression Gate Hurt Player Retention?

> End-to-end experiment analysis in SQL (DuckDB) and Python: data-quality and sample-ratio checks, a pre-declared primary metric, two-proportion tests with confidence intervals, multiple-testing correction, bootstrap robustness checks, power analysis, and a written ship/no-ship recommendation.

## Problem

In the mobile puzzle game *Cookie Cats*, players hit a "gate" that forces them to wait or pay before continuing. The product team tested moving the first gate from **level 30** to **level 40**. A later gate could feel friendlier — or it could remove a natural break that keeps players coming back.

**Decision to make:** keep the gate at level 30, or move it to level 40?

## Data Source

Cookie Cats A/B test dataset, published on Kaggle — about 90k players randomly assigned to `gate_30` (control) or `gate_40` (treatment), with rounds played in their first 14 days and whether they returned 1 and 7 days after install. Not included in this repository; see [Setup](#setup).

| Column | Meaning |
|---|---|
| `userid` | Player identifier |
| `version` | `gate_30` (control) or `gate_40` (treatment) |
| `sum_gamerounds` | Rounds played in the first 14 days after install |
| `retention_1` / `retention_7` | Did the player come back 1 / 7 days after install? |

## Analysis Plan (decided before looking at results)

| Element | Choice | Why |
|---|---|---|
| Primary metric | Day-7 retention | Long-term engagement is what the gate placement is meant to protect |
| Secondary metric | Day-1 retention | Early signal; corrected for multiple comparisons with Holm |
| Guardrail | Rounds played | Heavy-tailed, so Mann-Whitney U plus a bootstrap CI on the p99-capped mean |
| Validity check | Sample-ratio mismatch (χ² vs. 50/50) | A broken split invalidates everything downstream |
| Significance | α = 0.05, two-sided | Standard; reported alongside confidence intervals, not instead of them |
| Power | Minimum detectable effect at 80% power | Lets a null result be read as "no effect larger than X" |

## Approach

1. **SQL layer** (`sql/`, executed with DuckDB) — data-quality checks (duplicates, invalid values, outliers), per-variant summary, and an engagement-level breakdown.
2. **Statistics** (`src/analyze.py`) — SRM test, two-proportion z-tests with Newcombe confidence intervals, Holm correction, bootstrap check of the primary metric, non-parametric engagement test, and power analysis.
3. **Readout** — the script writes the *Results* section below from the computed numbers, so the README never drifts from the code.

## Tech Stack

SQL (DuckDB), Python, pandas, SciPy, statsmodels, matplotlib

<!-- RESULTS:START -->

## Results

Run the pipeline in [Setup](#setup) to generate this section.

<!-- RESULTS:END -->

## Architecture

```
sql/
  01_data_quality.sql        <- duplicates, invalid values, outliers
  02_variant_summary.sql     <- per-variant sample sizes and rates
  03_engagement_segments.sql <- day-7 retention by engagement bucket
src/
  ingest.py                  <- downloads the dataset into data/raw/
  analyze.py                 <- runs the SQL, the statistics, the charts and the README section
outputs/
  figures/                   <- exported charts
  results.json               <- every computed number
```

## Setup

1. `pip install -r requirements.txt`
2. `python src/ingest.py` (or download the Cookie Cats CSV from Kaggle into `data/raw/cookie_cats.csv`)
3. `python src/analyze.py`

## Limitations and Next Steps

1. **Retention is not revenue.** A later gate may change how many players pay to skip it; the decision should be confirmed against in-app purchase data, which this dataset does not include.
2. **Sequential testing.** This readout assumes a fixed-horizon test analyzed once. If results were monitored daily, a sequential method (e.g. alpha spending) would be needed to keep the false-positive rate at 5%.
3. **Variance reduction.** With pre-experiment engagement data, CUPED could shrink the confidence intervals and the required sample size.
