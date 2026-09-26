"""External tool cancellation, bounded diagnostics and private file lifetime."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import get_ident

import pytest

from storage import ConcurrentModificationError, HostPath, UnsafeFilesystemPathError
from storage.media_processing import (
    MediaToolError,
    MediaToolProgress,
    media_workspace,
    run_media_tool,
)


def test_progress_is_delivered_while_tool_runs_on_the_calling_thread(
    tmp_path: Path,
) -> None:
    acknowledgement = tmp_path / "progress-received"
    caller = get_ident()
    updates: list[MediaToolProgress] = []

    def progress(update: MediaToolProgress) -> None:
        assert get_ident() == caller
        updates.append(update)
        acknowledgement.touch()

    result = run_media_tool(
        HostPath(sys.executable),
        (
            "-c",
            "import sys, time; from pathlib import Path; "
            "sys.stdout.write('out_t'); sys.stdout.flush(); "
            "sys.stdout.write('ime_us=2500000\\nspeed=2.50x\\nprogress=continue\\n'); sys.stdout.flush(); "
            "ack = Path(sys.argv[1]); "
            "exec('while not ack.exists(): time.sleep(0.01)'); "
            "print('out_time_us=5000000\\nspeed=3.0x\\nprogress=end'); "
            "sys.stderr.write('retained diagnostics')",
            str(acknowledgement),
        ),
        checkpoint=lambda: None,
        progress=progress,
        timeout_seconds=3,
    )
    assert updates[0] == MediaToolProgress(2.5, 2.5, False)
    assert updates[-1] == MediaToolProgress(5, 3, True)
    assert result.stdout == b""
    assert result.stderr == b"retained diagnostics"


def test_progress_records_are_bounded_without_accumulating_the_full_stream() -> None:
    updates: list[MediaToolProgress] = []
    run_media_tool(
        HostPath(sys.executable),
        (
            "-c",
            "print('out_time_us=1000\\nprogress=continue\\n' * 10000, end=''); print('out_time_us=2000\\nprogress=end')",
        ),
        checkpoint=lambda: None,
        progress=updates.append,
        max_output_bytes=64,
    )
    assert updates[-1] == MediaToolProgress(0.002, None, True)
    with pytest.raises(MediaToolError) as error:
        run_media_tool(
            HostPath(sys.executable),
            ("-c", "print('x' * 1000)"),
            checkpoint=lambda: None,
            progress=updates.append,
            max_output_bytes=64,
        )
    assert error.value.code == "media.tool_output_limit"


@pytest.mark.parametrize("value", ["N/A", "nan", "inf", "invalid"])
def test_unknown_progress_measurements_do_not_claim_completion(value: str) -> None:
    updates: list[MediaToolProgress] = []
    run_media_tool(
        HostPath(sys.executable),
        ("-c", f"print('out_time_us={value}\\nspeed={value}\\nprogress=end')"),
        checkpoint=lambda: None,
        progress=updates.append,
    )
    assert updates == [MediaToolProgress(None, None, True)]


def test_progress_callback_failure_kills_and_reaps_the_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
    ) -> subprocess.Popen[bytes]:
        process = original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
        )
        processes.append(process)
        return process

    def progress(_update: MediaToolProgress) -> None:
        raise RuntimeError("progress consumer stopped")

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="progress consumer stopped"):
        run_media_tool(
            HostPath(sys.executable),
            (
                "-c",
                "import time; print('out_time_us=1000\\nprogress=continue', flush=True); time.sleep(30)",
            ),
            checkpoint=lambda: None,
            progress=progress,
            timeout_seconds=3,
        )
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize(
    ("program", "code", "timeout", "limit"),
    [
        ("import time; time.sleep(30)", "media.tool_timeout", 0.1, 4096),
        ("print('x' * 100000)", "media.tool_output_limit", 3, 1024),
        (
            "import sys; print('invalid input', file=sys.stderr); sys.exit(2)",
            "media.tool_failed",
            3,
            4096,
        ),
    ],
)
def test_external_tools_fail_with_bounded_diagnostics_and_reap_processes(
    monkeypatch: pytest.MonkeyPatch, program: str, code: str, timeout: float, limit: int
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
    ) -> subprocess.Popen[bytes]:
        process = original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(MediaToolError) as error:
        run_media_tool(
            HostPath(sys.executable),
            ("-c", program),
            checkpoint=lambda: None,
            timeout_seconds=timeout,
            max_output_bytes=limit,
        )
    assert error.value.code == code
    assert len(str(error.value)) < 3000
    assert len(processes) == 1 and processes[0].poll() is not None


def test_cancellation_kills_and_reaps_running_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
    ) -> subprocess.Popen[bytes]:
        process = original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
        )
        processes.append(process)
        return process

    source = tmp_path / "source.bin"
    source.write_bytes(b"source")

    def checkpoint() -> None:
        if processes:
            raise RuntimeError("cancel requested")

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="cancel requested"):
        run_media_tool(
            HostPath(sys.executable),
            ("-c", "import time; time.sleep(30)"),
            checkpoint=checkpoint,
            input_file=HostPath(source),
        )
    assert len(processes) == 1 and processes[0].poll() is not None
    source.unlink()


def test_rejected_byte_transforms_remove_staging_and_preserve_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"original")
    snapshot: Path | None = None
    with (
        pytest.raises(MediaToolError, match="limit"),
        media_workspace(checkpoint=lambda: None) as workspace,
    ):
        captured = workspace.capture(HostPath(source))
        snapshot = Path(captured.snapshot)
        workspace.transform_bytes(
            captured.snapshot, ".mp3", lambda data: data, max_bytes=3
        )
    assert source.read_bytes() == b"original"
    assert snapshot is not None
    assert not snapshot.exists()


def test_tool_input_remains_seekable_and_preserves_selected_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"before-middle-after")
    result = run_media_tool(
        HostPath(sys.executable),
        (
            "-c",
            "import sys; "
            "f = open(sys.argv[1], 'rb'); f.seek(7); "
            "sys.stdout.buffer.write(f.read(6)); f.close()",
        ),
        input_file=HostPath(source),
        checkpoint=lambda: None,
    )
    assert result.stdout == b"middle" and result.returncode == 0
    assert source.read_bytes() == b"before-middle-after"


def test_unchecked_tool_returns_bounded_stderr_and_exit_status() -> None:
    result = run_media_tool(
        HostPath(sys.executable),
        ("-c", "import sys; sys.stderr.write('decoder error'); sys.exit(2)"),
        checkpoint=lambda: None,
        check=False,
        max_stderr_bytes=128,
    )
    assert result.returncode == 2
    assert result.stderr == b"decoder error"


def test_tool_rejects_linked_input_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, link = tmp_path / "source.bin", tmp_path / "link.bin"
    source.write_bytes(b"source")
    try:
        link.symlink_to(source)
    except OSError as error:
        pytest.skip(f"This Host cannot create a test symlink: {error}")

    def launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A linked source must be rejected before process launch")

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(UnsafeFilesystemPathError):
        run_media_tool(
            HostPath(sys.executable),
            ("-c", "print('unexpected')"),
            input_file=HostPath(link),
            checkpoint=lambda: None,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows denies replacement while pinned")
def test_windows_tool_input_stays_pinned_until_child_is_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    original = subprocess.Popen

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
    ) -> subprocess.Popen[bytes]:
        with pytest.raises(PermissionError):
            source.unlink()
        with pytest.raises(PermissionError):
            source.write_bytes(b"changed")
        return original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
        )

    monkeypatch.setattr(subprocess, "Popen", launch)
    result = run_media_tool(
        HostPath(sys.executable),
        ("-c", "import sys; sys.stdout.buffer.write(open(sys.argv[1], 'rb').read())"),
        input_file=HostPath(source),
        checkpoint=lambda: None,
    )
    assert result.stdout == b"source"
    source.unlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor inheritance")
def test_posix_child_reads_pinned_file_when_input_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, unrelated = tmp_path / "source.bin", tmp_path / "unrelated.bin"
    source.write_bytes(b"approved")
    unrelated.write_bytes(b"unapproved")
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...],
    ) -> subprocess.Popen[bytes]:
        source.rename(tmp_path / "original.bin")
        source.symlink_to(unrelated)
        process = original(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises((ConcurrentModificationError, UnsafeFilesystemPathError)):
        run_media_tool(
            HostPath(sys.executable),
            (
                "-c",
                "import sys; assert open(sys.argv[1], 'rb').read() == b'approved'",
            ),
            input_file=HostPath(source),
            checkpoint=lambda: None,
        )
    assert len(processes) == 1 and processes[0].returncode == 0
