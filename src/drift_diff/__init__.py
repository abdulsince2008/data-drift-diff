"""Zero-Config Data Drift Diff - Detect silent schema/distribution drift."""
from .core import DriftDiff
from .storage import SnapshotStore
from .report import generate_report

__all__ = ["DriftDiff", "SnapshotStore", "generate_report"]
__version__ = "0.1.0"