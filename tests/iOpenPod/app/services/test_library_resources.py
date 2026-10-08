"""Prepare, publish, and recover dependent Library files through the application."""

import base64
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event

import pytest
from tests.iPodDB.library.test_media_lifecycle import prepared_media
from tests.iPodDB.library.test_write_artwork import BLUE, TARGET, with_shared_artwork

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.library_write_inspection import inspect_library_write
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services import device_coordinator, library_resources
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    CoverFormat,
    CoverPixelFormat,
    IPodLibrary,
    LibrarySnapshot,
    WriteResources,
)
from storage import (
    AccessMode,
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    HardwareIdentifiers,
    Storage,
    StorageOperationError,
)
from storage.content_workspace import ContentFileBuffer, StagedContent
from storage.testing import VirtualStoragePlatform


@dataclass(frozen=True)
class Device:
    root: Path
    storage: Storage
    platform: VirtualStoragePlatform
    coordinator: DeviceCoordinator
    original: dict[str, bytes]

    @property
    def active(self) -> ActiveIPod:
        active = self.coordinator.active_ipod
        assert active is not None
        return active

    def prepare(
        self, snapshot: LibrarySnapshot, *, cover: bool = False, delete: bool = False
    ) -> LibraryReview:
        return self.coordinator.prepare_library(
            LibraryPreparationRequest(
                snapshot,
                self.active,
                1,
                1,
                artwork=(BLUE,) if cover else (),
                delete_omissions=delete,
            ),
            lambda _: None,
            Event(),
        )

    def save(
        self,
        review: LibraryReview,
        progress: Callable[[WriteProgress], None] = lambda _: None,
    ) -> LibrarySaveResult:
        """Keep recovery files so resource tests can verify complete restoration."""
        return self.coordinator.save_library(
            review, self.active, progress, Event(), retain_recovery=True
        )

    def restore(self, recovery: str) -> None:
        self.coordinator.close()
        with self.storage.open_session(
            self.storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as session:
            session.restore_transaction(
                session.inspect_transaction(DevicePath(recovery))
            )
        self.assert_original()

    def assert_original(self) -> None:
        for relative, data in self.original.items():
            assert (self.root / relative).read_bytes() == data, relative


def build_device(
    tmp_path: Path,
    *,
    shared_media: bool = False,
    photos: bool = False,
    media_payload: bytes | None = None,
    artwork_size_multiplier: int = 1,
    model: str = "MB565",
) -> Device:
    root = tmp_path / "ipod"
    source, thumbnail = with_shared_artwork(
        target=replace(
            TARGET,
            cover_formats=(
                CoverFormat(1055, 128, 128, 256, CoverPixelFormat.RGB565_LE)
                if model == "MB565"
                else CoverFormat(1060, 320, 320, 640, CoverPixelFormat.RGB565_LE),
            ),
        )
    )
    payload = (
        media_payload
        if media_payload is not None
        else b"simulated source media for deletion tests"
    )
    tracks = tuple(
        replace(
            track,
            size_bytes=len(payload),
            metadata=replace(
                track.metadata,
                file_format="AAC audio file",
                sample_rate_hz=44100,
                location=f"iPod_Control/Music/F00/{1 if shared_media else track.track_id}.m4a",
            ),
        )
        for track in source.snapshot.tracks
    )
    result = source.prepare(
        source.analyze(source.begin_draft(replace(source.snapshot, tracks=tracks))),
        WriteResources(media=tuple(prepared_media(track, payload) for track in tracks)),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    artwork = parse_ArtworkDB(result.prepared.artwork)
    for selection in artwork.find_chunks(MhifHeader):
        chunk = selection.chunk
        artwork = artwork.replace_chunk(
            selection,
            replace(
                chunk,
                header=replace(
                    chunk.header,
                    image_size=chunk.header.image_size * artwork_size_multiplier,
                ),
            ),
        )
    assert isinstance(thumbnail.data, bytes)
    files = {
        "iPod_Control/iTunes/iTunesDB": result.prepared.itunes,
        "iPod_Control/Artwork/ArtworkDB": write_ArtworkDB(artwork),
        thumbnail.relative_path: thumbnail.data,
        **{track.metadata.location: payload for track in tracks},
    }
    if photos:
        fixture = (
            Path(__file__).parents[3]
            / "fixtures"
            / "PhotosDB"
            / "original-photo-library.b64"
        )
        files["Photos/Photo Database"] = base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
        files["Photos/Full Resolution/iOpenPod/Sunrise.jpg"] = (
            b"retained full-resolution photo"
        )
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    metadata = root / "iPod_Control/Device"
    metadata.mkdir()
    (metadata / "SysInfo").write_text(
        f"ModelNumStr: {model}\nFirewireGuid: 000A270012345678\n", encoding="utf-8"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261 if model == "MB565" else None,
            transport_serial="000A270012345678",
        ),
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    coordinator = DeviceCoordinator(storage)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    return Device(root, storage, platform, coordinator, files)


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    fixture = build_device(tmp_path)
    try:
        yield fixture
    finally:
        fixture.coordinator.close()


def cover_snapshot(device: Device) -> LibrarySnapshot:
    first, second = device.active.library.tracks
    return replace(
        device.active.library,
        tracks=(replace(first, artwork_id=BLUE.artwork_id), second),
    )


def without_first(device: Device) -> LibrarySnapshot:
    first, second = device.active.library.tracks
    return replace(
        device.active.library,
        tracks=(second,),
        playlists=tuple(
            replace(
                playlist,
                entries=tuple(
                    e for e in playlist.entries if e.track_id != first.track_id
                ),
            )
            for playlist in device.active.library.playlists
        ),
    )


def test_ordinary_library_save_cleans_recovery_and_keeps_saved_contents(
    device: Device,
) -> None:
    desired = cover_snapshot(device)
    review = device.prepare(desired, cover=True)
    assert review.result.prepared is not None, review.result.issues

    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )

    assert saved.active is not None, saved.issues
    assert not saved.recovery_path
    assert not tuple((device.root / ".iopenpod-recovery").glob("*/transaction.json"))
    source = IPodLibrary(
        (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
    ).with_artwork((device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes())
    assert source.snapshot == saved.active.library
    assert source.snapshot.tracks[0].artwork_id == (
        review.result.prepared.snapshot.tracks[0].artwork_id
    )
    for file in review.result.prepared.artwork_files:
        assert isinstance(file.data, bytes)
        assert (device.root / file.relative_path).read_bytes() == file.data

    reselected = device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )
    assert reselected.library == saved.active.library
    assert not device.coordinator.sync_cleanup_path


def test_ordinary_library_save_cleanup_failure_keeps_success_and_retries_on_selection(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    desired = cover_snapshot(device)
    review = device.prepare(desired, cover=True)
    assert review.result.prepared is not None, review.result.issues

    def fail_cleanup(_session: FilesystemSession, _journal_path: DevicePath) -> None:
        raise OSError("Recovery directory is temporarily unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(FilesystemSession, "finalize_committed_transaction", fail_cleanup)
        saved = device.coordinator.save_library(
            review, device.active, lambda _: None, Event()
        )

    assert saved.active is not None, saved.issues
    assert saved.active.library == review.result.prepared.snapshot
    assert {issue.code for issue in saved.issues} == {"save.cleanup_pending"}
    assert saved.recovery_path
    assert (device.root / saved.recovery_path).exists()

    reselected = device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )
    assert reselected.library == saved.active.library
    assert not device.coordinator.sync_cleanup_path
    assert not (device.root / saved.recovery_path).exists()


def test_cover_replacement_publishes_all_formats_then_restores(device: Device) -> None:
    before = device.active.library
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues
    assert len(review.result.prepared.artwork_files) == 4
    assert [f.path for f in review.file_changes][-2:] == [
        "iPod_Control/Artwork/ArtworkDB",
        "iPod_Control/iTunes/iTunesDB",
    ]
    assert all(f.action == "write" for f in review.file_changes)
    device.assert_original()
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert saved.active.library.tracks[1] == before.tracks[1]
    for file in review.result.prepared.artwork_files:
        data = file.data
        assert isinstance(data, bytes)
        assert (device.root / file.relative_path).read_bytes() == data
        assert data.startswith(device.original.get(file.relative_path, b""))
    source = IPodLibrary(
        (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
    ).with_artwork((device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes())
    assert source.snapshot == saved.active.library
    device.restore(saved.recovery_path)
    for file in review.result.prepared.artwork_files:
        if file.relative_path not in device.original:
            assert not (device.root / file.relative_path).exists()


@pytest.mark.parametrize("budget", [10, 32768])
def test_cover_preparation_spills_past_memory_budget_and_restores(
    device: Device, monkeypatch: pytest.MonkeyPatch, budget: int
) -> None:
    monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", budget)
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues
    staged = {
        file.relative_path: file.data
        for file in review.result.prepared.artwork_files
        if isinstance(file.data, StagedContent)
    }
    assert staged
    assert not any(
        issue.code == "resources.artwork_disk_staging" for issue in review.result.issues
    )
    expected = {path: data.read_at(0, len(data)) for path, data in staged.items()}
    device.assert_original()
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    for path, data in staged.items():
        assert (device.root / path).read_bytes() == expected[path]
        assert expected[path].startswith(device.original.get(path, b""))
        assert not Path(data.path).exists()
    report = json.loads(inspect_library_write(None, review, state="saved"))
    descriptions = {
        file["relative_path"]: file["data"]
        for file in report["prepared"]["changed_artwork_files"]["items"]
    }
    for path, data in staged.items():
        assert descriptions[path] == {"size": len(data), "sha256": data.sha256}
    device.restore(saved.recovery_path)


def test_cover_disk_output_is_cleaned_when_review_is_replaced(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 0)
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None
    paths = [
        Path(file.data.path)
        for file in review.result.prepared.artwork_files
        if isinstance(file.data, StagedContent)
    ]
    assert paths and all(path.exists() for path in paths)
    device.prepare(device.active.library)
    assert all(not path.exists() for path in paths)
    device.assert_original()


def test_artwork_host_storage_failure_is_actionable_and_leaves_device_unchanged(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_buffer: ContentFileBuffer, _data: bytes) -> None:
        raise OSError("No space left on Host disk")

    monkeypatch.setattr(ContentFileBuffer, "append", fail)
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is None
    issue = next(
        issue
        for issue in review.result.issues
        if issue.code == "resources.host_staging_failed"
    )
    assert "free space" in issue.message
    assert "No space left" in issue.detail
    device.assert_original()


def test_changed_staged_artwork_cannot_be_published(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 0)
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None
    data = review.result.prepared.artwork_files[0].data
    assert isinstance(data, StagedContent)
    Path(data.path).write_bytes(b"changed")
    saved = device.save(review)
    assert saved.active is None
    device.assert_original()
    assert not Path(data.path).exists()


def test_clear_artwork_leaves_shared_cover_and_all_thumbnail_bytes(
    device: Device,
) -> None:
    first, second = device.active.library.tracks
    desired = replace(
        device.active.library, tracks=(replace(first, artwork_id=0), second)
    )
    review = device.prepare(desired)
    assert review.result.prepared is not None, review.result.issues
    assert not review.result.prepared.artwork_files
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert saved.active.library.tracks[0].artwork_id == 0
    assert saved.active.library.tracks[1] == second
    for name, data in device.original.items():
        if name.endswith(".ithmb"):
            assert (device.root / name).read_bytes() == data
    device.restore(saved.recovery_path)


def test_track_removal_moves_media_after_database_publication(device: Device) -> None:
    first = device.active.library.tracks[0]
    review = device.prepare(without_first(device), delete=True)
    assert review.result.prepared is not None, review.result.issues
    deleted_media = device.root / first.metadata.location
    assert review.file_changes[-1].action == "remove"
    assert review.file_changes[-1].path == first.metadata.location
    removed = False

    def observe(event: WriteProgress) -> None:
        nonlocal removed
        if not deleted_media.exists():
            source = IPodLibrary(
                (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
            )
            assert first.track_id not in {t.track_id for t in source.snapshot.tracks}
            removed = True

    saved = device.save(review, observe)
    assert saved.active is not None, saved.issues
    assert removed
    assert saved.active.library.tracks[0].track_id != first.track_id
    device.restore(saved.recovery_path)


def test_ordinary_track_deletion_never_hashes_or_retains_removed_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    first, second = device.active.library.tracks
    removed_path = DevicePath(first.metadata.location)
    original_fingerprint = FilesystemSession.fingerprint

    def fingerprint(self: FilesystemSession, path: DevicePath) -> FileFingerprint:
        if path == removed_path:
            raise AssertionError("Removed media must not be read for a full hash")
        return original_fingerprint(self, path)

    monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            without_first(device),
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=True,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    assert review.file_changes[-1].action == "delete"
    assert review.file_changes[-1].sha256 is None
    assert (device.root / first.metadata.location).exists()

    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is not None, saved.issues
    assert saved.recovery_path == ""
    assert not (device.root / first.metadata.location).exists()
    assert (device.root / second.metadata.location).exists()
    assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))


def test_changed_track_media_blocks_unrecoverable_deletion_before_saving(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    first = device.active.library.tracks[0]
    database = device.root / "iPod_Control/iTunes/iTunesDB"
    before = database.read_bytes()
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            without_first(device),
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=True,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    media = device.root / first.metadata.location
    media.write_bytes(media.read_bytes() + b"changed")

    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is None
    assert media.exists()
    assert database.read_bytes() == before


def test_permanent_deletion_preserves_media_shared_with_surviving_track(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, shared_media=True)
    first, second = device.active.library.tracks
    assert first.metadata.location == second.metadata.location
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            without_first(device),
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=True,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    assert not any(change.action == "delete" for change in review.file_changes)

    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is not None, saved.issues
    assert (device.root / second.metadata.location).exists()


def test_failed_post_commit_media_deletion_reports_saved_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    first = device.active.library.tracks[0]
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            without_first(device),
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=True,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues

    def fail_delete(
        self: FilesystemSession, path: DevicePath, *, expected: object
    ) -> None:
        raise StorageOperationError("injected delete failure")

    monkeypatch.setattr(FilesystemSession, "delete_unrecoverably", fail_delete)
    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is not None
    assert any(i.code == "save.media_deletion_incomplete" for i in saved.issues)
    assert (device.root / first.metadata.location).exists()
    assert first.track_id not in {t.track_id for t in saved.active.library.tracks}


def test_recovery_cleanup_failure_skips_permanent_media_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    first = device.active.library.tracks[0]
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            without_first(device),
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=True,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues

    def fail_cleanup(*_args: object) -> None:
        raise StorageOperationError("injected cleanup failure")

    monkeypatch.setattr(
        device_coordinator, "_finalize_committed_transaction", fail_cleanup
    )
    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is not None
    assert saved.recovery_path
    assert any(i.code == "save.media_deletion_skipped" for i in saved.issues)
    assert (device.root / first.metadata.location).exists()


def test_photo_removal_moves_full_resolution_file_after_photosdb_publication(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, photos=True)
    try:
        photos = device.active.library.photos
        assert photos is not None
        desired_photos = replace(
            photos,
            photos=(),
            albums=tuple(replace(album, photo_ids=()) for album in photos.albums),
        )
        review = device.prepare(
            replace(device.active.library, photos=desired_photos),
            delete=True,
        )
        assert review.result.prepared is not None, review.result.issues
        assert tuple(
            (change.path, change.action) for change in review.file_changes
        ) == (
            ("Photos/Photo Database", "write"),
            (
                "Photos/Full Resolution/iOpenPod/Sunrise.jpg",
                "remove",
            ),
        )
        full_resolution = device.root / "Photos/Full Resolution/iOpenPod/Sunrise.jpg"
        removed = False

        def observe(_event: WriteProgress) -> None:
            nonlocal removed
            if not full_resolution.exists():
                source = IPodLibrary(
                    (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
                ).with_photos((device.root / "Photos/Photo Database").read_bytes())
                assert source.snapshot.photos is not None
                assert source.snapshot.photos.photos == ()
                removed = True

        saved = device.save(review, observe)
        assert saved.active is not None, saved.issues
        assert removed
        assert saved.active.library.photos == desired_photos
        assert not full_resolution.exists()
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


def test_removing_one_shared_track_keeps_media(tmp_path: Path) -> None:
    device = build_device(tmp_path, shared_media=True)
    try:
        path = device.root / device.active.library.tracks[0].metadata.location
        review = device.prepare(without_first(device), delete=True)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert path.read_bytes() == next(
            data for name, data in device.original.items() if name.endswith(".m4a")
        )
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("phase", ["after_review", "save.storage.prepared"])
def test_new_sidecar_blocks_removal_before_publication(
    device: Device, phase: str
) -> None:
    review = device.prepare(without_first(device), delete=True)
    assert review.result.prepared is not None, review.result.issues
    sidecar = device.root / "iPod_Control/iTunes/OTGPlaylistInfo-new"
    if phase == "after_review":
        sidecar.write_bytes(b"pending positional data")

    def observe(event: WriteProgress) -> None:
        if event.phase == phase:
            sidecar.write_bytes(b"pending positional data")

    saved = device.save(review, observe)
    assert saved.active is None
    assert saved.issues[0].code in ("save.source_unavailable", "save.failed")
    device.assert_original()


def test_pending_play_counts_are_remapped_with_the_library_and_restored(
    device: Device,
) -> None:
    from tests.iPodDB.sidecars.test_playback_sidecars import play_counts

    tracks = device.active.library.tracks
    rows = tuple(bytes([i + 1]) * 28 for i in range(len(tracks)))
    sidecar = device.root / "iPod_Control/iTunes/Play Counts"
    original = play_counts(rows)
    sidecar.write_bytes(original)
    review = device.prepare(without_first(device), delete=True)
    assert review.result.prepared is not None, review.result.issues
    assert sidecar.read_bytes() == original
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert sidecar.read_bytes()[96:] == b"".join(rows[1:])
    device.restore(saved.recovery_path)
    assert sidecar.read_bytes() == original


@pytest.mark.parametrize("phase", ["after_review", "save.storage.prepared"])
def test_changed_captured_play_counts_stop_publication(
    device: Device, phase: str
) -> None:
    from tests.iPodDB.sidecars.test_playback_sidecars import play_counts

    sidecar = device.root / "iPod_Control/iTunes/Play Counts"
    original = play_counts(tuple(b"\x01" * 28 for _ in device.active.library.tracks))
    sidecar.write_bytes(original)
    review = device.prepare(without_first(device), delete=True)
    assert review.result.prepared is not None, review.result.issues
    changed = original[:-1] + b"\x02"
    if phase == "after_review":
        sidecar.write_bytes(changed)

    def progress(event: WriteProgress) -> None:
        if event.phase == phase:
            sidecar.write_bytes(changed)

    saved = device.save(review, progress)
    assert saved.active is None
    assert sidecar.read_bytes() == changed
    device.assert_original()


def test_changed_thumbnail_blocks_whole_save(device: Device) -> None:
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues
    path = device.root / next(
        name for name in device.original if name.endswith(".ithmb")
    )
    changed = b"external artwork edit"
    path.write_bytes(changed)
    saved = device.save(review)
    assert saved.active is None
    assert path.read_bytes() == changed
    assert (
        device.root / "iPod_Control/iTunes/iTunesDB"
    ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]


def test_appledouble_artwork_churn_is_not_a_library_dependency(device: Device) -> None:
    name = next(name for name in device.original if name.endswith(".ithmb"))
    actual = device.root / name
    companion = actual.with_name("._" + actual.name)
    companion.write_bytes(b"macOS metadata before publication")
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues

    def progress(event: WriteProgress) -> None:
        if event.phase == "save.storage.publishing":
            companion.write_bytes(b"macOS metadata replaced during publication")

    saved = device.save(review, progress)
    assert saved.active is not None, saved.issues
    assert companion.read_bytes() == b"macOS metadata replaced during publication"
    device.restore(saved.recovery_path)


def test_copied_review_has_no_save_authority(device: Device) -> None:
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues
    saved = device.save(replace(review))
    assert saved.active is None and saved.issues[0].code == "save.stale"
    device.assert_original()


def test_sync_can_verify_unchanged_library_without_a_storage_transaction(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = device.active
    ordinary = device.prepare(active.library)
    assert ordinary.result.prepared is None
    fingerprint = FilesystemSession.fingerprint

    def check_without_media(
        session: FilesystemSession, path: DevicePath
    ) -> FileFingerprint:
        assert not path.is_relative_to(DevicePath("iPod_Control/Music"))
        return fingerprint(session, path)

    monkeypatch.setattr(FilesystemSession, "fingerprint", check_without_media)
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(active.library, active, 1, 1),
        lambda _: None,
        Event(),
        allow_unchanged=True,
    )
    assert review.result.prepared is not None, review.result.issues
    assert review.file_changes == ()

    def forbid_transaction(*args: object, **kwargs: object) -> None:
        raise AssertionError("An unchanged association review must not rewrite files")

    monkeypatch.setattr(FilesystemSession, "execute_transaction", forbid_transaction)
    saved = device.save(review)
    assert saved.active is active, saved.issues
    assert not saved.issues and not saved.recovery_path
    device.assert_original()
    assert device.save(review).issues[0].code == "save.stale"


@pytest.mark.parametrize("changed_database", [False, True])
def test_unchanged_sync_review_rechecks_source_and_captured_dependencies(
    device: Device, changed_database: bool
) -> None:
    active = device.active
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(active.library, active, 1, 1),
        lambda _: None,
        Event(),
        allow_unchanged=True,
    )
    assert review.result.prepared is not None, review.result.issues
    path = device.root / (
        "iPod_Control/iTunes/iTunesDB"
        if changed_database
        else "iPod_Control/Device/Preferences"
    )
    path.write_bytes(b"external change after review")
    saved = device.save(review)
    assert saved.active is None
    assert saved.issues[0].code == "save.source_unavailable"
    assert path.read_bytes() == b"external change after review"
    assert not saved.recovery_path


def test_interrupted_artwork_save_retains_draft_and_recovers_after_reconnect(
    device: Device,
) -> None:
    original_active = device.active
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues

    def unplug(event: WriteProgress) -> None:
        if event.phase == "save.storage.publishing":
            device.platform.disconnect(device.root)

    saved = device.save(review, unplug)
    assert saved.active is None and saved.issues[0].code == "save.recovery_required"
    assert saved.recovery_path
    assert device.active is original_active
    device.platform.reconnect(device.root)
    assert device.save(review).issues[0].code == "save.stale"
    device.restore(saved.recovery_path)


def test_missing_removed_media_is_not_recreated_or_required(device: Device) -> None:
    path = device.root / device.active.library.tracks[0].metadata.location
    path.unlink()
    review = device.prepare(without_first(device), delete=True)
    assert review.result.prepared is not None, review.result.issues
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert not path.exists()


def test_deletions_require_explicit_draft_intent(device: Device) -> None:
    review = device.prepare(without_first(device))
    assert review.result.prepared is None
    assert any(i.code == "draft.deletion_not_enabled" for i in review.result.issues)
    device.assert_original()


def test_older_preparation_cannot_replace_newer_save_authority(device: Device) -> None:
    newest: list[LibraryReview] = []
    active = device.active

    def interleave(event: WriteProgress) -> None:
        if event.phase == "source.recheck" and not newest:
            snapshot = replace(
                active.library,
                tracks=tuple(replace(t, title="Newest") for t in active.library.tracks),
            )
            newest.append(device.prepare(snapshot))

    older = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            cover_snapshot(device), active, 1, 1, artwork=(BLUE,)
        ),
        interleave,
        Event(),
    )
    assert older.result.prepared is not None
    assert len(newest) == 1 and newest[0].result.prepared is not None
    assert device.save(older).issues[0].code == "save.stale"
    saved = device.save(newest[0])
    assert saved.active is not None, saved.issues
    assert all(t.title == "Newest" for t in saved.active.library.tracks)


def test_cancellation_during_staging_is_reported_without_publication(
    device: Device,
) -> None:
    review = device.prepare(cover_snapshot(device), cover=True)
    assert review.result.prepared is not None, review.result.issues
    cancelled = Event()

    def cancel(event: WriteProgress) -> None:
        if event.phase == "save.storage.staging":
            cancelled.set()

    saved = device.coordinator.save_library(review, device.active, cancel, cancelled)
    assert saved.active is None and saved.issues[0].code == "save.cancelled"
    device.assert_original()
