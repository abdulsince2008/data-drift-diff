"""Core drift detection engine using ydata-profiling."""
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from ydata_profiling import ProfileReport

from .storage import SnapshotStore


class DriftDiff:
    """Detect schema and distribution drift between dataset runs."""

    def __init__(
        self,
        db_path: str | Path = "data/drift_snapshots.db",
        drift_threshold: float = 0.05,
    ):
        self.store = SnapshotStore(db_path)
        self.drift_threshold = drift_threshold
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    def _compute_column_hash(self, profile: dict[str, Any]) -> str:
        """Create a deterministic hash of column profile for quick change detection."""
        key_fields = {
            "type": profile.get("type"),
            "n": profile.get("n"),
            "n_distinct": profile.get("n_distinct"),
            "p_missing": profile.get("p_missing"),
            "mean": profile.get("mean"),
            "std": profile.get("std"),
            "min": profile.get("min"),
            "max": profile.get("max"),
            "histogram": profile.get("histogram"),
        }
        return hashlib.md5(str(sorted(key_fields.items())).encode()).hexdigest()[:12]

    def profile_dataset(
        self, df: pd.DataFrame, dataset_name: str, sample_size: int | None = None
    ) -> dict[str, Any]:
        """Generate ydata-profiling report and extract column profiles."""
        if sample_size and len(df) > sample_size:
            df = df.sample(n=sample_size, random_state=42)

        profile = ProfileReport(
            df,
            title=f"{dataset_name} Profile",
            explorative=True,
            minimal=True,
            progress_bar=False,
        )

        report_json = profile.to_json()
        report_dict = json.loads(report_json)
        columns = {}

        for col_name, col_data in report_dict.get("variables", {}).items():
            col_profile = {
                "type": col_data.get("type"),
                "n": col_data.get("n"),
                "n_distinct": col_data.get("n_distinct"),
                "p_missing": col_data.get("p_missing"),
                "mean": col_data.get("mean"),
                "std": col_data.get("std"),
                "min": col_data.get("min"),
                "max": col_data.get("max"),
                "median": col_data.get("median"),
                "histogram": col_data.get("histogram"),
                "value_counts": col_data.get("value_counts"),
                "hash": None,  # Will be set below
            }
            col_profile["hash"] = self._compute_column_hash(col_profile)
            columns[col_name] = col_profile

            self.store.save_snapshot(
                self.run_id,
                dataset_name,
                col_name,
                col_data.get("type", "Unknown"),
                col_profile,
            )

        return {
            "run_id": self.run_id,
            "dataset_name": dataset_name,
            "n_rows": len(df),
            "n_cols": len(df.columns),
            "columns": columns,
            "profile_hash": hashlib.md5(str(sorted(columns.items())).encode()).hexdigest()[:16],
        }

    def detect_drift(
        self,
        current_profile: dict[str, Any],
        dataset_name: str,
        previous_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Compare current profile against previous run."""
        if previous_run_id is None:
            previous_run_id = self.store.get_latest_run(dataset_name, exclude_run_id=self.run_id)

        if previous_run_id is None:
            return {
                "drift_detected": False,
                "message": "No previous run found - baseline established",
                "run_id": self.run_id,
                "previous_run_id": None,
                "column_drifts": {},
                "schema_changes": {"added": [], "removed": [], "type_changed": []},
                "summary": {
                    "total_columns": len(current_profile["columns"]),
                    "drifted_columns": 0,
                    "added_columns": 0,
                    "removed_columns": 0,
                    "type_changed": 0,
                },
                "dataset_name": dataset_name,
            }

        prev_columns_raw = {
            c["name"]: c for c in self.store.get_all_columns(previous_run_id, dataset_name)
        }
        curr_columns = current_profile["columns"]

        # Unwrap stored profiles (they have a "profile" key)
        prev_columns = {k: v["profile"] for k, v in prev_columns_raw.items()}

        column_drifts = {}
        schema_changes = {"added": [], "removed": [], "type_changed": []}

        all_columns = set(prev_columns.keys()) | set(curr_columns.keys())

        for col_name in all_columns:
            prev = prev_columns.get(col_name)
            curr = curr_columns.get(col_name)

            if prev is None:
                schema_changes["added"].append(col_name)
                column_drifts[col_name] = {
                    "status": "added",
                    "drift_score": 1.0,
                    "details": "New column not present in previous run",
                }
                continue

            if curr is None:
                schema_changes["removed"].append(col_name)
                column_drifts[col_name] = {
                    "status": "removed",
                    "drift_score": 1.0,
                    "details": "Column removed since previous run",
                }
                continue

            if prev["type"] != curr["type"]:
                schema_changes["type_changed"].append(
                    {"column": col_name, "from": prev["type"], "to": curr["type"]}
                )

            drift_result = self._compute_drift_score(prev, curr)
            column_drifts[col_name] = drift_result

        overall_drift = any(d.get("drift_score", 0) > self.drift_threshold for d in column_drifts.values())
        schema_drift = bool(schema_changes["added"] or schema_changes["removed"] or schema_changes["type_changed"])

        return {
            "drift_detected": overall_drift or schema_drift,
            "run_id": self.run_id,
            "previous_run_id": previous_run_id,
            "column_drifts": column_drifts,
            "schema_changes": schema_changes,
            "summary": {
                "total_columns": len(all_columns),
                "drifted_columns": sum(1 for d in column_drifts.values() if d.get("drift_score", 0) > self.drift_threshold),
                "added_columns": len(schema_changes["added"]),
                "removed_columns": len(schema_changes["removed"]),
                "type_changed": len(schema_changes["type_changed"]),
            },
            "dataset_name": dataset_name,
        }

    def _compute_drift_score(
        self, prev_profile: dict[str, Any], curr_profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute statistical drift score between two column profiles."""
        if prev_profile.get("hash") == curr_profile.get("hash"):
            return {"status": "unchanged", "drift_score": 0.0, "details": "Profile hash matches"}

        col_type = prev_profile.get("type", "Unknown")

        if col_type in ("Numeric", "Integer", "Float"):
            return self._numeric_drift(prev_profile, curr_profile)
        elif col_type in ("Categorical", "Boolean"):
            return self._categorical_drift(prev_profile, curr_profile)
        elif col_type == "DateTime":
            return self._datetime_drift(prev_profile, curr_profile)
        else:
            return {"status": "unknown_type", "drift_score": 0.0, "details": f"Unhandled type: {col_type}"}

    def _numeric_drift(
        self, prev: dict[str, Any], curr: dict[str, Any]
    ) -> dict[str, Any]:
        """Detect drift in numeric columns using mean/std shift."""
        details = []
        drift_score = 0.0

        for stat in ("mean", "std", "min", "max"):
            p_val = prev.get(stat)
            c_val = curr.get(stat)
            if p_val is not None and c_val is not None and p_val != 0:
                rel_change = abs(c_val - p_val) / abs(p_val)
                drift_score = max(drift_score, rel_change)
                if rel_change > self.drift_threshold:
                    details.append(f"{stat} changed by {rel_change:.1%}")

        if prev.get("histogram") and curr.get("histogram"):
            ks_score = self._ks_test_histogram(prev["histogram"], curr["histogram"])
            drift_score = max(drift_score, ks_score)
            if ks_score > self.drift_threshold:
                details.append(f"KS test statistic: {ks_score:.3f}")

        status = "drifted" if drift_score > self.drift_threshold else "stable"
        return {
            "status": status,
            "drift_score": round(drift_score, 4),
            "details": "; ".join(details) if details else "Within threshold",
        }

    def _categorical_drift(
        self, prev: dict[str, Any], curr: dict[str, Any]
    ) -> dict[str, Any]:
        """Detect drift in categorical columns using distribution shift."""
        prev_vc = prev.get("value_counts", {})
        curr_vc = curr.get("value_counts", {})

        all_categories = set(prev_vc.keys()) | set(curr_vc.keys())
        if not all_categories:
            return {"status": "stable", "drift_score": 0.0, "details": "No categories"}

        prev_total = sum(prev_vc.values())
        curr_total = sum(curr_vc.values())

        drift_score = 0.0
        details = []

        for cat in all_categories:
            p_pct = prev_vc.get(cat, 0) / prev_total if prev_total else 0
            c_pct = curr_vc.get(cat, 0) / curr_total if curr_total else 0
            diff = abs(c_pct - p_pct)
            drift_score = max(drift_score, diff)
            if diff > self.drift_threshold:
                details.append(f"{cat}: {p_pct:.1%} -> {c_pct:.1%}")

        new_cats = set(curr_vc.keys()) - set(prev_vc.keys())
        if new_cats:
            drift_score = max(drift_score, 1.0)
            details.append(f"New categories: {', '.join(new_cats)}")

        status = "drifted" if drift_score > self.drift_threshold else "stable"
        return {
            "status": status,
            "drift_score": round(drift_score, 4),
            "details": "; ".join(details) if details else "Within threshold",
        }

    def _datetime_drift(
        self, prev: dict[str, Any], curr: dict[str, Any]
    ) -> dict[str, Any]:
        """Detect drift in datetime columns."""
        details = []
        drift_score = 0.0

        for stat in ("min", "max"):
            p_val = prev.get(stat)
            c_val = curr.get(stat)
            if p_val and c_val:
                try:
                    p_ts = pd.Timestamp(p_val).timestamp()
                    c_ts = pd.Timestamp(c_val).timestamp()
                    if p_ts != 0:
                        rel_change = abs(c_ts - p_ts) / abs(p_ts)
                        drift_score = max(drift_score, rel_change)
                        if rel_change > self.drift_threshold:
                            details.append(f"{stat} shifted by {rel_change:.1%}")
                except Exception:
                    pass

        status = "drifted" if drift_score > self.drift_threshold else "stable"
        return {
            "status": status,
            "drift_score": round(drift_score, 4),
            "details": "; ".join(details) if details else "Within threshold",
        }

    def _ks_test_histogram(self, hist1: dict, hist2: dict) -> float:
        """Approximate KS test from histogram bins."""
        try:
            bins1 = hist1.get("bins", [])
            bins2 = hist2.get("bins", [])
            counts1 = hist1.get("counts", [])
            counts2 = hist2.get("counts", [])

            if not bins1 or not bins2 or len(bins1) != len(bins2):
                return 0.0

            total1 = sum(counts1)
            total2 = sum(counts2)
            if total1 == 0 or total2 == 0:
                return 0.0

            cdf1 = []
            cdf2 = []
            cum1 = cum2 = 0
            for c1, c2 in zip(counts1, counts2):
                cum1 += c1 / total1
                cum2 += c2 / total2
                cdf1.append(cum1)
                cdf2.append(cum2)

            return max(abs(a - b) for a, b in zip(cdf1, cdf2))
        except Exception:
            return 0.0