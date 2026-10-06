import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from iOpenPod.app.display_text import SourceText
from iOpenPod.app.host_media_fingerprint import FpcalcUnavailableError
from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodMediaScanner,
    IPodMediaScanProgress,
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
) -> tuple[Path, FilesystemSession]:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Test iPod")
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
    assert upgraded_document["version"] == 4
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


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b'{"version": 4}'])
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
