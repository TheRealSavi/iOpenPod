"""Native helper process ownership includes frozen bootloader descendants."""

import ctypes
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from iOpenPod.app.updates.processes import ParentProcess, candidate_process
from iOpenPod.app.updates.processes_windows import WindowsCandidateProcess


@pytest.mark.parametrize("failure", ["SetInformationJobObject", "CreateProcessW"])
def test_candidate_start_failure_preserves_native_error_and_closes_job(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    kernel = Mock()
    kernel.CreateJobObjectW.return_value = 42
    getattr(kernel, failure).return_value = 0
    loader = Mock(return_value=kernel)
    error = OSError(5, "Access is denied")
    last_error = Mock(return_value=5)
    win_error = Mock(return_value=error)
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", last_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", win_error, raising=False)

    # Cleanup must not replace the error captured at the failing native call.
    def close_handle(_handle: int) -> None:
        last_error.return_value = 0

    kernel.CloseHandle.side_effect = close_handle
    with pytest.raises(OSError) as raised:
        WindowsCandidateProcess([sys.executable], {})
    assert raised.value is error
    loader.assert_called_once_with("kernel32", use_last_error=True)
    win_error.assert_called_once_with(5)
    kernel.CloseHandle.assert_called_once_with(42)
    kernel.ResumeThread.assert_not_called()


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
        # Windows may publish the empty job count before every terminated
        # descendant's process handle becomes signaled.
        deadline = time.monotonic() + 5
        while not descendant.exited() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert descendant.exited()
    finally:
        child.stop()
        child.release()
        if descendant:
            descendant.close()
