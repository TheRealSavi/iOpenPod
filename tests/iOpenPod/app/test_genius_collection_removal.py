"""Explicit saved Genius Playlist deletion uses the reviewed Storage transaction."""

import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.binary_fixtures import parse_mhod

from iOpenPod.app.library_write import LibraryPreparationRequest
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library.genius import GeniusCollectionKind
from iPodDB.sidecars import GeniusPlaylist, create_genius_playlist


def test_saved_genius_playlist_removal_is_recoverable(tmp_path: Path) -> None:
    device = build_device(tmp_path, model="MB565")
    sidecar_path = device.root / "iPod_Control/iTunes/GeniusPlaylist_1.plist"
    try:
        first = device.active.library.tracks[0]
        assert first.ipod is not None
        pid = first.ipod.db_track_id
        sidecar = create_genius_playlist(
            GeniusPlaylist(1, "Saved Genius", pid, 0, (0,), (pid,))
        ).serialize()
        sidecar_path.write_bytes(sidecar)
        active = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        collection = next(
            item
            for item in active.genius.collections
            if item.kind is GeniusCollectionKind.PLAYLIST
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library,
                active,
                1,
                1,
                remove_genius_collections=(collection.collection_id,),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert sidecar_path.exists()
        assert any(
            change.path.endswith("GeniusPlaylist_1.plist") and change.action == "remove"
            for change in review.file_changes
        )
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert not sidecar_path.exists()
        assert not saved.active.genius.collections
        device.restore(saved.recovery_path)
        assert sidecar_path.read_bytes() == sidecar
    finally:
        device.coordinator.close()


def test_canonical_genius_playlist_removal_preserves_tracks(tmp_path: Path) -> None:
    device = build_device(tmp_path, model="MB565")
    database_path = device.root / "iPod_Control/iTunes/iTunesDB"
    try:
        document = parse_iTunesDB(database_path.read_bytes())
        for selection in document.find_chunks(MhypHeader):
            if selection.chunk.header.playlist_id == 10:
                document = document.replace_chunk(
                    selection,
                    replace(
                        selection.chunk,
                        children=(
                            parse_mhod(54, struct.pack("<Q", 101)),
                            *selection.chunk.children,
                        ),
                    ),
                )
        database_path.write_bytes(write_iTunesDB(document))
        active = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        collection = next(
            item
            for item in active.genius.collections
            if item.kind is GeniusCollectionKind.PLAYLIST
        )
        desired = replace(active.library, playlists=())
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                active,
                1,
                1,
                delete_omissions=True,
                remove_genius_collections=(collection.collection_id,),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks == active.library.tracks
        assert not saved.active.genius.collections
        reloaded = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert not reloaded.genius.collections
    finally:
        device.coordinator.close()


def test_removing_canonical_playlist_also_removes_its_saved_sidecar(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, model="MB565")
    database_path = device.root / "iPod_Control/iTunes/iTunesDB"
    sidecar_path = device.root / "iPod_Control/iTunes/GeniusPlaylist_1.plist"
    try:
        document = parse_iTunesDB(database_path.read_bytes())
        for selection in document.find_chunks(MhypHeader):
            if selection.chunk.header.playlist_id == 10:
                document = document.replace_chunk(
                    selection,
                    replace(
                        selection.chunk,
                        children=(
                            parse_mhod(54, struct.pack("<Q", 101)),
                            *selection.chunk.children,
                        ),
                    ),
                )
        database_path.write_bytes(write_iTunesDB(document))
        device.original["iPod_Control/iTunes/iTunesDB"] = database_path.read_bytes()
        sidecar = create_genius_playlist(
            GeniusPlaylist(
                1, "Saved Genius", 101, 0, (0,), (101,), playlist_persistent_id=10
            )
        ).serialize()
        sidecar_path.write_bytes(sidecar)
        active = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        collection = next(
            item
            for item in active.genius.collections
            if item.kind is GeniusCollectionKind.PLAYLIST
            and item.native_playlist_id == 10
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(active.library, playlists=()),
                active,
                1,
                1,
                delete_omissions=True,
                remove_genius_collections=(collection.collection_id,),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert any(
            change.path.endswith("GeniusPlaylist_1.plist") and change.action == "remove"
            for change in review.file_changes
        )
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert not sidecar_path.exists()
        assert not saved.active.genius.collections
        device.restore(saved.recovery_path)
        assert sidecar_path.read_bytes() == sidecar
    finally:
        device.coordinator.close()
