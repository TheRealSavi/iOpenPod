"""Phase selection follows its companion ID, then its exact title fallback."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    resolve_phase_playlist,
)


@pytest.mark.parametrize(
    "pid,expected", [(None, 20), (0, 20), (999, 20), (10, 10), (20, 20), (30, 30)]
)
def test_id_precedes_name_and_previous_markers_are_ignored(
    pid: int | None, expected: int
) -> None:
    snapshot = LibrarySnapshot(
        playlists=(
            Playlist(10, "Music"),
            Playlist(20, "Phase"),
            Playlist(30, "Other", is_phase=True),
            Playlist(40, "Phase", PlaylistKind.FOLDER),
        )
    )
    resolved = resolve_phase_playlist(snapshot, pid)
    assert [p.playlist_id for p in resolved.playlists if p.is_phase] == [expected]


@pytest.mark.parametrize("name", ["phase", "Phase ", "PhaseX"])
def test_name_fallback_is_exact(name: str) -> None:
    snapshot = LibrarySnapshot(playlists=(Playlist(1, name, is_phase=True),))
    assert not resolve_phase_playlist(snapshot, None).playlists[0].is_phase


def test_captured_index_context_survives_other_overlays_and_noop() -> None:
    source = library(mirrored=True).with_phase_playlist(10)
    assert source.snapshot.playlists[0].is_phase
    source = source.with_device_time(source.device_time).with_sidecars(())
    assert source.snapshot.playlists[0].is_phase
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes
    assert result.prepared.snapshot.playlists[0].is_phase
    renamed = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Renamed"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(renamed)))
    assert result.prepared is not None, result.issues
    assert all(
        row.chunk.header.phase_game_flag == 25
        for row in parse_iTunesDB(result.prepared.itunes).find_chunks(MhypHeader)
        if row.chunk.header.playlist_id == 10
    )
