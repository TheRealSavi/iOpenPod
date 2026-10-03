"""Native helper process ownership includes frozen bootloader descendants."""

import sys
import time
from pathlib import Path

import pytest

from iOpenPod.app.updates.processes import ParentProcess, candidate_process


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native job ownership")
def test_candidate_can_finish_without_being_killed_on_release(tmp_path: Path) -> None:
    marker = tmp_path / "completed"
    child = candidate_process(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('healthy')",
            str(marker),
        ]
    )
    try:
        assert child.wait(timeout=15) == 0
        assert marker.read_text() == "healthy"
    finally:
        child.stop()
        child.release()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native job ownership")
def test_stopping_candidate_stops_only_its_owned_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    script = "import subprocess,sys,time; from pathlib import Path; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
    child = candidate_process([sys.executable, "-c", script, str(marker)])
    descendant = None
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        descendant = ParentProcess(int(marker.read_text()), Path(sys.executable))
        assert not descendant.exited()
        child.stop()
        assert child.poll() is not None
        assert descendant.exited()
    finally:
        child.stop()
        child.release()
        if descendant:
            descendant.close()
