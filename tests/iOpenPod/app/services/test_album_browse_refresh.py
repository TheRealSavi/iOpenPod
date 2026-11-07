"""Refresh Library repairs Classic browse indexes through verified Storage writes."""

from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_album_browse_repair import album_orders, album_source

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
)
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
)
from iOpenPod.app.sync_plan import SyncPlan
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.writer.signature import verify_hash58
from iPodDB.library import LibrarySnapshot
from storage import Storage
from storage.testing import VirtualStoragePlatform

GUID = bytes.fromhex("000A270012345678")


def classic(
    tmp_path: Path,
    *,
    jump_tables: bool = True,
) -> tuple[Path, DeviceCoordinator, VirtualStoragePlatform]:
    root = _ipod_volume(tmp_path / "classic", model_number="MB145")
    (root / "iPod_Control/iTunes/iTunesDB").write_bytes(
        album_source(jump_tables=jump_tables).serialize().itunes
    )
    (root / "iPod_Control/Device/SysInfo").write_text(
        f"ModelNumStr: MB145\nFirewireGuid: {GUID.hex().upper()}\n", encoding="utf-8"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Classic")
    return root, DeviceCoordinator(Storage(platform)), platform


@pytest.mark.parametrize("jump_tables", [False, True])
def test_no_change_sync_repairs_classic_album_indexes_and_signs_output(
    tmp_path: Path,
    jump_tables: bool,
) -> None:
    root, coordinator, _ = classic(tmp_path, jump_tables=jump_tables)
    database = root / "iPod_Control/iTunes/iTunesDB"
    original = database.read_bytes()
    media = root / "iPod_Control/Music/F00/track.m4a"
    payload = media.read_bytes()
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        assert database.read_bytes() == original
        request = SyncExecutionRequest(
            SyncPlan(()),
            HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
            active,
            1,
            1,
            reconcile_playlists=False,
        )
        result = SyncExecutor(coordinator).execute(request, lambda _: None, Event())
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert album_orders(database.read_bytes()) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
        assert verify_hash58(database.read_bytes(), GUID)
        assert sum(
            s.chunk.header.mhod_type == 53
            for s in parse_iTunesDB(database.read_bytes()).find_chunks(MhodHeader)
        ) == (2 if jump_tables else 0)
        assert result.active.library == active.library
        assert media.read_bytes() == payload
    finally:
        coordinator.close()


@pytest.mark.parametrize("interruption", ["changed", "disconnected", "cancelled"])
def test_rebuild_publication_rejects_changed_source_or_interruption(
    tmp_path: Path, interruption: str
) -> None:
    root, coordinator, platform = classic(tmp_path)
    database = root / "iPod_Control/iTunes/iTunesDB"
    original = database.read_bytes()
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, rebuild_album_indexes=True
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert [item.path for item in review.file_changes] == [
            "iPod_Control/iTunes/iTunesDB"
        ]
        assert database.read_bytes() == original
        cancelled = Event()
        if interruption == "changed":
            database.write_bytes(original + b"external change")
        elif interruption == "disconnected":
            platform.disconnect(root)
            coordinator.discover_devices()
        else:
            cancelled.set()
        if interruption == "cancelled":
            with pytest.raises(PreparationCancelledError):
                coordinator.save_library(review, active, lambda _: None, cancelled)
        else:
            result = coordinator.save_library(review, active, lambda _: None, cancelled)
            assert result.active is None
        assert database.read_bytes() == (
            original + b"external change" if interruption == "changed" else original
        )
    finally:
        coordinator.close()
