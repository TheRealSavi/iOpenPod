import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from iOpenPod.app import library_sync_helper as helper_module
from iOpenPod.app.display_text import SourceText
from iOpenPod.app.host_media_fingerprint import FpcalcUnavailableError
from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.ipod_analysis_cache import IPodAnalysisCache, IPodAnalysisRecord
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodMediaScanner,
    IPodMediaScanProgress,
    IPodMediaScanStage,
    LibrarySyncHelperCancelledError,
    LibrarySyncHelperError,
    SyncDetails,
    SyncedImage,
    SyncedTrack,
    publish_sync_helper,
)
from iOpenPod.app.sync_plan import SyncPlanAction, prepare_sync_plan
from iOpenPod.app.sync_track_details import track_tag_sha256
from iPodDB.library import (
    IPodTrackDetails,
    LibrarySnapshot,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Track,
    TrackMetadata,
)
from storage import (
    AccessMode,
    AtomicHostFile,
    CopyResult,
    DeviceEntry,
    DevicePath,
    DevicePathNotFoundError,
    FilesystemSession,
    HostPath,
    Storage,
    StorageOperationError,
    VolumeDisconnectedError,
)
from storage.testing import VirtualStoragePlatform


def test_missing_fingerprinting_tool_does_not_abort_photos_or_repeat_the_failure(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    second = replace(
        library.tracks[0],
        track_id=8,
        ipod=replace(library.tracks[0].ipod, db_track_id=8)
        if library.tracks[0].ipod is not None
        else None,
    )
    library = replace(library, tracks=(*library.tracks, second))

    class Missing:
        calls = 0

        def fingerprint(self, source: HostPath, *, checkpoint: object) -> str:
            self.calls += 1
            raise FpcalcUnavailableError("Install fpcalc")

    missing = Missing()
    with session:
        result = IPodMediaScanner(missing).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert len(result.images) == 1
    assert len(result.issues) == 1
    assert missing.calls == 1


class _Fingerprinter:
    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.values: list[str] = ["1,2,3"]

    def fingerprint(
        self,
        source: HostPath,
        *,
        checkpoint: object,
    ) -> str:
        del checkpoint
        path = Path(source.path)
        assert not any(previous.exists() for previous in self.calls)
        self.calls.append(path)
        assert path.read_bytes().startswith(b"audio")
        return self.values.pop(0)


def _session(
    tmp_path: Path,
    *,
    access: AccessMode = AccessMode.READ_WRITE,
    device_id: str = "virtual-device-1",
    volume_id: str = "virtual-volume-1",
) -> tuple[Path, FilesystemSession]:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, label="Test iPod", device_id=device_id, volume_id=volume_id
    )
    storage = Storage(platform)
    mounted = storage.discover().volumes[0]
    return root, storage.open_session(mounted, access=access)


def _library() -> LibrarySnapshot:
    return LibrarySnapshot(
        tracks=(
            Track(
                7,
                "Song",
                "Artist",
                "Album",
                1_000,
                metadata=TrackMetadata(location="iPod_Control/Music/F00/SONG.MP3"),
                ipod=IPodTrackDetails(db_track_id=4_294_967_301),
            ),
        ),
        photos=PhotoLibrary(
            photos=(
                Photo(
                    91,
                    representations=(
                        PhotoRepresentation(
                            PhotoRepresentationKind.FULL_RESOLUTION,
                            0,
                            "Photos/Full Resolution/2026/09/image.jpg",
                            0,
                            11,
                            10,
                            10,
                        ),
                    ),
                ),
            )
        ),
    )


def _write_media(root: Path) -> None:
    track = root / "iPod_Control" / "Music" / "F00" / "SONG.MP3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"audio-one")
    image = root / "Photos" / "Full Resolution" / "2026" / "09" / "image.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image-bytes")


def test_scan_fingerprints_uncached_media_and_persists_helper(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    fingerprinter = _Fingerprinter()
    scanner = IPodMediaScanner(fingerprinter)
    progress: list[IPodMediaScanProgress] = []

    with session:
        result = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
            progress=progress.append,
        )

    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))
    document = json.loads(helper_path.read_bytes())
    assert result.persisted is True
    assert result.cache.reused == 0
    assert result.cache.fingerprinted == 2
    assert result.tracks[0].database_track_id == 4_294_967_301
    assert result.tracks[0].acoustic_fingerprint == "1,2,3"
    assert result.tracks[0].sync is None
    assert result.images[0].content_sha256 == hashlib.sha256(b"image-bytes").hexdigest()
    assert document["tracks"][0]["database_track_id"] == "4294967301"
    assert document["tracks"][0]["sync"] is None
    assert document["images"][0]["image_id"] == 91
    assert len(fingerprinter.calls) == 1
    assert not fingerprinter.calls[0].exists()
    fingerprinted = next(
        event.message
        for event in progress
        if event.message.startswith("Fingerprinting iPod Track")
    )
    assert isinstance(fingerprinted, SourceText)
    assert fingerprinted.source == "Fingerprinting iPod Track {index} of {total}…"
    assert dict(fingerprinted.parameters) == {"index": "1", "total": "1"}


def test_scan_releases_each_device_capture_before_copying_the_next(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    second = "iPod_Control/Music/F00/NEXT.MP3"
    (root / second).write_bytes(b"audio-two")
    library = replace(
        library,
        tracks=(
            *library.tracks,
            replace(
                library.tracks[0],
                track_id=8,
                metadata=replace(library.tracks[0].metadata, location=second),
                ipod=IPodTrackDetails(db_track_id=4_294_967_302),
            ),
        ),
    )
    fingerprinter = _Fingerprinter()
    fingerprinter.values = ["1,2,3", "4,5,6"]
    with session:
        result = IPodMediaScanner(fingerprinter).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
    assert len(result.tracks) == len(fingerprinter.calls) == 2
    assert not any(path.exists() for path in fingerprinter.calls)


def test_scan_reuses_helper_without_reading_media_content_again(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    initial_fingerprinter = _Fingerprinter()
    initial = IPodMediaScanner(initial_fingerprinter)

    with session:
        first = initial.scan(
            session,
            _library(),
            library_sha256="b" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        helper_before = (root / Path(str(LIBRARY_SYNC_HELPER_PATH))).read_bytes()
        reuse_fingerprinter = _Fingerprinter()
        reused = IPodMediaScanner(reuse_fingerprinter).scan(
            session,
            _library(),
            library_sha256="b" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        helper_after = (root / Path(str(LIBRARY_SYNC_HELPER_PATH))).read_bytes()

    assert reused.cache.reused == 2
    assert reused.cache.fingerprinted == 0
    assert reuse_fingerprinter.calls == []
    assert reused.helper_revision == first.helper_revision
    assert helper_after == helper_before


@pytest.mark.parametrize("version", [3, 4])
def test_prior_helper_is_reused_without_refingerprinting(
    tmp_path: Path, version: int
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))

    with session:
        IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="b" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        document = json.loads(helper_path.read_bytes())
        document["version"] = version
        document["tracks"][0]["sync"] = {
            "last_synced_at": "2026-09-18T20:00:00+00:00",
            "host_path_hint": "Music/Artist/Song.flac",
            "host_size_bytes": 123_456,
            "host_modified_ns": 1_789_762_000_000_000_000,
            "source_format": "flac",
            "ipod_format": "mp3",
            "was_transcoded": True,
        }
        if version == 4:
            document["tracks"][0]["sync"]["host_payload_sha256"] = "a" * 64
        records = {"tracks": document["tracks"], "images": document["images"]}
        document["catalog_sha256"] = hashlib.sha256(
            json.dumps(
                records,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        helper_path.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        fingerprinter = _Fingerprinter()
        upgraded = IPodMediaScanner(fingerprinter).scan(
            session,
            _library(),
            library_sha256="b" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        upgraded_document = json.loads(helper_path.read_bytes())

    assert upgraded.cache.reused == 2
    assert upgraded.cache.fingerprinted == 0
    assert fingerprinter.calls == []
    assert upgraded_document["version"] == 5
    sync = upgraded.tracks[0].sync
    assert sync is not None
    assert sync.ipod_artwork_id is None
    assert sync.ipod_tag_sha256 is None
    assert sync.ipod_baseline_pending is (version == 3)
    if version == 3:
        assert upgraded_document["tracks"][0]["sync"]["ipod_baseline_pending"] is True


def test_v3_migration_does_not_hide_manual_ipod_tag_edit(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))
    current_ipod_library = replace(
        _library(),
        tracks=(replace(_library().tracks[0], artist="Manual Artist"),),
    )

    with session:
        IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="c" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        document = json.loads(helper_path.read_bytes())
        document["version"] = 3
        document["tracks"][0]["sync"] = {
            "last_synced_at": "2026-09-18T20:00:00+00:00",
            "host_path_hint": str(tmp_path / "Music" / "Artist" / "Song.mp3"),
            "host_size_bytes": 123_456,
            "host_modified_ns": 1_789_762_000_000_000_000,
            "source_format": "mp3",
            "ipod_format": "mp3",
            "was_transcoded": False,
        }
        records = {"tracks": document["tracks"], "images": document["images"]}
        document["catalog_sha256"] = hashlib.sha256(
            json.dumps(
                records,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        helper_path.write_text(
            json.dumps(
                document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        upgraded = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            current_ipod_library,
            library_sha256="c" * 64,
            persist=False,
            checkpoint=lambda: None,
        )

    host_path = tmp_path / "Music" / "Artist" / "Song.mp3"
    host_track = Track(
        1,
        "Song",
        "Artist",
        "Album",
        1_000,
        metadata=TrackMetadata(location=str(host_path)),
    )
    host = HostMediaLibrary(
        LibrarySnapshot(tracks=(host_track,)),
        (
            HostMediaSource(
                HostPath(host_path),
                HostMediaFileKind.AUDIO,
                123_456,
                1_789_762_000_000_000_000,
                acoustic_fingerprint="1,2,3",
            ),
        ),
        (),
        HostMediaCacheStats(),
    )
    plan = prepare_sync_plan(
        host,
        replace(upgraded, images=()),
        current_ipod_library,
    )

    track_item = next(item for item in plan.items if item.host_path == str(host_path))
    assert track_item.action is SyncPlanAction.UPDATE
    assert track_item.metadata_changed is True


def test_valid_sync_details_round_trip_with_a_reused_fingerprint(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))

    with session:
        IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="f" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        document = json.loads(helper_path.read_bytes())
        document["tracks"][0]["sync"] = {
            "last_synced_at": "2026-09-18T20:00:00+00:00",
            "host_path_hint": "Music/Artist/Song.flac",
            "host_size_bytes": 123_456,
            "host_modified_ns": 1_789_762_000_000_000_000,
            "source_format": "flac",
            "ipod_format": "mp3",
            "was_transcoded": True,
        }
        records = {
            "tracks": document["tracks"],
            "images": document["images"],
        }
        canonical_records = json.dumps(
            records,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        document["catalog_sha256"] = hashlib.sha256(canonical_records).hexdigest()
        helper_path.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        result = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="f" * 64,
            persist=True,
            checkpoint=lambda: None,
        )

    sync = result.tracks[0].sync
    assert sync is not None
    assert sync.last_synced_at == "2026-09-18T20:00:00+00:00"
    assert sync.host_modified_ns == 1_789_762_000_000_000_000
    assert sync.was_transcoded is True
    assert sync.host_artwork_sha256 is None
    assert sync.ipod_artwork_id is None
    assert sync.ipod_tag_sha256 is None


def test_changed_track_is_refingerprinted_while_unchanged_image_is_reused(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    first_fingerprinter = _Fingerprinter()

    with session:
        IPodMediaScanner(first_fingerprinter).scan(
            session,
            _library(),
            library_sha256="c" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        track = root / "iPod_Control" / "Music" / "F00" / "SONG.MP3"
        track.write_bytes(b"audio-two-with-a-different-size")
        changed_fingerprinter = _Fingerprinter()
        changed_fingerprinter.values = ["9,8,7"]
        result = IPodMediaScanner(changed_fingerprinter).scan(
            session,
            _library(),
            library_sha256="c" * 64,
            persist=True,
            checkpoint=lambda: None,
        )

    assert result.cache.reused == 1
    assert result.cache.fingerprinted == 1
    assert result.tracks[0].acoustic_fingerprint == "9,8,7"
    assert len(changed_fingerprinter.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b"{}", b'{"version": 4}', b"[" * 10_000 + b"0" + b"]" * 10_000],
)
def test_invalid_existing_helper_is_never_overwritten(
    tmp_path: Path, payload: bytes
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))
    helper_path.parent.mkdir(parents=True)
    helper_path.write_bytes(payload)

    with session:
        result = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="d" * 64,
            persist=True,
            checkpoint=lambda: None,
        )

    assert result.persisted is False
    assert helper_path.read_bytes() == payload
    assert any("invalid" in issue.detail for issue in result.issues)
    assert any("left unchanged" in issue.detail for issue in result.issues)


def test_read_only_scan_returns_evidence_without_creating_helper(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path, access=AccessMode.READ_ONLY)
    _write_media(root)

    with session:
        result = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="e" * 64,
            persist=False,
            checkpoint=lambda: None,
        )

    assert len(result.tracks) == 1
    assert len(result.images) == 1
    assert result.persisted is False
    assert not (root / Path(str(LIBRARY_SYNC_HELPER_PATH))).exists()
    assert any("not safely writable" in issue.detail for issue in result.issues)


def test_publish_without_scan_merges_podcast_evidence_and_preserves_host_provenance(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    removed = replace(
        library.tracks[0],
        track_id=8,
        ipod=IPodTrackDetails(db_track_id=4_294_967_302),
        metadata=replace(
            library.tracks[0].metadata, location="iPod_Control/Music/F00/OLD.MP3"
        ),
    )
    (root / removed.metadata.location).write_bytes(b"audio-old")
    initial_library = replace(library, tracks=(*library.tracks, removed))
    details = SyncDetails(
        "2026-09-27T12:00:00+00:00",
        "Music/Artist/Song.flac",
        123_456,
        1_789_762_000_000_000_000,
        "flac",
        "mp3",
        True,
        host_artwork_sha256="a" * 64,
    )
    image_details = replace(
        details,
        host_path_hint="Pictures/image.jpg",
        source_format="jpg",
        ipod_format="jpg",
        was_transcoded=False,
    )
    fingerprinter = _Fingerprinter()
    fingerprinter.values = ["1,2,3", "4,5,6"]
    with session:
        scanned = IPodMediaScanner(fingerprinter).scan(
            session,
            initial_library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        initial = publish_sync_helper(
            session,
            initial_library,
            scanned,
            (SyncedTrack(scanned.tracks[0].path, "1,2,3", details),),
            (
                SyncedImage(
                    scanned.images[0].path,
                    scanned.images[0].content_sha256,
                    image_details,
                ),
            ),
            library_sha256="a" * 64,
        )
        podcast = replace(
            removed,
            track_id=9,
            title="Podcast Episode",
            ipod=IPodTrackDetails(db_track_id=4_294_967_303),
            metadata=replace(
                removed.metadata, location="iPod_Control/Music/F00/CAST.MP3"
            ),
        )
        (root / podcast.metadata.location).write_bytes(b"audio-podcast")
        (root / removed.metadata.location).unlink()
        retained = replace(library.tracks[0], track_id=10)
        committed = replace(library, tracks=(retained, podcast))
        result = publish_sync_helper(
            session,
            committed,
            None,
            (SyncedTrack(DevicePath(podcast.metadata.location), "7,8,9"),),
            library_sha256="b" * 64,
        )
        reused = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            committed,
            library_sha256="b" * 64,
            persist=False,
            checkpoint=lambda: None,
        )

    assert result.persisted
    assert initial.tracks[0].sync is not None
    assert initial.tracks[0].sync.host_artwork_sha256 == "a" * 64
    assert initial.tracks[0].sync.ipod_artwork_id == library.tracks[0].artwork_id
    assert initial.tracks[0].sync.ipod_tag_sha256 == track_tag_sha256(library.tracks[0])
    assert result.tracks[0] == replace(initial.tracks[0], track_id=10)
    assert result.images == initial.images
    assert len(result.tracks) == 2
    assert result.tracks[1].track_id == podcast.track_id
    assert result.tracks[1].acoustic_fingerprint == "7,8,9"
    assert result.tracks[1].sync is None
    assert reused.tracks == result.tracks
    assert reused.images == result.images
    assert reused.cache.reused == 3


@pytest.mark.parametrize("changed", ["track", "photo", "identity"])
def test_publish_without_scan_drops_stale_retained_evidence(
    tmp_path: Path, changed: str
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    with session:
        IPodMediaScanner(_Fingerprinter()).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        if changed == "identity":
            library = replace(
                library,
                tracks=(
                    replace(library.tracks[0], ipod=IPodTrackDetails(db_track_id=999)),
                ),
            )
        elif changed == "track":
            (root / library.tracks[0].metadata.location).write_bytes(b"changed-audio")
        else:
            (root / "Photos/Full Resolution/2026/09/image.jpg").write_bytes(
                b"changed-image"
            )
        result = publish_sync_helper(
            session, library, None, (), library_sha256="b" * 64
        )

    assert len(result.tracks) == (1 if changed == "photo" else 0)
    assert len(result.images) == (0 if changed == "photo" else 1)


def test_publish_without_scan_preserves_invalid_helper(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / str(LIBRARY_SYNC_HELPER_PATH)
    helper_path.parent.mkdir(parents=True)
    helper_path.write_bytes(b"not-json")
    with session, pytest.raises(LibrarySyncHelperError, match=r"invalid.*preserved"):
        publish_sync_helper(session, _library(), None, (), library_sha256="a" * 64)
    assert helper_path.read_bytes() == b"not-json"


def test_publish_with_scan_rejects_changed_helper(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / str(LIBRARY_SYNC_HELPER_PATH)
    with session:
        scanned = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        publish_sync_helper(session, _library(), scanned, (), library_sha256="a" * 64)
        before = helper_path.read_bytes()
        with pytest.raises(LibrarySyncHelperError, match="changed after Review"):
            publish_sync_helper(
                session, _library(), scanned, (), library_sha256="b" * 64
            )
        assert helper_path.read_bytes() == before


@pytest.mark.parametrize("missing", ["track", "photo"])
def test_publish_without_scan_omits_missing_retained_files_and_keeps_new_podcast(
    tmp_path: Path, missing: str
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    podcast = replace(
        library.tracks[0],
        track_id=8,
        ipod=IPodTrackDetails(db_track_id=4_294_967_302),
        metadata=replace(
            library.tracks[0].metadata, location="iPod_Control/Music/F00/CAST.MP3"
        ),
    )
    (root / podcast.metadata.location).write_bytes(b"audio-podcast")
    with session:
        scanned = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        missing_path = (
            scanned.tracks[0].path if missing == "track" else scanned.images[0].path
        )
        (root / str(missing_path)).unlink()
        result = publish_sync_helper(
            session,
            replace(library, tracks=(*library.tracks, podcast)),
            None,
            (SyncedTrack(DevicePath(podcast.metadata.location), "7,8,9"),),
            library_sha256="b" * 64,
        )

    assert result.persisted
    assert result.tracks[-1].acoustic_fingerprint == "7,8,9"
    assert len(result.tracks) == (1 if missing == "track" else 2)
    assert len(result.images) == (0 if missing == "photo" else 1)
    assert len(result.issues) == 1
    assert "omitted" in result.issues[0].detail


@pytest.mark.parametrize("failed", ["track", "photo"])
@pytest.mark.parametrize("disconnected", [False, True])
def test_publish_without_scan_only_tolerates_retained_file_access_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed: str,
    disconnected: bool,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / str(LIBRARY_SYNC_HELPER_PATH)
    with session:
        scanned = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        failed_path = (
            scanned.tracks[0].path if failed == "track" else scanned.images[0].path
        )
        before = helper_path.read_bytes()
        stat = FilesystemSession.stat

        def fail_stat(self: FilesystemSession, path: DevicePath) -> DeviceEntry:
            if path == failed_path:
                if disconnected:
                    raise VolumeDisconnectedError("Device disconnected")
                raise StorageOperationError("Permission denied")
            return stat(self, path)

        monkeypatch.setattr(FilesystemSession, "stat", fail_stat)
        if disconnected:
            with pytest.raises(VolumeDisconnectedError):
                publish_sync_helper(
                    session, _library(), None, (), library_sha256="b" * 64
                )
            assert helper_path.read_bytes() == before
        else:
            result = publish_sync_helper(
                session, _library(), None, (), library_sha256="b" * 64
            )
            assert result.persisted
            assert len(result.tracks) == (0 if failed == "track" else 1)
            assert len(result.images) == (0 if failed == "photo" else 1)
            assert len(result.issues) == 1
            assert "Permission denied" in result.issues[0].detail


def test_publish_without_scan_rejects_missing_newly_committed_media(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    path = DevicePath(_library().tracks[0].metadata.location)
    (root / str(path)).unlink()
    with session, pytest.raises(DevicePathNotFoundError):
        publish_sync_helper(
            session,
            _library(),
            None,
            (SyncedTrack(path, "7,8,9"),),
            library_sha256="a" * 64,
        )
    assert not (root / str(LIBRARY_SYNC_HELPER_PATH)).exists()


def _cache_factory(directory: Path) -> Callable[[str], AtomicHostFile]:
    return lambda identity: AtomicHostFile(directory / f"{identity}.json")


def _two_tracks(root: Path) -> LibrarySnapshot:
    library = _library()
    second = replace(
        library.tracks[0],
        track_id=8,
        ipod=IPodTrackDetails(db_track_id=4294967302),
        metadata=replace(
            library.tracks[0].metadata, location="iPod_Control/Music/F00/NEXT.MP3"
        ),
    )
    (root / second.metadata.location).write_bytes(b"audio-two")
    return replace(library, tracks=(*library.tracks, second), photos=None)


def test_pre_review_analysis_survives_new_scanner_without_device_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, session = _session(tmp_path, access=AccessMode.READ_ONLY)
    _write_media(root)
    cache_file = _cache_factory(tmp_path / "cache")
    with session:
        first = IPodMediaScanner(_Fingerprinter(), analysis_cache_file=cache_file).scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
        counts: dict[DevicePath, int] = {}
        stat = FilesystemSession.stat

        def count_stat(self: FilesystemSession, path: DevicePath) -> DeviceEntry:
            counts[path] = counts.get(path, 0) + 1
            return stat(self, path)

        monkeypatch.setattr(FilesystemSession, "stat", count_stat)
        cached_file = next((tmp_path / "cache").glob("*.json"))
        before = cached_file.stat().st_mtime_ns
        fingerprinter = _Fingerprinter()
        second = IPodMediaScanner(fingerprinter, analysis_cache_file=cache_file).scan(
            session,
            _library(),
            library_sha256="b" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert second.cache.reused == 2
    assert second.cache.fingerprinted == 0
    assert second.tracks == first.tracks
    assert second.images == first.images
    assert second.tracks[0].sync is None
    assert second.images[0].sync is None
    assert fingerprinter.calls == []
    assert counts[first.tracks[0].path] == counts[first.images[0].path] == 1
    assert cached_file.stat().st_mtime_ns == before
    assert not (root / str(LIBRARY_SYNC_HELPER_PATH)).exists()


@pytest.mark.parametrize("changed", ["size", "mtime", "identity", "path"])
def test_host_analysis_cache_rejects_stale_track_facts(
    tmp_path: Path,
    changed: str,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = replace(_library(), photos=None)
    cache_file = _cache_factory(tmp_path / "cache")
    with session:
        IPodMediaScanner(_Fingerprinter(), analysis_cache_file=cache_file).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        path = root / library.tracks[0].metadata.location
        if changed == "size":
            path.write_bytes(b"audio-changed-size")
        elif changed == "mtime":
            ns = path.stat().st_mtime_ns + 10_000_000_000
            os.utime(path, ns=(ns, ns))
        elif changed == "identity":
            library = replace(
                library,
                tracks=(
                    replace(library.tracks[0], ipod=IPodTrackDetails(db_track_id=999)),
                ),
            )
        else:
            path.rename(path.with_name("MOVED.MP3"))
            library = replace(
                library,
                tracks=(
                    replace(
                        library.tracks[0],
                        metadata=replace(
                            library.tracks[0].metadata,
                            location="iPod_Control/Music/F00/MOVED.MP3",
                        ),
                    ),
                ),
            )
        fingerprinter = _Fingerprinter()
        result = IPodMediaScanner(fingerprinter, analysis_cache_file=cache_file).scan(
            session,
            library,
            library_sha256="b" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
    assert result.cache.fingerprinted == 1
    assert len(fingerprinter.calls) == 1


@pytest.mark.parametrize("identity_kind", ["device", "volume"])
def test_host_analysis_cache_isolates_devices_and_volumes(
    tmp_path: Path,
    identity_kind: str,
) -> None:
    cache_file = _cache_factory(tmp_path / "cache")
    for number in range(2):
        directory = tmp_path / str(number)
        directory.mkdir()
        root, session = _session(
            directory,
            device_id=f"device-{number}"
            if identity_kind == "device"
            else "same-device",
            volume_id=f"volume-{number}"
            if identity_kind == "volume"
            else "same-volume",
        )
        _write_media(root)
        path = root / _library().tracks[0].metadata.location
        os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        fingerprinter = _Fingerprinter()
        with session:
            result = IPodMediaScanner(
                fingerprinter, analysis_cache_file=cache_file
            ).scan(
                session,
                replace(_library(), photos=None),
                library_sha256="a" * 64,
                persist=False,
                checkpoint=lambda: None,
            )
        assert result.cache.fingerprinted == 1
        assert len(fingerprinter.calls) == 1
    assert len(tuple((tmp_path / "cache").glob("*.json"))) == 2


def test_cached_analysis_never_restores_lost_or_invalid_sync_provenance(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    cache_file = _cache_factory(tmp_path / "cache")
    scanner = IPodMediaScanner(_Fingerprinter(), analysis_cache_file=cache_file)
    with session:
        scanned = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        details = SyncDetails("2026-10-07", "Music/song.mp3", 9, 1, "mp3", "mp3", False)
        publish_sync_helper(
            session,
            _library(),
            scanned,
            (SyncedTrack(scanned.tracks[0].path, "1,2,3", details),),
            library_sha256="a" * 64,
        )
        committed = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        assert committed.tracks[0].sync is not None
        helper = root / str(LIBRARY_SYNC_HELPER_PATH)
        helper.write_bytes(b"damaged provenance")
        result = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        assert result.cache.reused == 2
        assert result.tracks[0].sync is None
        assert helper.read_bytes() == b"damaged provenance"
        with pytest.raises(LibrarySyncHelperError, match="invalid"):
            publish_sync_helper(
                session, _library(), result, (), library_sha256="a" * 64
            )


def test_scan_cancellation_checkpoints_completed_analysis_and_cleans_captures(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _two_tracks(root)
    cache_file = _cache_factory(tmp_path / "cache")
    temporary = tmp_path / "captures"
    temporary.mkdir()
    cancelled = Event()

    def checkpoint() -> None:
        if cancelled.is_set():
            raise LibrarySyncHelperCancelledError

    def progress(event: IPodMediaScanProgress) -> None:
        if event.stage is IPodMediaScanStage.TRACKS and event.completed == 1:
            cancelled.set()

    with session:
        scanner = IPodMediaScanner(
            _Fingerprinter(),
            analysis_cache_file=cache_file,
            temporary_directory=temporary,
        )
        with pytest.raises(LibrarySyncHelperCancelledError):
            scanner.scan(
                session,
                library,
                library_sha256="a" * 64,
                persist=False,
                checkpoint=checkpoint,
                progress=progress,
            )
        assert list(temporary.iterdir()) == []
        cancelled.clear()
        next_fingerprinter = _Fingerprinter()
        next_fingerprinter.values = ["4,5,6"]
        result = IPodMediaScanner(
            next_fingerprinter, analysis_cache_file=cache_file
        ).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=checkpoint,
        )
    assert result.cache.reused == result.cache.fingerprinted == 1
    assert len(next_fingerprinter.calls) == 1
    assert not (root / str(LIBRARY_SYNC_HELPER_PATH)).exists()


def test_device_copy_overlaps_previous_decode_with_two_capture_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _two_tracks(root)
    temporary = tmp_path / "captures"
    temporary.mkdir()
    decoding = Event()
    copying_next = Event()
    decoded_paths: list[Path] = []
    copy_to_host = FilesystemSession.copy_to_host

    class BlockingFingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            checkpoint()
            decoded_paths.append(Path(source.path))
            if len(decoded_paths) == 1:
                decoding.set()
                assert copying_next.wait(5), "The next copy did not overlap decoding"
            return "1,2,3"

    def copying(
        self: FilesystemSession,
        source: DevicePath,
        destination: HostPath,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> CopyResult:
        if source.name == "NEXT.MP3":
            assert decoding.wait(5)
            assert len(list(temporary.iterdir())) == 2
            copying_next.set()
        return copy_to_host(self, source, destination, progress=progress)

    monkeypatch.setattr(FilesystemSession, "copy_to_host", copying)
    with session:
        result = IPodMediaScanner(
            BlockingFingerprinter(), temporary_directory=temporary
        ).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
    assert len(result.tracks) == 2
    assert len(decoded_paths) == 2
    assert list(temporary.iterdir()) == []


@pytest.mark.parametrize("cached", [False, True])
def test_scan_disconnect_aborts_instead_of_publishing_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cached: bool,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    cache_file = _cache_factory(tmp_path / "cache")
    scanner = IPodMediaScanner(_Fingerprinter(), analysis_cache_file=cache_file)
    with session:
        if cached:
            scanner.scan(
                session,
                _library(),
                library_sha256="a" * 64,
                persist=False,
                checkpoint=lambda: None,
            )
        stat = FilesystemSession.stat

        def disconnect(self: FilesystemSession, path: DevicePath) -> DeviceEntry:
            if str(path) == _library().tracks[0].metadata.location:
                raise VolumeDisconnectedError("Unplugged")
            return stat(self, path)

        monkeypatch.setattr(FilesystemSession, "stat", disconnect)
        with pytest.raises(VolumeDisconnectedError):
            scanner.scan(
                session,
                _library(),
                library_sha256="a" * 64,
                persist=False,
                checkpoint=lambda: None,
            )
    assert not (root / str(LIBRARY_SYNC_HELPER_PATH)).exists()


def test_changed_during_decode_is_not_remembered_in_host_cache(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = replace(_library(), photos=None)
    cache_file = _cache_factory(tmp_path / "cache")

    class MutatingFingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            checkpoint()
            (root / library.tracks[0].metadata.location).write_bytes(b"audio-changed")
            return "1,2,3"

    with session:
        result = IPodMediaScanner(
            MutatingFingerprinter(), analysis_cache_file=cache_file
        ).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        assert result.tracks == ()
        assert any("changed while" in issue.detail for issue in result.issues)
        fingerprinter = _Fingerprinter()
        next_result = IPodMediaScanner(
            fingerprinter, analysis_cache_file=cache_file
        ).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
    assert next_result.cache.fingerprinted == 1
    assert len(fingerprinter.calls) == 1


def test_helper_writer_enforces_decoded_budget_before_replacing_previous_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    initial_library = replace(_library(), photos=None)
    with session:
        scanned = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            initial_library,
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        helper_path = root / str(LIBRARY_SYNC_HELPER_PATH)
        before = helper_path.read_bytes()
        library = _two_tracks(root)
        monkeypatch.setattr(helper_module, "_MAX_DECODED_ACOUSTIC_BYTES", 6)
        with pytest.raises(LibrarySyncHelperError, match="decoded acoustic"):
            publish_sync_helper(
                session,
                library,
                scanned,
                (
                    SyncedTrack(
                        DevicePath(library.tracks[1].metadata.location), "4,5,6"
                    ),
                ),
                library_sha256="b" * 64,
            )
        assert helper_path.read_bytes() == before


def test_helper_v5_round_trips_compact_fingerprints(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    raw = ",".join(str(4_000_000_000 + number) for number in range(1000))
    fingerprinter = _Fingerprinter()
    fingerprinter.values = [raw]
    with session:
        first = IPodMediaScanner(fingerprinter).scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
        )
        helper_payload = (root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
        assert len(helper_payload) < len(raw) // 2
        assert json.loads(helper_payload)["version"] == 5
        second = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
    assert second.tracks == first.tracks
    assert second.cache.reused == 2


def test_committed_empty_acoustic_does_not_enter_host_analysis_cache(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = replace(_library(), photos=None)
    path = DevicePath(library.tracks[0].metadata.location)
    details = SyncDetails("2026-10-07", "Music/song.mp3", 9, 1, "mp3", "mp3", False)
    cache_file = _cache_factory(tmp_path / "cache")
    with session:
        publish_sync_helper(
            session,
            library,
            None,
            (SyncedTrack(path, "", details),),
            library_sha256="a" * 64,
        )
        scanner = IPodMediaScanner(_Fingerprinter(), analysis_cache_file=cache_file)
        for _ in range(2):
            result = scanner.scan(
                session,
                library,
                library_sha256="a" * 64,
                persist=False,
                checkpoint=lambda: None,
                report_read_only=False,
            )
            assert result.cache.reused == 1
            assert result.tracks[0].sync is not None
            assert result.tracks[0].acoustic_fingerprint == ""
            assert result.issues == ()
    assert not (tmp_path / "cache").exists()


def test_warm_ipod_scan_reuses_validated_host_cache_without_loading_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    fingerprinter = _Fingerprinter()
    scanner = IPodMediaScanner(
        fingerprinter, analysis_cache_file=_cache_factory(tmp_path / "cache")
    )
    with session:
        scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )

        def no_reread(
            self: AtomicHostFile, *, max_bytes: int | None = None
        ) -> bytes | None:
            pytest.fail("An unchanged Host analysis cache was reread")

        monkeypatch.setattr(AtomicHostFile, "read_bytes", no_reread)
        result = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert result.cache.reused == 2
    assert len(fingerprinter.calls) == 1
    assert result.issues == ()


@pytest.mark.parametrize("change", ["replacement", "invalid", "deletion", "nested"])
def test_warm_ipod_scan_retires_cache_memory_after_external_change(
    tmp_path: Path,
    change: str,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = replace(_library(), photos=None)
    fingerprinter = _Fingerprinter()
    fingerprinter.values = ["1,2,3", "7,8,9"]
    scanner = IPodMediaScanner(
        fingerprinter, analysis_cache_file=_cache_factory(tmp_path / "cache")
    )
    with session:
        first = scanner.scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
        path = next((tmp_path / "cache").glob("*.json"))
        file = AtomicHostFile(path)
        if change == "deletion":
            path.unlink()
        elif change == "invalid":
            file.replace_bytes(b"not-json")
        elif change == "nested":
            file.replace_bytes(b"[" * 10_000 + b"0" + b"]" * 10_000)
        else:
            replacement = IPodAnalysisCache(file, path.stem)
            record = first.tracks[0]
            replacement.remember(
                IPodAnalysisRecord(
                    "database",
                    record.database_track_id,
                    record.path,
                    record.size_bytes,
                    record.modified_ns,
                    "4,5,6",
                )
            )
            replacement.save(force=True)
        result = scanner.scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    if change == "replacement":
        assert len(fingerprinter.calls) == 1
        assert result.tracks[0].acoustic_fingerprint == "4,5,6"
        assert result.cache.reused == 1
    else:
        assert len(fingerprinter.calls) == 2
        assert result.tracks[0].acoustic_fingerprint == "7,8,9"
        assert result.cache.fingerprinted == 1
    assert bool(result.issues) is (change in {"invalid", "nested"})


def test_failed_host_cache_save_retries_without_refingerprinting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    fingerprinter = _Fingerprinter()
    scanner = IPodMediaScanner(
        fingerprinter, analysis_cache_file=_cache_factory(tmp_path / "cache")
    )
    replace_bytes = AtomicHostFile.replace_bytes
    calls = 0

    def fail_first(self: AtomicHostFile, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("Cache temporarily unavailable")
        replace_bytes(self, data)

    monkeypatch.setattr(AtomicHostFile, "replace_bytes", fail_first)
    with session:
        first = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
        assert any("temporarily unavailable" in issue.detail for issue in first.issues)
        second = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert calls == 2
    assert len(fingerprinter.calls) == 1
    assert second.cache.reused == 2
    assert second.issues == ()
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


@pytest.mark.parametrize("cache_kind", ["helper", "host"])
@pytest.mark.parametrize("change", ["size", "mtime"])
def test_cached_track_is_revalidated_after_waiting_for_previous_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_kind: str,
    change: str,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _two_tracks(root)
    cache_file = _cache_factory(tmp_path / "cache") if cache_kind == "host" else None
    observed_cached_track = Event()
    second_path = DevicePath(library.tracks[1].metadata.location)
    disk_path = root / str(second_path)
    stat = FilesystemSession.stat

    def observe(self: FilesystemSession, path: DevicePath) -> DeviceEntry:
        entry = stat(self, path)
        if path == second_path:
            observed_cached_track.set()
        return entry

    class BlockingFingerprinter:
        calls = 0

        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            checkpoint()
            self.calls += 1
            if self.calls == 1:
                assert observed_cached_track.wait(5), "The cached file was not observed"
                if change == "size":
                    disk_path.write_bytes(
                        b"audio-changed-while-waiting-for-previous-decode"
                    )
                else:
                    modified_ns = disk_path.stat().st_mtime_ns + 10_000_000_000
                    os.utime(disk_path, ns=(modified_ns, modified_ns))
                return "4,5,6"
            return "7,8,9"

    with session:
        seeded = IPodMediaScanner(
            _Fingerprinter(), analysis_cache_file=cache_file
        ).scan(
            session,
            replace(library, tracks=(library.tracks[1],)),
            library_sha256="a" * 64,
            persist=cache_kind == "helper",
            checkpoint=lambda: None,
            report_read_only=False,
        )
        fingerprinter = BlockingFingerprinter()
        monkeypatch.setattr(FilesystemSession, "stat", observe)
        result = IPodMediaScanner(fingerprinter, analysis_cache_file=cache_file).scan(
            session,
            library,
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert fingerprinter.calls == 2
    assert result.cache.fingerprinted == 2
    assert result.cache.reused == 0
    assert result.tracks[1].acoustic_fingerprint == "7,8,9"
    if change == "size":
        assert result.tracks[1].size_bytes == disk_path.stat().st_size
        assert result.tracks[1].size_bytes != seeded.tracks[0].size_bytes
    else:
        assert result.tracks[1].modified_ns == disk_path.stat().st_mtime_ns
        assert result.tracks[1].modified_ns != seeded.tracks[0].modified_ns
    assert result.issues == ()


@pytest.mark.parametrize(
    "error",
    [
        OSError("Cache directory unavailable"),
        StorageOperationError("Cache storage unavailable"),
    ],
)
def test_host_cache_factory_failure_is_optional_and_retried_on_next_scan(
    tmp_path: Path,
    error: Exception,
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    factory_calls = 0

    def cache_factory(identity: str) -> AtomicHostFile:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            raise error
        return AtomicHostFile(tmp_path / "cache" / f"{identity}.json")

    fingerprinter = _Fingerprinter()
    fingerprinter.values = ["1,2,3", "1,2,3"]
    scanner = IPodMediaScanner(fingerprinter, analysis_cache_file=cache_factory)
    with session:
        first = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
        second = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
        third = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=False,
            checkpoint=lambda: None,
            report_read_only=False,
        )
    assert len(first.tracks) == len(first.images) == 1
    assert len(first.issues) == 1
    assert first.issues[0].subject == "Host iPod analysis cache"
    assert str(error) in first.issues[0].detail
    assert first.cache.fingerprinted == second.cache.fingerprinted == 2
    assert third.cache.reused == 2
    assert second.issues == third.issues == ()
    assert factory_calls == 2
    assert len(fingerprinter.calls) == 2
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1
