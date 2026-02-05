"""
SyncEngine - Bridge between PC music library and iPod

Core components:
- PCLibrary: Scans PC music folder, extracts metadata
- DiffEngine: Computes add/remove/upgrade queues by comparing fingerprints
"""

from .pc_library import PCLibrary, PCTrack
from .diff_engine import DiffEngine, SyncAction, SyncPlan, SyncItem, QualityChange

__all__ = [
    "PCLibrary",
    "PCTrack",
    "DiffEngine",
    "SyncAction",
    "SyncPlan",
    "SyncItem",
    "QualityChange",
]
