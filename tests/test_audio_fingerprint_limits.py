import subprocess
import sys
from types import SimpleNamespace
from typing import cast

from iopenpod.sync import audio_fingerprint
from iopenpod.sync.pc_library import PCTrack


def test_fpcalc_runs_below_normal_priority_on_windows() -> None:
    if sys.platform != "win32":
        return

    flags = int(audio_fingerprint._SP_KWARGS["creationflags"])
    assert flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS


def test_compute_fingerprint_limits_decoder_work_to_two_minutes(tmp_path, monkeypatch) -> None:
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"video")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="DURATION=120\nFINGERPRINT=1,2,3\n",
            stderr="",
        )

    monkeypatch.setattr(audio_fingerprint.subprocess, "run", fake_run)

    assert audio_fingerprint.compute_fingerprint(media, "fpcalc") == "1,2,3"
    assert commands == [["fpcalc", "-raw", "-length", "120", str(media)]]


def test_unchanged_unfingerprintable_file_is_not_retried(tmp_path, monkeypatch) -> None:
    media = tmp_path / "silent.mp4"
    media.write_bytes(b"video-without-audio")
    cache = audio_fingerprint.FingerprintCache(tmp_path / "fingerprints.json")
    attempts: list[str] = []

    monkeypatch.setattr(
        audio_fingerprint.FingerprintCache,
        "get_instance",
        classmethod(lambda cls: cache),
    )
    monkeypatch.setattr(audio_fingerprint, "read_fingerprint", lambda _path: None)

    def fake_compute(path, _fpcalc_path=None):
        attempts.append(str(path))
        return audio_fingerprint._FingerprintResult(
            None,
            deterministic_failure=True,
        )

    monkeypatch.setattr(audio_fingerprint, "_compute_fingerprint_result", fake_compute)

    first = audio_fingerprint.get_or_compute_fingerprint_with_status(
        media, fpcalc_path="fpcalc", write_to_file=False
    )
    second = audio_fingerprint.get_or_compute_fingerprint_with_status(
        media, fpcalc_path="fpcalc", write_to_file=False
    )

    assert first == (None, "failed")
    assert second == (None, "failed")
    assert attempts == [str(media)]


def test_transient_fingerprint_failure_is_retried(tmp_path, monkeypatch) -> None:
    media = tmp_path / "temporarily-unreadable.mp4"
    media.write_bytes(b"video")
    cache = audio_fingerprint.FingerprintCache(tmp_path / "fingerprints.json")
    attempts: list[str] = []

    monkeypatch.setattr(
        audio_fingerprint.FingerprintCache,
        "get_instance",
        classmethod(lambda cls: cache),
    )
    monkeypatch.setattr(audio_fingerprint, "read_fingerprint", lambda _path: None)

    def fake_compute(path, _fpcalc_path=None):
        attempts.append(str(path))
        return audio_fingerprint._FingerprintResult(None)

    monkeypatch.setattr(audio_fingerprint, "_compute_fingerprint_result", fake_compute)

    audio_fingerprint.get_or_compute_fingerprint_with_status(
        media, fpcalc_path="fpcalc", write_to_file=False
    )
    audio_fingerprint.get_or_compute_fingerprint_with_status(
        media, fpcalc_path="fpcalc", write_to_file=False
    )

    assert attempts == [str(media), str(media)]


def test_video_fingerprinting_uses_one_worker_even_when_more_are_requested() -> None:
    from iopenpod.sync.fingerprint_diff_engine import _fingerprint_worker_count

    tracks = [SimpleNamespace(is_video=False), SimpleNamespace(is_video=True)]

    assert _fingerprint_worker_count(8, cast(list[PCTrack], tracks)) == 1
