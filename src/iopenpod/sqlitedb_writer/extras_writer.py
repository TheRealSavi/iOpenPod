"""Extras.itdb writer — lyrics and chapter data.

Creates the Extras.itdb with empty tables. Lyrics from tracks are
inserted if available.

Reference: libgpod itdb_sqlite.c mk_Extras()
"""

import logging

from iopenpod.itunesdb_writer.mhit_writer import TrackInfo

from ._helpers import open_db
from ._helpers import s64 as _s64

logger = logging.getLogger(__name__)


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
    conn, cur = open_db(path)

    cur.executescript(_EXTRAS_SCHEMA)

    # Insert lyrics for tracks that have them
    lyrics_count = 0
    for track in tracks:
        if track.lyrics:
            # Simple checksum: sum of bytes mod 2^32
            checksum = sum(track.lyrics.encode('utf-8')) & 0xFFFFFFFF
            cur.execute(
                "INSERT INTO lyrics (item_pid, checksum, lyrics) VALUES (?, ?, ?)",
                (_s64(track.db_track_id), checksum, track.lyrics)
            )
            lyrics_count += 1

    # Insert chapter data for tracks that have chapters
    chapter_count = 0
    for track in tracks:
        cd = track.chapter_data or {}
        chapters = cd.get("chapters")
        if chapters:
            from iopenpod.itunesdb_writer.mhod_writer import build_chapter_blob
            blob = build_chapter_blob(
                chapters,
                unk024=cd.get("unk024", 0),
                unk028=cd.get("unk028", 0),
                unk032=cd.get("unk032", 0),
            )
            if blob:
                cur.execute(
                    "INSERT INTO chapter (item_pid, data) VALUES (?, ?)",
                    (_s64(track.db_track_id), blob)
                )
                chapter_count += 1

    conn.commit()
    conn.close()

    logger.info("Wrote Extras.itdb: %d lyrics entries, %d chapter entries", lyrics_count, chapter_count)
