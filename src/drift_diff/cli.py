#!/usr/bin/env python3
"""CLI entry point for data-drift-diff."""
import argparse
import sys
from pathlib import Path

import pandas as pd

from drift_diff.core import DriftDiff
from drift_diff.report import generate_report


def create_sample_data(output_dir: Path) -> tuple[Path, Path]:
    """Create sample baseline and drifted datasets."""
    output_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np

    np.random.seed(42)
    n = 1000

    # Baseline dataset
    baseline = pd.DataFrame({
        "user_id": range(1, n + 1),
        "age": np.random.normal(35, 10, n).clip(18, 80).astype(int),
        "income": np.random.lognormal(10.5, 0.5, n).round(2),
        "category": np.random.choice(["A", "B", "C", "D"], n, p=[0.4, 0.3, 0.2, 0.1]),
        "signup_date": pd.date_range("2020-01-01", periods=n, freq="h"),
        "is_active": np.random.choice([True, False], n, p=[0.7, 0.3]),
        "score": np.random.normal(50, 15, n).clip(0, 100),
    })

    # Drifted dataset - shifted distributions
    np.random.seed(123)
    drifted = pd.DataFrame({
        "user_id": range(1, n + 1),
        "age": np.random.normal(42, 12, n).clip(18, 80).astype(int),  # Mean shifted from 35 to 42
        "income": np.random.lognormal(11.0, 0.6, n).round(2),  # Higher income
        "category": np.random.choice(["A", "B", "C", "D", "E"], n, p=[0.2, 0.25, 0.2, 0.15, 0.2]),  # New category E
        "signup_date": pd.date_range("2023-01-01", periods=n, freq="h"),  # Different date range
        "is_active": np.random.choice([True, False], n, p=[0.5, 0.5]),  # Active rate dropped
        "score": np.random.normal(55, 18, n).clip(0, 100),  # Different distribution
        "new_feature": np.random.choice(["X", "Y", "Z"], n, p=[0.5, 0.3, 0.2]),  # New column
    })

    baseline_path = output_dir / "baseline.csv"
    drifted_path = output_dir / "drifted.csv"

    baseline.to_csv(baseline_path, index=False)
    drifted.to_csv(drifted_path, index=False)

    return baseline_path, drifted_path


def run_drift_check(
    csv_path: Path,
    dataset_name: str,
    db_path: Path,
    report_path: Path,
    sample_size: int | None = None,
    threshold: float = 0.05,
) -> int:
    """Run drift detection on a CSV file."""
    print(f"📖 Reading {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"❌ Failed to read CSV: {e}", file=sys.stderr)
        return 1

    print(f"📊 Profiling {len(df)} rows × {len(df.columns)} columns...")
    detector = DriftDiff(db_path=db_path, drift_threshold=threshold)

    try:
        profile = detector.profile_dataset(df, dataset_name, sample_size=sample_size)
    except Exception as e:
        print(f"❌ Profiling failed: {e}", file=sys.stderr)
        return 1

    print(f"🔍 Comparing against previous run...")
    drift_result = detector.detect_drift(profile, dataset_name)

    print(f"📝 Generating report: {report_path}")
    try:
        generate_report(drift_result, profile, report_path)
    except Exception as e:
        print(f"❌ Report generation failed: {e}", file=sys.stderr)
        return 1

    # Print summary
    summary = drift_result.get("summary", {})
    print("\n" + "=" * 50)
    print("DRIFT DETECTION SUMMARY")
    print("=" * 50)
    print(f"Run ID:         {drift_result['run_id']}")
    print(f"Previous Run:   {drift_result['previous_run_id'] or 'None (baseline)'}")
    print(f"Drift Detected: {'YES ⚠️' if drift_result['drift_detected'] else 'NO ✅'}")
    print(f"Total Columns:  {summary.get('total_columns', 0)}")
    print(f"Drifted Columns: {summary.get('drifted_columns', 0)}")
    print(f"Added Columns:  {summary.get('added_columns', 0)}")
    print(f"Removed Columns: {summary.get('removed_columns', 0)}")
    print(f"Type Changes:   {summary.get('type_changed', 0)}")
    print(f"Report:         {report_path}")
    print("=" * 50)

    return 0 if not drift_result["drift_detected"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Zero-Config Data Drift Diff - Detect silent schema/distribution drift",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First run (establishes baseline)
  python -m drift_diff.cli data/baseline.csv --name my_dataset

  # Subsequent run (detects drift)
  python -m drift_diff.cli data/drifted.csv --name my_dataset

  # Generate sample data and run demo
  python -m drift_diff.cli --demo
        """,
    )
    parser.add_argument("csv_path", nargs="?", help="Path to CSV file to profile")
    parser.add_argument("--name", "-n", default="default", help="Dataset name")
    parser.add_argument("--db", default="data/drift_snapshots.db", help="SQLite database path")
    parser.add_argument("--report", "-r", default="reports/drift_report.html", help="Output HTML report path")
    parser.add_argument("--sample", type=int, help="Sample size for large datasets")
    parser.add_argument("--threshold", "-t", type=float, default=0.05, help="Drift threshold (0-1)")
    parser.add_argument("--demo", action="store_true", help="Run demo with generated sample data")

    args = parser.parse_args()

    if args.demo:
        print("🎬 Running demo mode...")
        baseline_path, drifted_path = create_sample_data(Path("data"))

        print("\n📌 Run 1: Establishing baseline...")
        run_drift_check(baseline_path, "demo_dataset", Path(args.db), Path("reports/baseline_report.html"))

        print("\n📌 Run 2: Detecting drift...")
        return run_drift_check(drifted_path, "demo_dataset", Path(args.db), Path("reports/drift_report.html"), threshold=args.threshold)

    if not args.csv_path:
        parser.error("csv_path is required (or use --demo)")

    return run_drift_check(
        Path(args.csv_path),
        args.name,
        Path(args.db),
        Path(args.report),
        sample_size=args.sample,
        threshold=args.threshold,
    )


if __name__ == "__main__":
    sys.exit(main())