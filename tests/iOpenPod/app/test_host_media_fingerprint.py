"""Bounded fpcalc execution and raw-fingerprint validation."""

import io
import os
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    FpcalcUnavailableError,
)
from storage import HostPath


class _CompletedProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode

    def kill(self) -> None:
        self.killed = True


@pytest.mark.parametrize(
    ("source_name", "input_suffix"),
    [("song.flac", None), ("source", ".flac")],
)
def test_fpcalc_uses_raw_algorithm_two_with_a_bounded_analysis_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_name: str,
    input_suffix: str | None,
) -> None:
    commands: list[list[str]] = []

    def launch(args: list[str], **_kwargs: object) -> _CompletedProcess:
        commands.append(args)
        return _CompletedProcess(b"DURATION=120\nFINGERPRINT=1,2,4294967295\n")

    monkeypatch.setattr(subprocess, "Popen", launch)
    executable = HostPath(tmp_path / "fpcalc")
    source = HostPath(tmp_path / source_name)
    (tmp_path / source_name).write_bytes(b"source")

    fingerprint = FpcalcFingerprinter(
        executable,
        timeout_seconds=1,
        max_output_bytes=1024,
        input_suffix=input_suffix,
    ).fingerprint(source, checkpoint=lambda: None)

    assert fingerprint == "1,2,4294967295"
    assert [command[:-1] for command in commands] == [
        [
            os.fspath(executable),
            "-algorithm",
            "2",
            "-raw",
            "-length",
            "120",
            "-text",
            "-format",
            "flac",
        ]
    ]
    if os.name == "nt":
        assert commands[0][-1] == os.fspath(source)
    else:
        assert commands[0][-1].startswith("/dev/fd/")


@pytest.mark.parametrize(
    ("source_name", "input_suffix"),
    [("Mix.m3u8", None), ("source", ".m3u8")],
)
def test_fpcalc_refuses_playlist_inputs_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_name: str,
    input_suffix: str | None,
) -> None:
    def launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Playlist inputs must never reach the decoder")

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(FpcalcError, match="single-file decoder"):
        FpcalcFingerprinter(
            HostPath(tmp_path / "fpcalc"), input_suffix=input_suffix
        ).fingerprint(HostPath(tmp_path / source_name), checkpoint=lambda: None)


@pytest.mark.parametrize(
    "payload",
    [
        b"DURATION=0\n",
        b"FINGERPRINT=\n",
        b"FINGERPRINT=-1,2\n",
        b"FINGERPRINT=4294967296\n",
        b"FINGERPRINT=1,2\nFINGERPRINT=3,4\n",
    ],
)
def test_fpcalc_rejects_missing_or_invalid_raw_fingerprints(
    tmp_path: Path, payload: bytes
) -> None:
    process = _CompletedProcess(payload)
    source = tmp_path / "song.mp3"
    source.write_bytes(b"source")

    def launch(_args: list[str], **_kwargs: object) -> _CompletedProcess:
        return process

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(subprocess, "Popen", launch)
        fingerprinter = FpcalcFingerprinter(
            HostPath(tmp_path / "fpcalc.exe"),
            timeout_seconds=1,
            max_output_bytes=1024,
        )

        with pytest.raises(FpcalcError):
            fingerprinter.fingerprint(
                HostPath(source),
                checkpoint=lambda: None,
            )


def test_fpcalc_reports_a_missing_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_executable(_name: str) -> None:
        return None

    monkeypatch.setattr(
        "storage.media_processing.find_host_executable", missing_executable
    )

    with pytest.raises(FpcalcUnavailableError, match="Install Chromaprint") as error:
        FpcalcFingerprinter().fingerprint(
            HostPath(tmp_path / "song.mp3"),
            checkpoint=lambda: None,
        )
    assert "PATH" in str(error.value)


@pytest.mark.parametrize(
    ("stderr", "returncode", "message"),
    [
        (b"decoder rejected input", 2, "decoder rejected input"),
        (b"", 2, "fpcalc could not fingerprint the file"),
        (b"x" * 65537, 0, "fpcalc output exceeds the scan limit"),
    ],
    ids=("decoder-error", "no-detail", "stderr-limit"),
)
def test_fpcalc_preserves_failure_details_and_scan_diagnostic_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: bytes,
    returncode: int,
    message: str,
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"source")

    def launch(_args: list[str], **_kwargs: object) -> _CompletedProcess:
        return _CompletedProcess(b"FINGERPRINT=1,2\n", stderr, returncode)

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(FpcalcError, match=message):
        FpcalcFingerprinter(HostPath(tmp_path / "fpcalc")).fingerprint(
            HostPath(source), checkpoint=lambda: None
        )


def test_fpcalc_reports_tool_start_failure_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"source")

    def launch(_args: list[str], **_kwargs: object) -> None:
        raise OSError("not executable")

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(FpcalcUnavailableError, match="Could not start fpcalc"):
        FpcalcFingerprinter(HostPath(tmp_path / "fpcalc")).fingerprint(
            HostPath(source), checkpoint=lambda: None
        )


@pytest.mark.skipif(shutil.which("fpcalc") is None, reason="fpcalc is required")
def test_real_fpcalc_reads_pinned_input_without_changing_source(tmp_path: Path) -> None:
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(bytes(44100 * 8 * 2))
    before = source.read_bytes()
    fingerprint = FpcalcFingerprinter().fingerprint(
        HostPath(source), checkpoint=lambda: None
    )
    assert fingerprint and all(part.isdigit() for part in fingerprint.split(","))
    assert source.read_bytes() == before
