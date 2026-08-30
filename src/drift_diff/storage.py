"""SQLite-backed snapshot storage for column profiles."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class SnapshotStore:
    """Persist and retrieve column-level profile snapshots."""

    def __init__(self, db_path: str | Path = "data/drift_snapshots.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    dataset_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    column_type TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_dataset
                ON snapshots(run_id, dataset_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dataset_column
                ON snapshots(dataset_name, column_name)
            """)

    def save_snapshot(
        self,
        run_id: str,
        dataset_name: str,
        column_name: str,
        column_type: str,
        profile: dict[str, Any],
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO snapshots (run_id, dataset_name, column_name, column_type, profile_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, dataset_name, column_name, column_type, json.dumps(profile)),
            )

    def get_latest_run(self, dataset_name: str, exclude_run_id: str | None = None) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            if exclude_run_id:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT run_id FROM snapshots
                    WHERE dataset_name = ? AND run_id != ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (dataset_name, exclude_run_id),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT run_id FROM snapshots
                    WHERE dataset_name = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (dataset_name,),
                )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_snapshot(
        self, run_id: str, dataset_name: str, column_name: str
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT profile_json, column_type FROM snapshots
                WHERE run_id = ? AND dataset_name = ? AND column_name = ?
                """,
                (run_id, dataset_name, column_name),
            )
            row = cursor.fetchone()
            if row:
                return {"profile": json.loads(row[0]), "type": row[1]}
            return None

    def get_all_columns(self, run_id: str, dataset_name: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT column_name, column_type, profile_json FROM snapshots
                WHERE run_id = ? AND dataset_name = ?
                """,
                (run_id, dataset_name),
            )
            return [
                {"name": row[0], "type": row[1], "profile": json.loads(row[2])}
                for row in cursor.fetchall()
            ]

    def get_run_history(self, dataset_name: str, limit: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT run_id, created_at FROM snapshots
                WHERE dataset_name = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (dataset_name, limit),
            )
            return [{"run_id": row[0], "created_at": row[1]} for row in cursor.fetchall()]

    def delete_run(self, run_id: str, dataset_name: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM snapshots WHERE run_id = ? AND dataset_name = ?
                """,
                (run_id, dataset_name),
            )
            return cursor.rowcount