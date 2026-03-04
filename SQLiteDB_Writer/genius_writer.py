"""Genius.itdb writer — Genius playlists and similarity data.

Creates a minimal Genius.itdb with empty tables. We don't support Genius
features, but the database file must exist for the firmware.

Reference: libgpod itdb_sqlite.c mk_Genius()
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)


_GENIUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS genius_config (
    id INTEGER NOT NULL,
    version INTEGER,
    default_num_results INTEGER DEFAULT 0,
    min_num_results INTEGER DEFAULT 0,
    data BLOB,
    PRIMARY KEY (id),
    UNIQUE (version)
);

CREATE TABLE IF NOT EXISTS genius_metadata (
    genius_id INTEGER NOT NULL,
    version INTEGER,
    data BLOB,
    PRIMARY KEY (genius_id)
);

CREATE TABLE IF NOT EXISTS genius_similarities (
    genius_id INTEGER NOT NULL,
    version INTEGER,
    data BLOB,
    PRIMARY KEY (genius_id)
);
"""


def write_genius_itdb(path: str) -> None:
    """Write Genius.itdb SQLite database (empty tables).

    Args:
        path: Output file path.
    """
    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    cur = conn.cursor()

    cur.executescript(_GENIUS_SCHEMA)

    conn.commit()
    conn.close()

    logger.info("Wrote Genius.itdb (empty)")
