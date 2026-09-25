"""Fresh-process import boundaries for responsive GUI startup."""

import subprocess
import sys


def test_app_composition_does_not_import_music_analysis_libraries() -> None:
    source = """
import importlib.abc
import sys

blocked_roots = frozenset({"librosa", "numba", "scipy"})

class HeavyAnalysisImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        root = fullname.partition(".")[0]
        if root in blocked_roots:
            raise AssertionError(f"GUI startup eagerly imported {root}")
        return None

sys.meta_path.insert(0, HeavyAnalysisImportBlocker())

import iOpenPod.app.context
from iOpenPod.app.synesthesia import WholeTrackMusicAnalyzer

WholeTrackMusicAnalyzer()
print("STARTUP_IMPORTS_CLEAN")
"""

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", source],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "STARTUP_IMPORTS_CLEAN"
