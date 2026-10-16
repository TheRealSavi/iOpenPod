"""Reviewed Sync can replace stale firmware projections without editing the CDB."""

from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _database_with_track,  # pyright: ignore[reportPrivateUsage]
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_execution import (
    _photo_host,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    _draft,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.sync_plan import SyncPlan, SyncPlanAction, prepare_sync_plan
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.library import IPodLibrary, LibrarySnapshot
from iPodDB.library.writing import WriteChecksum, WriteResources, WriteTarget
from iPodDB.SQLiteDB.checksum import verify_locations_cbk
from storage import Storage
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from pathlib import Path


_NAMES = (
    "Library.itdb",
    "Locations.itdb",
    "Dynamic.itdb",
    "Extras.itdb",
    "Genius.itdb",
    "Locations.itdb.cbk",
)
_GUID = bytes.fromhex("000A270012345678")


def _nano6(tmp_path: Path, *, signing_identity: bool = True) -> Path:
    root = _ipod_volume(
        tmp_path / "nano6", model_number="MC525", database_name="iTunesCDB"
    )
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    logical = bytearray(_database_with_track(track_header_size=0x270))
    media_type_offset = logical.index(b"mhit") + 0xD0
    logical[media_type_offset : media_type_offset + 4] = (1).to_bytes(4, "little")
    cdb.write_bytes(compress_iTunesCDB(bytes(logical)))
    if signing_identity:
        (root / "iPod_Control/Device/SysInfo").write_text(
            f"ModelNumStr: MC525\nFirewireGuid: {_GUID.hex().upper()}\n",
            encoding="utf-8",
        )
    directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
    directory.mkdir()
    for name in _NAMES:
        (directory / name).write_bytes(b"stale firmware projection")
    return root


def test_unchanged_sync_replaces_all_sqlite_without_rewriting_cdb(
    tmp_path: Path,
) -> None:
    root = _nano6(tmp_path)
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    retained = cdb.read_bytes()
    directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        assert all(
            (directory / name).read_bytes() == b"stale firmware projection"
            for name in _NAMES
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, regenerate_sqlite=True
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert review.result.prepared is not None, review.result.issues
        artifacts = review.result.prepared.sqlite
        assert artifacts is not None
        assert review.result.prepared.itunes == retained
        assert {
            change.path.rsplit("/", 1)[-1] for change in review.file_changes
        } == set(_NAMES)
        assert all(
            (directory / name).read_bytes() == b"stale firmware projection"
            for name in _NAMES
        )

        saved = coordinator.save_library(review, active, lambda _: None, Event())

        assert saved.active is not None, saved.issues
        assert cdb.read_bytes() == retained
        assert all(
            (directory / name).read_bytes() == data
            for name, data in artifacts.artifacts()
        )
        assert verify_locations_cbk(artifacts, WriteChecksum.HASHAB, _GUID)
    finally:
        coordinator.close()


@pytest.mark.parametrize("name", _NAMES)
def test_unchanged_sync_rechecks_every_sqlite_file(tmp_path: Path, name: str) -> None:
    root = _nano6(tmp_path)
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    retained = cdb.read_bytes()
    directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, regenerate_sqlite=True
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.sqlite is not None
        (directory / name).write_bytes(b"external change")

        saved = coordinator.save_library(review, active, lambda _: None, Event())

        assert saved.active is None
        assert cdb.read_bytes() == retained
        assert (directory / name).read_bytes() == b"external change"
        assert all(
            (directory / other).read_bytes() == b"stale firmware projection"
            for other in _NAMES
            if other != name
        )
    finally:
        coordinator.close()


def test_unchanged_sync_requires_signing_identity(tmp_path: Path) -> None:
    root = _nano6(tmp_path, signing_identity=False)
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, regenerate_sqlite=True
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert review.result.prepared is None
        assert any(
            issue.code == "target.missing_guid" for issue in review.result.issues
        )
        directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
        assert all(
            (directory / name).read_bytes() == b"stale firmware projection"
            for name in _NAMES
        )
    finally:
        coordinator.close()


def test_ordinary_noop_preparation_keeps_exact_retained_bytes() -> None:
    retained = compress_iTunesCDB(_database_with_track())
    source = IPodLibrary.parse(retained)
    target = WriteTarget(
        compressed_database=True,
        sqlite_database=True,
        sqlite_checksum=WriteChecksum.HASHAB,
    )
    result = source.prepare(source.analyze(source.begin_draft(), target))

    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == retained
    assert result.prepared.sqlite is None
    assert source.serialize().itunes == retained


def test_sync_executor_refreshes_sqlite_with_no_media_or_smart_playlists(
    tmp_path: Path,
) -> None:
    root = _nano6(tmp_path)
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    retained = cdb.read_bytes()
    directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        assert not active.library.playlists
        request = SyncExecutionRequest(
            SyncPlan(()),
            HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
            active,
            1,
            1,
            reconcile_playlists=False,
        )
        draft, completed, changed = _draft(request, [], [])
        assert not completed
        assert draft.snapshot == active.library
        assert not changed

        result = SyncExecutor(coordinator).execute(request, lambda _: None, Event())

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert cdb.read_bytes() == retained
        assert all(
            (directory / name).read_bytes() != b"stale firmware projection"
            for name in _NAMES
        )
    finally:
        coordinator.close()


def test_photo_only_sync_also_refreshes_sqlite(tmp_path: Path) -> None:
    root = _nano6(tmp_path)
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    retained = cdb.read_bytes()
    directory = root / "iPod_Control/iTunes/iTunes Library.itlp"
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        host = _photo_host(tmp_path)
        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        comparison = prepare_sync_plan(host, ipod, active.library)
        plan = SyncPlan(
            tuple(
                item for item in comparison.items if item.action is SyncPlanAction.ADD
            )
        )
        assert plan.change_count == 1
        request = SyncExecutionRequest(
            plan, host, ipod, active, 1, 1, reconcile_playlists=False
        )

        result = SyncExecutor(coordinator).execute(request, lambda _: None, Event())

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert result.active.library.photos is not None
        assert len(result.active.library.photos.photos) == 1
        assert cdb.read_bytes() == retained
        assert all(
            (directory / name).read_bytes() != b"stale firmware projection"
            for name in _NAMES
        )
    finally:
        coordinator.close()


def test_explicit_sqlite_refresh_requires_playback_sidecar_evidence() -> None:
    retained = compress_iTunesCDB(_database_with_track(track_header_size=0x270))
    source = IPodLibrary.parse(retained)
    target = WriteTarget(
        compressed_database=True,
        sqlite_database=True,
        sqlite_checksum=WriteChecksum.HASHAB,
        firewire_guid=_GUID,
    )
    plan = source.analyze(source.begin_draft(regenerate_sqlite=True), target)

    blocked = source.prepare(plan, WriteResources(pending_playback_sidecars=True))

    assert blocked.prepared is None
    assert any(issue.code == "resources.playback_sidecars" for issue in blocked.issues)
    prepared = source.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert prepared.prepared is not None, prepared.issues
    assert prepared.prepared.sqlite is not None
    assert prepared.prepared.itunes == retained
