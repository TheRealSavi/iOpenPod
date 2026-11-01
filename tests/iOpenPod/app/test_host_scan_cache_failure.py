"""A Host Media Scan cache that cannot be saved is reported, not just logged."""

import base64
import shutil
from pathlib import Path

import pytest

from iOpenPod.app.host_media_library import (
    CACHE_ISSUE_SUBJECT,
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaScanIssue,
    HostMediaScanner,
    PendingHostMediaScan,
    _CachedTrackRecord,  # pyright: ignore[reportPrivateUsage]
)
from storage import AtomicHostFile, HostPath

FINGERPRINT = ",".join(str(value) for value in range(1, 41))
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"


def _pending(tmp_path: Path) -> PendingHostMediaScan:
    record = _CachedTrackRecord(
        HostPath(tmp_path / "track.mp3"),
        HostMediaFileKind.AUDIO,
        99,
        123,
        metadata_complete=True,
        acoustic_fingerprint=FINGERPRINT,
    )
    return PendingHostMediaScan(
        records=(),
        external_references=(),
        issues=(),
        cache=HostMediaCacheStats(),
        cached_records=(record,),
    )


def _blocked_cache(tmp_path: Path) -> AtomicHostFile:
    # A regular file where the cache directory should be fails on every platform.
    blocker = tmp_path / "cache-dir"
    blocker.write_bytes(b"not a directory")
    return AtomicHostFile(blocker / "host-media-library.json")


def _cache_issues(library: HostMediaLibrary) -> list[HostMediaScanIssue]:
    return [issue for issue in library.issues if issue.subject == CACHE_ISSUE_SUBJECT]


def test_unsaveable_cache_becomes_a_cache_issue_with_a_recommendation(
    tmp_path: Path,
) -> None:
    cache = _blocked_cache(tmp_path)

    result = HostMediaScanner(cache).complete(
        _pending(tmp_path), frozenset(), checkpoint=lambda: None
    )

    assert not cache.path.exists()
    (issue,) = _cache_issues(result)
    assert issue.path == HostPath(cache.path)
    assert "New scan results could not be saved to" in issue.detail
    assert str(cache.path) in issue.detail
    assert "fingerprinted again on the next scan" in issue.detail
    assert "Make that folder writable" in issue.detail


def test_saveable_cache_reports_no_cache_issue(tmp_path: Path) -> None:
    cache = AtomicHostFile(tmp_path / "cache" / "host-media-library.json")

    result = HostMediaScanner(cache).complete(
        _pending(tmp_path), frozenset(), checkpoint=lambda: None
    )

    assert cache.path.exists()
    assert _cache_issues(result) == []


def test_cache_issue_clears_once_a_later_save_succeeds(tmp_path: Path) -> None:
    cache = _blocked_cache(tmp_path)
    scanner = HostMediaScanner(cache)
    first = scanner.complete(_pending(tmp_path), frozenset(), checkpoint=lambda: None)
    assert len(_cache_issues(first)) == 1

    cache.path.parent.unlink()
    second = scanner.complete(_pending(tmp_path), frozenset(), checkpoint=lambda: None)

    assert cache.path.exists()
    assert _cache_issues(second) == []


def test_relative_cache_path_still_reports_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    blocker = tmp_path / "relative-dir"
    blocker.write_bytes(b"not a directory")
    cache = AtomicHostFile(Path("relative-dir") / "host-media-library.json")

    result = HostMediaScanner(cache).complete(
        _pending(tmp_path), frozenset(), checkpoint=lambda: None
    )

    (issue,) = _cache_issues(result)
    assert issue.path.path.is_absolute()


def _real_track_pending(tmp_path: Path) -> tuple[HostPath, PendingHostMediaScan]:
    path = tmp_path / "track.mp3"
    path.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    stat = path.stat()
    record = _CachedTrackRecord(
        HostPath(path),
        HostMediaFileKind.AUDIO,
        stat.st_size,
        stat.st_mtime_ns,
        metadata_complete=True,
        acoustic_fingerprint=FINGERPRINT,
    )
    pending = PendingHostMediaScan(
        records=(record,),
        external_references=(),
        issues=(),
        cache=HostMediaCacheStats(),
        cached_records=(record,),
    )
    return HostPath(path), pending


def test_targeted_reread_reports_a_failed_save(tmp_path: Path) -> None:
    track, pending = _real_track_pending(tmp_path)
    cache_dir = tmp_path / "cache"
    scanner = HostMediaScanner(AtomicHostFile(cache_dir / "host-media-library.json"))
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert _cache_issues(library) == []

    # The cache directory disappears between the scan and the Sync-time reread.
    shutil.rmtree(cache_dir)
    cache_dir.write_bytes(b"not a directory")
    refreshed = scanner.refresh_tracks(
        library, frozenset((track,)), checkpoint=lambda: None
    )

    (issue,) = _cache_issues(refreshed)
    assert "New scan results could not be saved to" in issue.detail


def test_targeted_reread_clears_a_stale_cache_issue(tmp_path: Path) -> None:
    track, pending = _real_track_pending(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.write_bytes(b"not a directory")
    scanner = HostMediaScanner(AtomicHostFile(cache_dir / "host-media-library.json"))
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(_cache_issues(library)) == 1

    cache_dir.unlink()
    refreshed = scanner.refresh_tracks(
        library, frozenset((track,)), checkpoint=lambda: None
    )

    assert _cache_issues(refreshed) == []
    assert (cache_dir / "host-media-library.json").exists()
    assert len(refreshed.snapshot.tracks) == 1
