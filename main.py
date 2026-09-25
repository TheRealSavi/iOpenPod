"""Source-checkout launcher sharing the installed application's entry point."""

import sys
from pathlib import Path

# Prefer this checkout's launcher when an older editable install is still
# present in the environment. This keeps ``uv run main.py`` tied to the source
# being edited instead of a stale site-packages module.
_SOURCE_ROOT = Path(__file__).resolve().parent / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from iopenpod_launcher import run_with_crash_logging  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_with_crash_logging())
