"""Opt-in child lifetime pipes preserve default EOF and ordinary cancellation."""

import subprocess
import sys
from pathlib import Path

import pytest

from storage import HostPath
from storage.media_processing import MediaToolError, run_media_tool


@pytest.mark.parametrize("keep_open", [False, True])
def test_stdin_is_eof_by_default_and_remains_open_only_when_requested(
    keep_open: bool,
) -> None:
    program = """
import os, sys
descriptor = sys.stdin.fileno()
if sys.argv[1] == 'open':
    os.set_blocking(descriptor, False)
try:
    data = os.read(descriptor, 1)
except BlockingIOError:
    print('open')
else:
    print('eof' if not data else 'unexpected input')
"""
    result = run_media_tool(
        HostPath(sys.executable),
        ("-c", program, "open" if keep_open else "closed"),
        checkpoint=lambda: None,
        keep_stdin_open=keep_open,
        timeout_seconds=3,
    )
    assert result.stdout.strip() == (b"open" if keep_open else b"eof")


@pytest.mark.parametrize("cancel", [False, True])
def test_lifetime_pipe_is_closed_and_process_reaped_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    ready = tmp_path / "ready"

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
        env: dict[str, str],
    ) -> subprocess.Popen[bytes]:
        process = original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
            env=env,
        )
        processes.append(process)
        return process

    def checkpoint() -> None:
        if cancel and ready.exists():
            raise InterruptedError("preparation cancelled")

    monkeypatch.setattr(subprocess, "Popen", launch)
    error = InterruptedError if cancel else MediaToolError
    with pytest.raises(error):
        run_media_tool(
            HostPath(sys.executable),
            (
                "-c",
                "import sys; from pathlib import Path; "
                "Path(sys.argv[1]).touch(); sys.stdin.buffer.read(1)",
                str(ready),
            ),
            checkpoint=checkpoint,
            keep_stdin_open=True,
            timeout_seconds=3 if cancel else 0.3,
        )
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].stdin is not None and processes[0].stdin.closed
