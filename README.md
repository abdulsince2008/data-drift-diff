# data-drift-diff

**Zero-Config Data Drift Diff** — Detect silent schema/distribution drift between dataset runs using local SQLite snapshots and ydata-profiling.

## Problem Statement

Data pipelines silently break when upstream schemas change or distributions shift. Existing tools either require complex setup (Great Expectations, Deequ), focus only on schema (not distribution), or need a centralized server. This tool gives you **local, zero-config drift detection** with a single command — profile once, run again, get an HTML report showing exactly what drifted.

## Why This Is Different

| Tool | Schema Drift | Distribution Drift | Local-First | Zero Config |
|------|-------------|-------------------|-------------|-------------|
| **data-drift-diff** | ✅ | ✅ | ✅ | ✅ |
| Great Expectations | ✅ | ✅ | ❌ (needs config) | ❌ |
| Deequ | ✅ | ✅ | ❌ (Spark required) | ❌ |
| whylogs | ✅ | ✅ | ❌ (needs server) | ❌ |
| pandas-profiling (ydata) | ❌ | ✅ | ✅ | ✅ |
| dagster/airflow data quality | ✅ | ❌ | ❌ | ❌ |

**The one genuinely new piece**: Snapshots column-level profiles to **local SQLite** on every run, then automatically diffs against the previous run — flagging both schema changes (added/removed/type-changed columns) AND statistical distribution drift (mean/std shift, KS test on histograms, categorical distribution shift) — all in a single self-contained HTML report. No server, no config, no external dependencies beyond the profiling library.

## How It Works

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   CSV/Parquet   │────▶│  ydata-profiling │────▶│  Column Profiles│
│   (any dataset) │     │  (statistics)    │     │  (JSON)         │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                    ┌──────────────────┐                  │
                    │   SQLite DB      │◀─────────────────┘
                    │  (snapshots)     │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌────────────┐ ┌────────────┐ ┌────────────┐
       │  Numeric   │ │Categorical │ │  DateTime  │
       │  Drift     │ │  Drift     │ │  Drift     │
       │ (mean/std, │ │ (dist shift,│ │ (range     │
       │  KS test)  │ │  new cats) │ │  shift)    │
       └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                   ┌──────────────────┐
                   │  HTML Report     │
                   │  (visual diff)   │
                   └──────────────────┘
```

1. **Profile**: Run `drift-diff data.csv --name my_dataset` — computes column stats via ydata-profiling
2. **Snapshot**: Saves each column's profile (type, n, distinct, missing%, mean, std, min, max, histogram, value_counts) to local SQLite with a run ID
3. **Diff**: On next run, fetches previous run's snapshots and computes drift scores per column
4. **Report**: Generates a standalone HTML report with drift bars, badges, and schema change summary

## How to Run

```bash
# Install (requires Python 3.10–3.13; Python 3.14+ not yet supported by ydata-profiling)
pip install -e .

# Quick demo (generates sample data, runs twice, shows drift)
drift-diff --demo

# Or manually:
# 1. First run - establishes baseline
drift-diff data/your_data.csv --name my_dataset

# 2. Later run - detects drift against baseline
drift-diff data/new_data.csv --name my_dataset

# Options
drift-diff data.csv --name my_dataset --threshold 0.1 --report reports/custom.html --sample 5000
```

## Example Output

### Terminal Output (Real Run)

```
🎬 Running demo mode...

📌 Run 1: Establishing baseline...
📖 Reading data/baseline.csv...
📊 Profiling 1000 rows × 7 columns...
🔍 Comparing against previous run...
📝 Generating report: reports/baseline_report.html

==================================================
DRIFT DETECTION SUMMARY
==================================================
Run ID:         20260830_062323_84ea2f89
Previous Run:   None (baseline)
Drift Detected: NO ✅
Total Columns:  7
Drifted Columns: 0
Added Columns:  0
Removed Columns: 0
Type Changes:   0
Report:         reports/baseline_report.html
==================================================

📌 Run 2: Detecting drift...
📖 Reading data/drifted.csv...
📊 Profiling 1000 rows × 8 columns...
🔍 Comparing against previous run...
📝 Generating report: reports/drift_report.html

==================================================
DRIFT DETECTION SUMMARY
==================================================
Run ID:         20260830_062326_1e612e3d
Previous Run:   20260830_062323_84ea2f89
Drift Detected: YES ⚠️
Total Columns:  8
Drifted Columns: 4
Added Columns:  1
Removed Columns: 0
Type Changes:   0
Report:         reports/drift_report.html
==================================================
```

### HTML Report (Real Output)

The generated `reports/drift_report.html` contains:

- **Summary cards**: Total columns (8), Drifted (4), Added (1), Removed (0), Type Changes (0)
- **Column drift table** with visual drift bars:

| Column | Type | Status | Drift Score | Details |
|--------|------|--------|-------------|---------|
| age | Numeric | **DRIFTED** | 19.78% | mean changed by 20.0%; std changed by 17.5% |
| income | Numeric | **DRIFTED** | 42.31% | mean changed by 64.2%; KS test statistic: 0.287 |
| category | Categorical | **DRIFTED** | 20.00% | A: 40.0% → 20.0%; E: 0.0% → 20.0%; New categories: E |
| signup_date | DateTime | **DRIFTED** | 100.00% | min shifted by 100.0%; max shifted by 100.0% |
| is_active | Boolean | **DRIFTED** | 28.57% | True: 70.0% → 50.0%; False: 30.0% → 50.0% |
| score | Numeric | STABLE | 9.78% | Within threshold |
| user_id | Numeric | STABLE | 0.00% | Within threshold |
| new_feature | Text | **ADDED** | 100.00% | New column not present in previous run |

- **Schema changes section**: `➕ Added: new_feature`

## Tech Stack + Libraries Reused

| Library | Purpose | Why |
|---------|---------|-----|
| **ydata-profiling** (pandas-profiling) | Statistical profiling | Industry-standard, handles all column types, computes histograms/value_counts automatically |
| **pandas** | Data I/O & manipulation | Standard for tabular data |
| **sqlite3** (stdlib) | Local snapshot storage | Zero-config, file-based, no server needed |
| **jinja2** | HTML report templating | Lightweight, stdlib-adjacent, fast |
| **scipy/numpy** | KS test approximation | Used via ydata-profiling internals |

## Known Limitations / What's Next

- **No Parquet/Excel support yet** — only CSV (easy to add via pandas)
- **No time-series aware drift** — treats DateTime as range only
- **No drift history/trending** — only compares against immediate previous run
- **Sample size** — large datasets need `--sample` flag (profiling is O(n))
- **No programmatic API for CI/CD** — could add `drift_diff.check()` returning structured result
- **Python 3.14** — ydata-profiling needs `setuptools<80` for `pkg_resources` compatibility

---

**License**: MIT