"""Photo Sync packs verified ranges into shared, recoverable thumbnail shards."""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_write import PreparationCancelledError, WriteProgress
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services import photo_shard_resources
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.sync_execution import SyncExecutionStatus
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    PreparedPhoto,
    RetainedArtworkFile,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader
from storage import (
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    HostPath,
    StorageOperationError,
)
from storage.content_workspace import ContentWorkspace, StagedContent
from storage.host_input import LocalHostFile


def photo_host(root: Path, colors: tuple[str, ...]) -> HostMediaLibrary:
    root.mkdir(parents=True, exist_ok=True)
    photos: list[Photo] = []
    sources: list[HostMediaSource] = []
    for identity, color in enumerate(colors, 1):
        path = root / f"{color}.png"
        Image.new("RGB", (60, 120), color).save(path)
        data = path.read_bytes()
        observed = LocalHostFile.observe(HostPath(path))
        photos.append(
            Photo(
                identity,
                source_size_bytes=len(data),
                representations=(
                    PhotoRepresentation(
                        PhotoRepresentationKind.FULL_RESOLUTION,
                        0,
                        str(path),
                        0,
                        len(data),
                        60,
                        120,
                    ),
                ),
            )
        )
        sources.append(
            HostMediaSource(
                observed.path,
                HostMediaFileKind.PHOTO,
                observed.size_bytes,
                observed.modified_ns,
                content_sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return HostMediaLibrary(
        LibrarySnapshot(photos=PhotoLibrary(photos=tuple(photos))),
        tuple(sources),
        (),
        HostMediaCacheStats(),
    )


@pytest.mark.parametrize("budget", [0, 2 * 1024 * 1024 * 1024])
def test_sync_photos_share_shards_and_append_on_a_later_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int
) -> None:
    from iOpenPod.app import sync_execution

    monkeypatch.setattr(sync_execution, "_PHOTO_MEMORY_BUDGET", budget)
    device = build_device(tmp_path)
    try:
        executor = _Executor(device.coordinator, transcoder=_AvailableTools())
        first = executor.execute(
            _request(device, photo_host(tmp_path / "first", ("red", "blue"))),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None and first.active.library.photos is not None
        photos = first.active.library.photos.photos
        first_thumbs = {
            rep.format_id: rep
            for rep in photos[0].representations
            if rep.kind is PhotoRepresentationKind.THUMBNAIL
        }
        before = {
            rep.relative_path: (device.root / rep.relative_path).read_bytes()
            for rep in first_thumbs.values()
        }
        for rep in photos[1].representations:
            if rep.kind is PhotoRepresentationKind.THUMBNAIL:
                previous = first_thumbs[rep.format_id]
                assert rep.relative_path == previous.relative_path
                assert rep.offset == previous.size_bytes
        second = executor.execute(
            _request(device, photo_host(tmp_path / "second", ("green",))),
            lambda _: None,
            Event(),
        )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None and second.active.library.photos is not None
        assert second.active.library.photos.photos[:2] == photos
        for rep in second.active.library.photos.photos[2].representations:
            if rep.kind is PhotoRepresentationKind.THUMBNAIL:
                assert rep.relative_path == first_thumbs[rep.format_id].relative_path
                assert rep.offset == len(before[rep.relative_path])
                assert (
                    (device.root / rep.relative_path)
                    .read_bytes()
                    .startswith(before[rep.relative_path])
                )
    finally:
        device.coordinator.close()


def test_sync_rolls_over_full_shards_independently_by_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    original_pack = DeviceCoordinator.pack_photo_shards
    limit = 2 * 691_200

    def pack_with_capacity(
        coordinator: DeviceCoordinator,
        expected: ActiveIPod,
        assets: tuple[PreparedPhoto, ...],
        workspace: ContentWorkspace,
        checkpoint: Callable[[], None],
        *,
        max_file_bytes: int | None = None,
    ) -> tuple[PreparedPhoto, ...]:
        return original_pack(
            coordinator, expected, assets, workspace, checkpoint, max_file_bytes=limit
        )

    monkeypatch.setattr(DeviceCoordinator, "pack_photo_shards", pack_with_capacity)
    try:
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, photo_host(tmp_path / "host", ("red", "blue", "green"))),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.active.library.photos is not None
        rows = [
            {rep.format_id: rep for rep in photo.representations}
            for photo in result.active.library.photos.photos
        ]
        assert rows[0][1067].relative_path == rows[1][1067].relative_path
        assert rows[1][1067].offset == 691_200
        assert rows[2][1067].relative_path.endswith("F1067_2.ithmb")
        assert rows[2][1067].offset == 0
        assert len({row[1066].relative_path for row in rows}) == 1
        assert all(
            path.stat().st_size <= limit
            for path in (device.root / "Photos/Thumbs").iterdir()
        )
        old_shard = device.root / rows[0][1067].relative_path
        original = old_shard.read_bytes()
        library = result.active.library.photos
        retained = library.photos[1:]
        desired = replace(
            library,
            photos=retained,
            albums=tuple(
                replace(album, photo_ids=tuple(photo.photo_id for photo in retained))
                for album in library.albums
            ),
        )
        review = device.prepare(
            replace(device.active.library, photos=desired), delete=True
        )
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert old_shard.read_bytes() == original
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_sync_without_photo_changes_publishes_pending_photo_count_repair(
    tmp_path: Path, cancel: bool
) -> None:
    device = build_device(tmp_path, photos=True)
    try:
        path = device.root / "Photos/Photo Database"
        valid = path.read_bytes()
        images = parse_PhotosDB(valid).find_chunks(MhsdHeader)[0].chunk.children[0]
        offset = images.offset + 8
        damaged = valid[:offset] + bytes(4) + valid[offset + 4 :]
        device.coordinator.close()
        path.write_bytes(damaged)
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert device.active.photos_repairs_pending
        request = _request(device, photo_host(tmp_path / "host", ()))
        assert not request.plan.change_count
        cancelled = Event()
        if cancel:
            cancelled.set()
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, cancelled
        )
        if cancel:
            assert result.status is SyncExecutionStatus.CANCELLED
            assert device.active.photos_repairs_pending
            assert path.read_bytes() == damaged
        else:
            assert result.status is SyncExecutionStatus.SUCCESS, result.issues
            assert (
                result.active is not None and not result.active.photos_repairs_pending
            )
            assert path.read_bytes() == valid
            assert not result.completed
        assert (
            device.root / "iPod_Control/iTunes/iTunesDB"
        ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "damage", ["missing", "truncated", "unreadable", "cancel", "disconnect"]
)
def test_sync_skips_unavailable_shards_without_filling_old_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    device = build_device(tmp_path)
    try:
        executor = _Executor(device.coordinator, transcoder=_AvailableTools())
        first = executor.execute(
            _request(device, photo_host(tmp_path / "first", ("red", "blue"))),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None and first.active.library.photos is not None
        original_photos = first.active.library.photos
        shard = original_photos.photos[0].representations[1].relative_path
        old_path = device.root / shard
        data = old_path.read_bytes()
        database = (device.root / "Photos/Photo Database").read_bytes()
        if damage == "missing":
            old_path.unlink()
        elif damage == "truncated":
            old_path.write_bytes(data[:1])
        else:
            original_capture = ContentWorkspace.capture_device_snapshot

            def capture(
                workspace: ContentWorkspace,
                session: FilesystemSession,
                path: DevicePath,
            ) -> tuple[bytes | StagedContent, FileFingerprint]:
                if str(path) == shard:
                    if damage == "cancel":
                        raise PreparationCancelledError
                    if damage == "disconnect":
                        device.platform.disconnect(device.root)
                        session.stat(path)
                    raise StorageOperationError("Unreadable retained Photo shard")
                return original_capture(workspace, session, path)

            monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", capture)
        second = executor.execute(
            _request(device, photo_host(tmp_path / "second", ("green",))),
            lambda _: None,
            Event(),
        )
        if damage in ("cancel", "disconnect"):
            assert second.status is (
                SyncExecutionStatus.CANCELLED
                if damage == "cancel"
                else SyncExecutionStatus.FAILED
            ), second.issues
            assert (device.root / "Photos/Photo Database").read_bytes() == database
            assert old_path.read_bytes() == data
            return
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None and second.active.library.photos is not None
        assert second.active.library.photos.photos[:2] == original_photos.photos
        added = second.active.library.photos.photos[2]
        assert added.representations[1].relative_path == shard.replace(
            "_1.ithmb", "_2.ithmb"
        )
        assert added.representations[1].offset == 0
        if damage == "missing":
            assert not old_path.exists()
        else:
            assert old_path.read_bytes() == (
                data[:1] if damage == "truncated" else data
            )
    finally:
        device.coordinator.close()


def test_changed_prefix_after_capture_prevents_sync_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    try:
        executor = _Executor(device.coordinator, transcoder=_AvailableTools())
        first = executor.execute(
            _request(device, photo_host(tmp_path / "first", ("red",))),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None and first.active.library.photos is not None
        representation = first.active.library.photos.photos[0].representations[1]
        path = device.root / representation.relative_path
        old = path.read_bytes()
        database = (device.root / "Photos/Photo Database").read_bytes()
        original_pack = photo_shard_resources.capture_and_pack

        def capture_and_change(
            session: FilesystemSession,
            assets: tuple[PreparedPhoto, ...],
            retained: tuple[RetainedArtworkFile, ...],
            photos: PhotoLibrary | None,
            workspace: ContentWorkspace,
            checkpoint: Callable[[], None],
            *,
            max_file_bytes: int,
        ) -> tuple[PreparedPhoto, ...]:
            packed = original_pack(
                session,
                assets,
                retained,
                photos,
                workspace,
                checkpoint,
                max_file_bytes=max_file_bytes,
            )
            path.write_bytes(b"changed" + old[7:])
            return packed

        monkeypatch.setattr(
            photo_shard_resources, "capture_and_pack", capture_and_change
        )
        second = executor.execute(
            _request(device, photo_host(tmp_path / "second", ("blue",))),
            lambda _: None,
            Event(),
        )
        assert second.status is SyncExecutionStatus.FAILED, second.issues
        assert (device.root / "Photos/Photo Database").read_bytes() == database
        assert path.read_bytes() == b"changed" + old[7:]
    finally:
        device.coordinator.close()


def test_interrupted_photo_database_publication_restores_shared_shards(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        executor = _Executor(device.coordinator, transcoder=_AvailableTools())
        first = executor.execute(
            _request(device, photo_host(tmp_path / "first", ("red", "blue"))),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        before = {
            path.relative_to(device.root): path.read_bytes()
            for path in (device.root / "Photos").rglob("*")
            if path.is_file()
        }
        interrupted = False

        def interrupt(event: WriteProgress) -> None:
            nonlocal interrupted
            if (
                event.phase == "save.storage.publishing"
                and event.current_item == "Photos/Photo Database"
                and not interrupted
            ):
                interrupted = True
                assert (device.root / event.current_item).read_bytes() != before[
                    Path(event.current_item)
                ]
                assert any(
                    (device.root / path).read_bytes() != data
                    for path, data in before.items()
                    if path.suffix == ".ithmb"
                )
                raise OSError("Interrupted after publishing PhotosDB and shared shards")

        second = executor.execute(
            _request(device, photo_host(tmp_path / "second", ("green",))),
            interrupt,
            Event(),
        )
        assert interrupted
        assert second.status is SyncExecutionStatus.FAILED, second.issues
        assert {
            path.relative_to(device.root): path.read_bytes()
            for path in (device.root / "Photos").rglob("*")
            if path.is_file()
        } == before
        assert not second.recovery_path
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
    finally:
        device.coordinator.close()
