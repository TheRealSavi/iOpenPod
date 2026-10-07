"""Scan metadata keeps probe safety without copying or hashing whole media."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.tags import inspection_tag_values
from storage import ConcurrentModificationError, HostPath, media_probe
from storage.media_processing import run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage.media_processing import ToolOutput

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"


@pytest.mark.parametrize("name", ["silent.mp4", "source.mkv", "chapters-cover.m4a"])
def test_scan_metadata_matches_captured_inspection_without_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    executable = shutil.which("ffprobe")
    if executable is None:
        pytest.skip("FFprobe is required for real scan metadata tests")
    path = tmp_path / "selected file.bin"
    path.write_bytes(base64.decodebytes((FIXTURES / f"{name}.b64").read_bytes()))
    inspector = MediaInspector(HostPath(executable))
    captured = inspector.inspect(HostPath(path), checkpoint=lambda: None)

    def forbidden_capture(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Metadata scans must not capture or hash the whole source")

    monkeypatch.setattr(
        "iOpenPod.app.media.inspection.capture_host_file", forbidden_capture
    )
    monkeypatch.setattr("storage.host_capture._capture", forbidden_capture)
    scanned = inspector.scan_metadata(HostPath(path), checkpoint=lambda: None)
    assert scanned.containers == captured.containers
    assert scanned.duration_seconds == captured.duration_seconds
    assert scanned.bitrate_bps == captured.bitrate_bps
    assert scanned.streams == captured.streams
    assert scanned.chapters == captured.chapters
    assert inspection_tag_values(scanned) == inspection_tag_values(captured)
    assert not hasattr(scanned, "fingerprint")


def _launch_script(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    script: str,
    *,
    before_launch: Callable[[], None] | None = None,
) -> list[subprocess.Popen[bytes]]:
    launch_process = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

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
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert "concat" not in args[args.index("-format_whitelist") + 1].split(",")
        assert "enable_drefs" not in args
        assert "use_absolute_path" not in args
        if os.name == "nt":
            assert args[-1] == str(source)
        else:
            assert args[-1] == f"/dev/fd/{pass_fds[0]}"
        if before_launch is not None:
            before_launch()
        process = launch_process(
            [sys.executable, "-c", script, args[-1]],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
            env=env,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    return processes


@pytest.mark.parametrize(
    ("script", "code", "timeout"),
    [
        ("import time; time.sleep(30)", "media.probe_timeout", 0.2),
        ("print('x' * 1000000)", "media.probe_output_limit", 5),
        ("import sys; sys.stderr.write('x' * 1000000)", "media.probe_output_limit", 5),
        ("raise SystemExit(3)", "media.probe_failed", 5),
    ],
)
def test_scan_probe_failures_are_bounded_and_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    code: str,
    timeout: float,
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"abc")
    processes = _launch_script(monkeypatch, source, script)
    with pytest.raises(MediaInspectionError) as caught:
        MediaInspector(
            HostPath(sys.executable), timeout_seconds=timeout, max_output_bytes=4096
        ).scan_metadata(HostPath(source), checkpoint=lambda: None)
    assert caught.value.code == code
    assert len(processes) == 1 and processes[0].poll() is not None
    # The input handle is released after failed or cancelled probes.
    source.write_bytes(b"released")


def test_cancel_scan_probe_reaps_child_and_releases_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"abc")
    processes = _launch_script(monkeypatch, source, "import time; time.sleep(30)")
    cancelled = InterruptedError("cancel scan")

    def checkpoint() -> None:
        if processes:
            raise cancelled

    with pytest.raises(InterruptedError) as caught:
        MediaInspector(HostPath(sys.executable)).scan_metadata(
            HostPath(source), checkpoint=checkpoint
        )
    assert caught.value is cancelled
    assert len(processes) == 1 and processes[0].poll() is not None
    source.write_bytes(b"released")


def test_scan_probe_rejects_source_change_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"abc")
    _launch_script(monkeypatch, source, "print('{}')")

    def changed_tool(
        executable: HostPath,
        arguments: tuple[str, ...],
        *,
        input_file: HostPath,
        checkpoint: Callable[[], None],
        timeout_seconds: float,
        max_output_bytes: int,
        max_stderr_bytes: int,
    ) -> ToolOutput:
        result = run_media_tool(
            executable,
            arguments,
            input_file=input_file,
            checkpoint=checkpoint,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            max_stderr_bytes=max_stderr_bytes,
        )
        source.write_bytes(b"changed after the probe")
        return result

    monkeypatch.setattr(media_probe, "run_media_tool", changed_tool)
    with pytest.raises(ConcurrentModificationError):
        MediaInspector(HostPath(sys.executable)).scan_metadata(
            HostPath(source), checkpoint=lambda: None
        )


def test_scan_probe_pins_the_input_until_child_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"abc")

    def replace_source() -> None:
        if os.name == "nt":
            with pytest.raises(PermissionError):
                source.write_bytes(b"different")
        else:
            source.rename(tmp_path / "original")
            source.write_bytes(b"different")

    processes = _launch_script(
        monkeypatch,
        source,
        "import json, sys; assert open(sys.argv[1], 'rb').read() == b'abc'; "
        "print(json.dumps({'format': {'size': '3', 'format_name': 'mov'}, "
        "'streams': [{'index': 0, 'codec_type': 'video'}]}))",
        before_launch=replace_source,
    )
    inspector = MediaInspector(HostPath(sys.executable))
    if os.name == "nt":
        result = inspector.scan_metadata(HostPath(source), checkpoint=lambda: None)
        assert result.containers == ("mov",)
    else:
        with pytest.raises(ConcurrentModificationError):
            inspector.scan_metadata(HostPath(source), checkpoint=lambda: None)
    assert len(processes) == 1 and processes[0].returncode == 0


def test_scan_probe_input_remains_seekable_and_size_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large video.bin"
    with source.open("wb") as stream:
        stream.seek(64 * 1024 * 1024)
        stream.write(b"tail")
    script = (
        "import json, sys; "
        "f = open(sys.argv[1], 'rb'); f.seek(-4, 2); "
        "assert f.read() == b'tail'; "
        "print(json.dumps({'format': {'size': '3', 'format_name': 'mov'}, "
        "'streams': [{'index': 0, 'codec_type': 'video'}]}))"
    )
    _launch_script(monkeypatch, source, script)
    with pytest.raises(MediaInspectionError) as caught:
        MediaInspector(HostPath(sys.executable)).scan_metadata(
            HostPath(source), checkpoint=lambda: None
        )
    assert caught.value.code == "media.probe_invalid"


@pytest.mark.parametrize("data", [b'{"format":NaN}', b'{"format":{},"format":{}}'])
def test_scan_metadata_rejects_malformed_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"abc")
    _launch_script(
        monkeypatch, source, f"import sys; sys.stdout.buffer.write({data!r})"
    )
    with pytest.raises(MediaInspectionError) as caught:
        MediaInspector(HostPath(sys.executable)).scan_metadata(
            HostPath(source), checkpoint=lambda: None
        )
    assert caught.value.code == "media.probe_invalid"
