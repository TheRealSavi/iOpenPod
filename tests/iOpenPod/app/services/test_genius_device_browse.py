"""Device selection exposes native Genius collections without importing them."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _database_with_track,  # pyright: ignore[reportPrivateUsage]
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_sqlite_refresh import (
    _nano6,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.library.genius import GeniusCollectionKind
from iPodDB.sidecars import GeniusPlaylist, create_genius_playlist
from storage import (
    FilesystemSession,
    Storage,
    StorageTransaction,
    TransactionActivity,
    TransactionProgress,
    TransactionResult,
)
from storage.testing import VirtualStoragePlatform

_PID = 0x0102030405060708


def _device(tmp_path: Path, *, damaged: bool = False) -> tuple[DeviceCoordinator, Path]:
    root = _ipod_volume(
        tmp_path / "nano", model_number="MD479", database_name="iTunesCDB"
    )
    folder = root / "iPod_Control/iTunes"
    (folder / "iTunesCDB").write_bytes(
        compress_iTunesCDB(_database_with_track(track_header_size=624))
    )
    saved = create_genius_playlist(
        GeniusPlaylist(
            saved_index=1,
            name="Saved Genius",
            seed_track_persistent_id=_PID,
            database_timestamp=123,
            track_master_indexes=None,
            track_persistent_ids=(_PID, _PID),
            playlist_persistent_id=1234,
        )
    ).serialize()
    (folder / "GeniusPlaylist_1.plist").write_bytes(saved)
    companion = folder / "iTunes Library.itlp/Library.itdb"
    companion.parent.mkdir()
    if damaged:
        companion.write_bytes(b"broken optional database")
    else:
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript("""
                CREATE TABLE container(pid INTEGER PRIMARY KEY, name TEXT, distinguished_kind INTEGER, smart_is_genius INTEGER, name_order INTEGER);
                CREATE TABLE item_to_container(item_pid INTEGER,container_pid INTEGER,physical_order INTEGER);
                CREATE TABLE container_seed(container_pid INTEGER,item_pid INTEGER,seed_order INTEGER);
                INSERT INTO container VALUES(42,'Native Mix',32,1,1);
            """)
            connection.execute("INSERT INTO item_to_container VALUES(?,42,0)", (_PID,))
            connection.execute("INSERT INTO container_seed VALUES(42,?,0)", (_PID,))
            connection.commit()
            companion.write_bytes(connection.serialize())
        finally:
            connection.close()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="nano")
    return DeviceCoordinator(Storage(platform)), root


def test_selection_loads_mix_and_saved_playlist_without_mutating_or_importing(
    tmp_path: Path,
) -> None:
    coordinator, root = _device(tmp_path)
    before = {
        p: p.read_bytes()
        for p in (root / "iPod_Control/iTunes").rglob("*")
        if p.is_file()
    }
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id, reconcile_metadata=False)
    assert [(c.name, c.kind, c.track_ids) for c in active.genius.collections] == [
        ("Saved Genius", GeniusCollectionKind.PLAYLIST, (7, 7)),
        ("Native Mix", GeniusCollectionKind.MIX, (7,)),
    ]
    assert not active.genius.issues
    assert not active.library.playlists
    assert active.library.tracks[0].title == "Blue Train"
    assert all(p.read_bytes() == data for p, data in before.items())
    coordinator.deactivate()
    assert coordinator.active_ipod is None


def test_damaged_optional_sqlite_keeps_saved_genius_and_primary_library_visible(
    tmp_path: Path,
) -> None:
    coordinator, _ = _device(tmp_path, damaged=True)
    active = coordinator.select_device(
        coordinator.discover_devices().candidates[0].id, reconcile_metadata=False
    )
    assert active.library.tracks[0].title == "Blue Train"
    assert [c.name for c in active.genius.collections] == ["Saved Genius"]
    assert active.genius.issues


@pytest.mark.parametrize("disconnect_after_commit", [False, True])
def test_successful_publication_refreshes_browse_from_published_companion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disconnect_after_commit: bool,
) -> None:
    root = _nano6(tmp_path)
    companion = root / "iPod_Control/iTunes/iTunes Library.itlp/Library.itdb"
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(companion.read_bytes())
        connection.execute(
            "INSERT INTO container(pid,name,distinguished_kind,smart_is_genius,name_order) VALUES(42,'Retained Mix',32,1,1)"
        )
        connection.execute(
            "INSERT INTO item_to_container(item_pid,container_pid,physical_order) VALUES(?,42,0)",
            (_PID,),
        )
        connection.execute(
            "INSERT INTO container_seed(container_pid,item_pid,seed_order) VALUES(42,?,0)",
            (_PID,),
        )
        connection.commit()
        companion.write_bytes(connection.serialize())
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="nano")
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id,
            reconcile_metadata=False,
        )
        assert [c.name for c in active.genius.collections] == ["Retained Mix"]
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, regenerate_sqlite=True
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert review.result.prepared is not None, review.result.issues
        if disconnect_after_commit:
            execute = FilesystemSession.execute_transaction

            def disconnect_after_verified_commit(
                session: FilesystemSession,
                plan: StorageTransaction,
                *,
                checkpoint: Callable[[], None] | None = None,
                progress: Callable[[TransactionProgress], None] | None = None,
                activity: Callable[[TransactionActivity], None] | None = None,
            ) -> TransactionResult:
                result = execute(
                    session,
                    plan,
                    checkpoint=checkpoint,
                    progress=progress,
                    activity=activity,
                )
                platform.disconnect(root)
                session.invalidate("Disconnected after verified commit")
                return result

            monkeypatch.setattr(
                FilesystemSession,
                "execute_transaction",
                disconnect_after_verified_commit,
            )
        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert saved.active.genius == active.genius
        assert saved.active.genius is not active.genius
        assert not saved.active.genius.issues
        assert saved.active.library.tracks[0].title == "Blue Train"
        if disconnect_after_commit:
            assert saved.recovery_path
            assert "save.cleanup_pending" in {issue.code for issue in saved.issues}
            assert "save.source_unavailable" not in {
                issue.code for issue in saved.issues
            }
    finally:
        coordinator.close()
