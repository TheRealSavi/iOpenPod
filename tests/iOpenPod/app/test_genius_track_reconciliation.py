"""Track deletion keeps native Genius collections coherent and recoverable."""

import plistlib
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.binary_fixtures import parse_mhod

from iOpenPod.app.library_workspace import LibraryWorkspace
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import PlaylistKind
from iPodDB.sidecars import (
    GeniusPlaylist,
    create_genius_playlist,
    parse_genius_playlist,
)


@pytest.mark.parametrize("canonical", (False, True))
@pytest.mark.parametrize("removed_index", (0, 1))
@pytest.mark.parametrize("binary", (False, True))
def test_track_removal_reconciles_saved_and_canonical_members_with_recovery(
    tmp_path: Path, canonical: bool, removed_index: int, binary: bool
) -> None:
    device = build_device(tmp_path, model="MB565")
    directory = device.root / "iPod_Control/iTunes"
    path = directory / "GeniusPlaylist_1.plist"
    try:
        pids = tuple(t.ipod.db_track_id for t in device.active.library.tracks if t.ipod)
        assert len(pids) == 2
        if canonical:
            document = parse_iTunesDB((directory / "iTunesDB").read_bytes())
            for row in document.find_chunks(MhypHeader):
                if row.chunk.header.playlist_id == 10:
                    document = document.replace_chunk(
                        row,
                        replace(
                            row.chunk,
                            children=(
                                parse_mhod(54, struct.pack("<Q", pids[0])),
                                *row.chunk.children,
                            ),
                        ),
                    )
            (directory / "iTunesDB").write_bytes(write_iTunesDB(document))
            device.original["iPod_Control/iTunes/iTunesDB"] = (
                directory / "iTunesDB"
            ).read_bytes()
        playlist = GeniusPlaylist(
            1,
            "Saved collection",
            pids[0],
            123456,
            None if binary else (0, 1, 0, 1),
            (pids[0], pids[1], pids[0], pids[1]),
            playlist_persistent_id=10 if canonical else 99,
        )
        properties = plistlib.loads(create_genius_playlist(playlist).serialize())
        properties["future"] = {"blob": b"\x00\xff", "values": [True, 2.5]}
        data = plistlib.dumps(
            properties, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML
        )
        path.write_bytes(data)
        active = device.coordinator.select_device(device.active.candidate.id)
        workspace = LibraryWorkspace()
        workspace.load(active.library)
        removed = active.library.tracks[removed_index]
        workspace.remove_tracks((removed.track_id,), workspace.edit_revision)
        review = device.prepare(workspace.desired_snapshot(), delete=True)
        assert review.result.prepared is not None, review.result.issues
        assert path.read_bytes() == data
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        result = parse_genius_playlist(path.read_bytes()).playlist
        survivor = pids[1 - removed_index]
        assert result == replace(
            playlist,
            seed_track_persistent_id=survivor,
            track_persistent_ids=(survivor, survivor),
            track_master_indexes=None if binary else (0, 0),
        )
        assert plistlib.loads(path.read_bytes())["future"] == properties["future"]
        if canonical:
            retained = next(
                p
                for p in saved.active.library.playlists
                if p.kind is PlaylistKind.GENIUS
            )
            assert retained.genius_seed_persistent_id == survivor
            assert all(t != removed.track_id for t in retained.track_ids)
        device.restore(saved.recovery_path)
        assert path.read_bytes() == data
    finally:
        device.coordinator.close()


def test_deleting_last_saved_member_removes_only_its_sidecar(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/GeniusPlaylist_1.plist"
    other = device.root / "iPod_Control/iTunes/GeniusPlaylist_2.plist"
    try:
        tracks = device.active.library.tracks
        assert tracks[0].ipod is not None and tracks[1].ipod is not None
        first, second = tracks[0].ipod.db_track_id, tracks[1].ipod.db_track_id
        data = create_genius_playlist(
            GeniusPlaylist(1, "Empty after removal", first, 0, None, (first,))
        ).serialize()
        untouched = create_genius_playlist(
            GeniusPlaylist(2, "Retained", second, 0, None, (second,))
        ).serialize()
        path.write_bytes(data)
        other.write_bytes(untouched)
        active = device.coordinator.select_device(device.active.candidate.id)
        workspace = LibraryWorkspace()
        workspace.load(active.library)
        workspace.remove_tracks((tracks[0].track_id,), workspace.edit_revision)
        review = device.prepare(workspace.desired_snapshot(), delete=True)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert not path.exists()
        assert other.read_bytes() == untouched
        device.restore(saved.recovery_path)
        assert path.read_bytes() == data
        assert other.read_bytes() == untouched
    finally:
        device.coordinator.close()


def test_changed_saved_sidecar_invalidates_review_before_publication(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/GeniusPlaylist_1.plist"
    try:
        tracks = device.active.library.tracks
        pids = tuple(t.ipod.db_track_id for t in tracks if t.ipod)
        data = create_genius_playlist(
            GeniusPlaylist(1, "Saved", pids[0], 0, (0, 1), pids)
        ).serialize()
        path.write_bytes(data)
        active = device.coordinator.select_device(device.active.candidate.id)
        workspace = LibraryWorkspace()
        workspace.load(active.library)
        workspace.remove_tracks((tracks[0].track_id,), workspace.edit_revision)
        review = device.prepare(workspace.desired_snapshot(), delete=True)
        assert review.result.prepared is not None, review.result.issues
        changed = data.replace(b"Saved", b"Changed")
        path.write_bytes(changed)
        saved = device.save(review)
        assert saved.active is None
        device.assert_original()
        assert path.read_bytes() == changed
    finally:
        device.coordinator.close()
