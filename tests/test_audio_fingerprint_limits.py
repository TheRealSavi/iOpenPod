import struct
import subprocess
import sys
import tracemalloc
from types import SimpleNamespace
from typing import cast

from iopenpod.sync import audio_fingerprint
from iopenpod.sync.pc_library import PCTrack


def _write_sparse_mp4_with_large_cover(path, payload_size: int) -> None:
    """Write an MP4 metadata tree without materialising its cover payload."""

    covr_size = 8 + payload_size
    ilst_size = 8 + covr_size
    meta_size = 12 + ilst_size
    udta_size = 8 + meta_size
    moov_size = 8 + udta_size
    with path.open("wb") as stream:
        stream.write(struct.pack(">I4s", moov_size, b"moov"))
        stream.write(struct.pack(">I4s", udta_size, b"udta"))
        stream.write(struct.pack(">I4s", meta_size, b"meta"))
        stream.write(b"\0\0\0\0")
        stream.write(struct.pack(">I4s", ilst_size, b"ilst"))
        stream.write(struct.pack(">I4s", covr_size, b"covr"))
        stream.seek(payload_size - 1, 1)
        stream.write(b"\0")


def test_fpcalc_runs_below_normal_priority_on_windows() -> None:
    if sys.platform != "win32":
        return

    flags = int(audio_fingerprint._SP_KWARGS["creationflags"])
    assert flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS


def test_mp4_fingerprint_lookup_has_bounded_metadata_memory(tmp_path, monkeypatch) -> None:
    media = tmp_path / "movie.mp4"
    _write_sparse_mp4_with_large_cover(media, 16 * 1024 * 1024)
    cache = audio_fingerprint.FingerprintCache(tmp_path / "fingerprints.json")

    monkeypatch.setattr(
        audio_fingerprint.FingerprintCache,
        "get_instance",
        classmethod(lambda cls: cache),
    )
    monkeypatch.setattr(
        audio_fingerprint,
        "_compute_fingerprint_result",
        lambda _path, _fpcalc_path=None: audio_fingerprint._FingerprintResult("1,2,3"),
    )

    tracemalloc.start()
    try:
        result = audio_fingerprint.get_or_compute_fingerprint_with_status(
            media,
            fpcalc_path="fpcalc",
            write_to_file=False,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result == ("1,2,3", "computed")
    assert peak_bytes < 4 * 1024 * 1024


def test_compute_fingerprint_limits_decoder_work_to_two_minutes(tmp_path, monkeypatch) -> None:
    media = tmp_path / "song.mp3"
    media.write_bytes(b"audio")
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


def test_video_sources_never_launch_fingerprinting_processes(tmp_path, monkeypatch) -> None:
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"video")
    launches: list[list[str]] = []

    def record_process(command, **_kwargs):
        launches.append(command)
        return subprocess.CompletedProcess(
            command,
            returncode=2,
            stdout="",
            stderr="ERROR: Empty fingerprint",
        )

    monkeypatch.setattr(audio_fingerprint.subprocess, "run", record_process)

    identity = audio_fingerprint.compute_fingerprint(media, "fpcalc")

    assert identity is not None
    assert identity.startswith("video-sample-sha256-v1:")
    assert launches == []


def test_cached_acoustic_video_fingerprint_migrates_without_decoder(
    tmp_path,
    monkeypatch,
) -> None:
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"video")
    cache = audio_fingerprint.FingerprintCache(tmp_path / "fingerprints.json")
    cache.store(media, "1,2,3")
    launches: list[list[str]] = []

    monkeypatch.setattr(
        audio_fingerprint.FingerprintCache,
        "get_instance",
        classmethod(lambda cls: cache),
    )

    def record_process(command, **_kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(audio_fingerprint.subprocess, "run", record_process)

    identity, status = audio_fingerprint.get_or_compute_fingerprint_with_status(
        media,
        fpcalc_path="fpcalc",
        write_to_file=True,
    )

    assert identity is not None
    assert identity.startswith("video-sample-sha256-v1:")
    assert status == "computed"
    assert launches == []


def test_unchanged_unfingerprintable_file_is_not_retried(tmp_path, monkeypatch) -> None:
    media = tmp_path / "silent.mp3"
    media.write_bytes(b"audio-without-a-fingerprint")
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
    media = tmp_path / "temporarily-unreadable.mp3"
    media.write_bytes(b"audio")
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
