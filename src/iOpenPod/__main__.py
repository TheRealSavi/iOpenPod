"""Support ``uv run python -m iOpenPod`` and the native desktop launcher."""

from iopenpod_launcher import run_with_crash_logging

if __name__ == "__main__":
    raise SystemExit(run_with_crash_logging())
