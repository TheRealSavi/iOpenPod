"""Extras.itdb writer — lyrics and chapter data.

Creates the Extras.itdb with empty tables. Lyrics from tracks are
inserted if available.

Reference: libgpod itdb_sqlite.c mk_Extras()
"""

import sqlite3
import logging

from iTunesDB_Writer.mhit_writer import TrackInfo

logger = logging.getLogger(__name__)


def _s64(val: int) -> int:
    """Convert unsigned 64-bit int to signed for SQLite INTEGER storage."""
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


_EXTRAS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapter (
    item_pid INTEGER NOT NULL,
    data BLOB,
    PRIMARY KEY (item_pid)
);

CREATE TABLE IF NOT EXISTS lyrics (
    item_pid INTEGER NOT NULL,
    checksum INTEGER,
    lyrics TEXT,
    PRIMARY KEY (item_pid)
);
"""


def write_extras_itdb(
    path: str,
    tracks: list[TrackInfo],
) -> None:
    """Write Extras.itdb SQLite database.

    Args:
        path: Output file path.
        tracks: List of TrackInfo objects.
    """
    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    cur = conn.cursor()

    cur.executescript(_EXTRAS_SCHEMA)

    # Insert lyrics for tracks that have them
    lyrics_count = 0
    for track in tracks:
        if track.lyrics:
            # Simple checksum: sum of bytes mod 2^32
            checksum = sum(track.lyrics.encode('utf-8')) & 0xFFFFFFFF
            cur.execute(
                "INSERT INTO lyrics (item_pid, checksum, lyrics) VALUES (?, ?, ?)",
                (_s64(track.dbid), checksum, track.lyrics)
            )
            lyrics_count += 1

    conn.commit()
    conn.close()

    logger.info("Wrote Extras.itdb: %d lyrics entries", lyrics_count)
