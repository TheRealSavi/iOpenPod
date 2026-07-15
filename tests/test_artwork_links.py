from __future__ import annotations

from pathlib import Path

from iopenpod.itunesdb_parser import artwork_links


def test_hydrate_track_artwork_refs_fills_missing_refs_from_song_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        artwork_links,
        "_build_song_to_artwork_id",
        lambda _path: {111: 100, 222: 101},
    )
    tracks = [
        {"db_track_id": 111, "artwork_count": 1, "artwork_id_ref": 0},
        {"db_track_id": 222, "artwork_count": 0},
        {"db_track_id": 333, "artwork_count": 0},
    ]

    count = artwork_links.hydrate_track_artwork_refs(
        tracks,
        tmp_path / "iPod_Control" / "iTunes" / "iTunesDB",
    )

    assert count == 2
    assert tracks[0]["artwork_id_ref"] == 100
    assert tracks[0]["artwork_count"] == 1
    assert tracks[1]["artwork_id_ref"] == 101
    assert tracks[1]["mhii_link"] == 101
    assert tracks[1]["artwork_count"] == 1
    assert "artwork_id_ref" not in tracks[2]


def test_hydrate_track_artwork_refs_keeps_matching_existing_track_refs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        artwork_links,
        "_build_song_to_artwork_id",
        lambda _path: {111: 999},
    )
    tracks = [{"db_track_id": 111, "artwork_count": 1, "artwork_id_ref": 999}]

    count = artwork_links.hydrate_track_artwork_refs(
        tracks,
        tmp_path / "iPod_Control" / "iTunes" / "iTunesDB",
    )

    assert count == 0
    assert tracks[0]["artwork_id_ref"] == 999


def test_hydrate_track_artwork_refs_corrects_stale_track_refs_from_song_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        artwork_links,
        "_build_song_to_artwork_id",
        lambda _path: {111: 100},
    )
    tracks = [{"db_track_id": 111, "artwork_count": 1, "artwork_id_ref": 999}]

    count = artwork_links.hydrate_track_artwork_refs(
        tracks,
        tmp_path / "iPod_Control" / "iTunes" / "iTunesDB",
    )

    assert count == 1
    assert tracks[0]["artwork_id_ref"] == 100
    assert tracks[0]["mhii_link"] == 100
