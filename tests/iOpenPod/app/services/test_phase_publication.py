"""Phase companion preparation and publication on a virtual device."""

import plistlib
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from tests.iOpenPod.app.phase_test_support import StubPhaseAnalysis

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.services.phase import (
    INDEX_PATH,
    MANIFEST_PATH,
    capture_phase_selection,
    prepare_phase,
)
from iPodDB.games import PhaseLibrary, build_phase_library
from iPodDB.games.phase import parse_library
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    Track,
    playlist_entries,
)
from iPodDB.library.models import IPodTrackDetails, MediaType, TrackMetadata
from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    HostPath,
    Storage,
    StorageTransaction,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


def snapshot() -> LibrarySnapshot:
    tracks = tuple(
        Track(
            i,
            str(i),
            "Artist",
            "Album",
            duration,
            ipod=IPodTrackDetails(db_track_id=0x8000000000000000 + i),
            metadata=TrackMetadata(location=f"iPod_Control/Music/F00/{i}.m4a"),
        )
        for i, duration in ((1, 29_999), (2, 30_000), (3, 1_800_999), (4, 1_801_000))
    )
    return LibrarySnapshot(
        (*tracks, replace(tracks[1], track_id=5, media_types=(MediaType.PODCAST,))),
        (
            Playlist(
                0xFEDCBA9876543210,
                "My music",
                entries=playlist_entries((1, 2, 3, 4, 5, 2)),
                is_phase=True,
            ),
        ),
    )


def test_prepare_publish_reuse_and_deselect(tmp_path: Path) -> None:
    manifest = tmp_path / str(MANIFEST_PATH)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        plistlib.dumps({"Name": "Phase", "Version": "1.0", "GUID": "phase"})
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    desired = snapshot()
    analyzer = StubPhaseAnalysis()
    for track in desired.tracks:
        media = tmp_path / track.metadata.location
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"verified input " + str(track.track_id).encode())
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        publication = prepare_phase(
            session, LibrarySnapshot(), desired, analyzer=analyzer
        )
        assert len(publication.writes) == 4
        assert not (tmp_path / str(INDEX_PATH)).exists()
        changed = {w.path for w in publication.writes}
        transaction = StorageTransaction(
            publication.writes,
            (),
            tuple(f for f in publication.files if f.path not in changed),
        )
        session.execute_transaction(transaction)
        index = parse_library((tmp_path / str(INDEX_PATH)).read_bytes())
        assert index.playlist_id == desired.playlists[0].playlist_id
        assert [t.persistent_id for t in index.tracks] == [
            0x8000000000000002,
            0x8000000000000003,
        ]
        assert len(analyzer.calls) == 2
        again = prepare_phase(session, desired, desired, analyzer=analyzer)
        assert not again.writes
        assert len(analyzer.calls) == 2
        media = tmp_path / desired.tracks[1].metadata.location
        media.write_bytes(b"replacement audio")
        regenerated = prepare_phase(session, desired, desired, analyzer=analyzer)
        assert len(analyzer.calls) == 3
        assert regenerated.writes
        cleared = replace(
            desired, playlists=(replace(desired.playlists[0], is_phase=False),)
        )
        result = prepare_phase(session, desired, cleared)
        assert len(result.writes) == 1
        assert result.writes[0].path == INDEX_PATH
        assert isinstance(result.writes[0].source, bytes)
        assert parse_library(result.writes[0].source).playlist_id == 0
        deleted = prepare_phase(session, desired, replace(desired, playlists=()))
        assert deleted.writes == result.writes


def test_workspace_selects_only_one_and_preserves_membership() -> None:
    workspace = LibraryWorkspace()
    original = snapshot()
    workspace.load(original)
    created = workspace.create(PlaylistKind.PLAYLIST, "Other", is_phase=True)
    assert [p.playlist_id for p in workspace.playlists if p.is_phase] == [
        created.playlist_id
    ]
    previous = workspace.playlists[0]
    workspace.update(previous.playlist_id, is_phase=True)
    assert [p.playlist_id for p in workspace.playlists if p.is_phase] == [
        previous.playlist_id
    ]
    assert workspace.playlists[0].entries == original.playlists[0].entries
    with pytest.raises(ValueError, match="editable music"):
        workspace.create(PlaylistKind.FOLDER, "Folder", is_phase=True)


def test_no_phase_does_not_need_device_files_and_missing_game_blocks(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as session:
        assert not prepare_phase(session, LibrarySnapshot(), LibrarySnapshot()).files
        with pytest.raises(ValueError, match="no longer installed"):
            prepare_phase(session, LibrarySnapshot(), snapshot())


def test_selection_capture_reads_full_id_and_extended_header(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    path = tmp_path / str(INDEX_PATH)
    with storage.open_session(storage.discover().volumes[0]) as session:
        pid, before = capture_phase_selection(session)
        assert pid is None and before.fingerprint is None
        path.parent.mkdir(parents=True)
        data = bytearray(build_phase_library(PhaseLibrary(0xFEDCBA9876543210)))
        data[0x40] = 1  # Unknown header data does not hide the selection.
        path.write_bytes(data)
        pid, before = capture_phase_selection(session)
        assert pid == 0xFEDCBA9876543210
        assert before.fingerprint == session.fingerprint(INDEX_PATH)
        path.write_bytes(b"invalid index")
        assert capture_phase_selection(session)[0] is None


def test_incoming_audio_is_analyzed_before_it_exists_on_device(tmp_path: Path) -> None:
    root = tmp_path / "device"
    manifest = root / str(MANIFEST_PATH)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        plistlib.dumps({"Name": "Phase", "Version": "1", "GUID": "phase"})
    )
    host = tmp_path / "prepared.m4a"
    host.write_bytes(b"verified prepared audio")
    payload = host.read_bytes()
    track = snapshot().tracks[1]
    desired = replace(
        snapshot(),
        tracks=(track,),
        playlists=(
            replace(
                snapshot().playlists[0], entries=playlist_entries((track.track_id,))
            ),
        ),
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    analyzer = StubPhaseAnalysis()
    incoming = TransactionWrite(
        DevicePath(track.metadata.location),
        HostPath(host),
        FileContent(len(payload), sha256(payload).hexdigest()),
    )
    with storage.open_session(storage.discover().volumes[0]) as session:
        prepared = prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            media_writes=(incoming,),
        )
        assert len(prepared.writes) == 3  # chart, provenance, index
        assert analyzer.calls == [HostPath(host)]
        assert not (root / track.metadata.location).exists()
        host.write_bytes(b"changed Host audio")
        with pytest.raises(ValueError, match="changed before analysis"):
            prepare_phase(
                session,
                LibrarySnapshot(),
                desired,
                analyzer=analyzer,
                media_writes=(incoming,),
            )
