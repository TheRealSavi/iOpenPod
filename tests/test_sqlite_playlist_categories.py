from __future__ import annotations

import sqlite3

from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo
from iopenpod.sqlitedb_writer.library_writer import write_library_itdb


def test_sqlite_writer_maps_libgpod_music_mhsd5_type(tmp_path) -> None:
    db_path = tmp_path / "Library.itdb"

    write_library_itdb(
        str(db_path),
        tracks=[],
        smart_playlists=[
            PlaylistInfo(
                name="Music",
                playlist_id=123,
                master=True,
                mhsd5_type=4,
            )
        ],
        master_playlist_name="iPod",
        db_pid=1,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT distinguished_kind, is_hidden FROM container WHERE name = ?",
            ("Music",),
        ).fetchone()

    assert row == (4, 1)
