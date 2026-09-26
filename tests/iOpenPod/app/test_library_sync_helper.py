import hashlib
import json
from dataclasses import replace
from pathlib import Path

from iOpenPod.app.host_media_fingerprint import FpcalcUnavailableError
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodMediaScanner,
)
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
from storage import AccessMode, FilesystemSession, HostPath, Storage
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

    with session:
        result = scanner.scan(
            session,
            _library(),
            library_sha256="a" * 64,
            persist=True,
            checkpoint=lambda: None,
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


def test_invalid_existing_helper_is_never_overwritten(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    helper_path = root / Path(str(LIBRARY_SYNC_HELPER_PATH))
    helper_path.parent.mkdir(parents=True)
    helper_path.write_bytes(b"not-json")

    with session:
        result = IPodMediaScanner(_Fingerprinter()).scan(
            session,
            _library(),
            library_sha256="d" * 64,
            persist=True,
            checkpoint=lambda: None,
        )

    assert result.persisted is False
    assert helper_path.read_bytes() == b"not-json"
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
