"""Cold video scans read in place; unchanged absent audio stays cached."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.iOpenPod.app.test_library_sync_helper import (
    _session,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.host_media_library import HostMediaScanner
from iOpenPod.app.library_sync_helper import LIBRARY_SYNC_HELPER_PATH, IPodMediaScanner
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata
from storage import AtomicHostFile, DevicePath, FilesystemSession, HostPath


@pytest.fixture(params=(False, True), ids=("no-audio", "with-audio"))
def video(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, bool]:
    executable = shutil.which("ffmpeg")
    if executable is None or shutil.which("fpcalc") is None:
        pytest.skip("Video analysis requires FFmpeg and fpcalc")
    has_audio = bool(request.param)
    path = tmp_path / "video.mp4"
    subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=64x64:r=10:d=16",
            *(
                ["-f", "lavfi", "-i", "sine=sample_rate=44100:duration=16"]
                if has_audio
                else []
            ),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path, has_audio


def test_device_video_analysis_avoids_captures_and_survives_scanner_restart(
    tmp_path: Path, video: tuple[Path, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, has_audio = video
    root, session = _session(tmp_path)
    path = DevicePath("iPod_Control/Music/F00/video.mp4")
    (root / str(path)).parent.mkdir(parents=True)
    shutil.copyfile(source, root / str(path))
    library = LibrarySnapshot(
        tracks=(
            Track(
                1,
                "Video",
                "",
                "",
                16_000,
                media_types=(MediaType.VIDEO,),
                metadata=TrackMetadata(location=str(path)),
            ),
        )
    )
    calls: list[DevicePath] = []
    native = FpcalcFingerprinter.fingerprint_device

    def analyze(
        self: FpcalcFingerprinter,
        session: FilesystemSession,
        source: DevicePath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        calls.append(source)
        return native(self, session, source, checkpoint=checkpoint)

    def reject_capture(*args: object, **kwargs: object) -> None:
        pytest.fail("Scanning a video must not capture its complete device file")

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint_device", analyze)
    monkeypatch.setattr(
        "iOpenPod.app.library_sync_helper.capture_device_file", reject_capture
    )
    cache_file = AtomicHostFile(tmp_path / "analysis.json")
    with session:
        for scan_number in range(2):
            result = IPodMediaScanner(analysis_cache_file=lambda _: cache_file).scan(
                session,
                library,
                library_sha256="a" * 64,
                persist=False,
                checkpoint=lambda: None,
                report_read_only=False,
            )
            assert result.cache.reused == scan_number
            assert bool(result.tracks) is has_audio
            assert bool(result.issues) is not has_audio
        assert calls == [path]
        # Changed file facts retire even a completed no-audio result.
        changed = root / str(path)
        stat = changed.stat()
        os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
        IPodMediaScanner(analysis_cache_file=lambda _: cache_file).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        assert calls == [path, path]
        assert not (root / str(LIBRARY_SYNC_HELPER_PATH)).exists()


def test_host_reuses_absent_audio_across_restarts_but_rechecks_changed_file(
    tmp_path: Path, video: tuple[Path, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, has_audio = video
    calls: list[HostPath] = []
    native = FpcalcFingerprinter.fingerprint

    def analyze(
        self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        calls.append(source)
        return native(self, source, checkpoint=checkpoint)

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", analyze)
    cache_file = AtomicHostFile(tmp_path / "host-cache.json")
    for scan_number in range(2):
        scanner = HostMediaScanner(cache_file)
        result = scanner.scan((), files=(HostPath(source),), checkpoint=lambda: None)
        assert result.cache.reused == scan_number
        library = scanner.complete(result, frozenset(), checkpoint=lambda: None)
        assert bool(library.sources[0].acoustic_fingerprint) is has_audio
    assert len(calls) == 1
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    HostMediaScanner(cache_file).scan(
        (), files=(HostPath(source),), checkpoint=lambda: None
    )
    assert len(calls) == 2
