from __future__ import annotations

from pathlib import Path

from iopenpod.sync._db_io import read_existing_database


def test_read_existing_database_keeps_playlist_datasets_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod_path = tmp_path / "iPod"
    itunes_dir = ipod_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    itdb_path = itunes_dir / "iTunesDB"
    itdb_path.write_bytes(b"mhbd")

    monkeypatch.setattr("iopenpod.device.resolve_itdb_path", lambda _path: str(itdb_path))
    monkeypatch.setattr("iopenpod.itunesdb_parser.parse_itunesdb", lambda _path: {"raw": True})
    monkeypatch.setattr(
        "iopenpod.itunesdb_shared.extraction.extract_datasets",
        lambda _raw: {
            "mhlt": [],
            "mhlp": [
                {"playlist_id": 1, "Title": "Dataset 2 Master", "master_flag": 1}
            ],
            "mhlp_podcast": [
                {"playlist_id": 2, "Title": "Dataset 3 Master", "master_flag": 1}
            ],
            "mhlp_smart": [
                {
                    "playlist_id": 3,
                    "Title": "Rentals",
                    "master_flag": 1,
                    "mhsd5_type": 7,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "iopenpod.itunesdb_shared.extraction.extract_mhod_strings",
        lambda _children: {},
    )
    monkeypatch.setattr(
        "iopenpod.itunesdb_shared.extraction.extract_playlist_extras",
        lambda _children: {},
    )
    monkeypatch.setattr(
        "iopenpod.itunesdb_parser.artwork_links.hydrate_track_artwork_refs",
        lambda _tracks, _itdb_path: None,
    )
    monkeypatch.setattr(
        "iopenpod.itunesdb_parser.playcounts.parse_playcounts",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "iopenpod.itunesdb_parser.otg.load_otg_playlists",
        lambda _itunes_dir, _tracks: [],
    )

    parsed = read_existing_database(ipod_path)

    assert "playlists" not in parsed
    assert "smart_playlists" not in parsed
    assert [row["Title"] for row in parsed["dataset2_standard_playlists"]] == [
        "Dataset 2 Master"
    ]
    assert [row["Title"] for row in parsed["dataset3_podcast_playlists"]] == [
        "Dataset 3 Master"
    ]
    assert [row["Title"] for row in parsed["dataset5_smart_playlists"]] == [
        "Rentals"
    ]
