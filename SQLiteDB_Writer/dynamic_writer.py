"""Dynamic.itdb writer — play counts, ratings, and bookmark data.

Contains item_stats (per-track play/skip counts, ratings, bookmarks)
and container_ui (playlist UI state like play order, repeat, shuffle).

Reference: libgpod itdb_sqlite.c mk_Dynamic()
"""

import sqlite3
import logging
from typing import Optional

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Writer.mhyp_writer import PlaylistInfo

logger = logging.getLogger(__name__)


def _s64(val: int) -> int:
    """Convert unsigned 64-bit int to signed for SQLite INTEGER storage."""
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


_DYNAMIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS item_stats (
    item_pid INTEGER NOT NULL,
    has_been_played INTEGER DEFAULT 0,
    date_played INTEGER DEFAULT 0,
    play_count_user INTEGER DEFAULT 0,
    play_count_recent INTEGER DEFAULT 0,
    date_skipped INTEGER DEFAULT 0,
    skip_count_user INTEGER DEFAULT 0,
    skip_count_recent INTEGER DEFAULT 0,
    bookmark_time_ms REAL,
    bookmark_time_ms_common REAL,
    user_rating INTEGER DEFAULT 0,
    user_rating_common INTEGER DEFAULT 0,
    rental_expired INTEGER DEFAULT 0,
    play_count_user_original INTEGER DEFAULT 0,
    skip_count_user_original INTEGER DEFAULT 0,
    genius_id INTEGER DEFAULT 0,
    PRIMARY KEY (item_pid)
);

CREATE TABLE IF NOT EXISTS container_ui (
    container_pid INTEGER NOT NULL,
    play_order INTEGER DEFAULT 0,
    is_reversed INTEGER DEFAULT 0,
    album_field_order INTEGER DEFAULT 0,
    repeat_mode INTEGER DEFAULT 0,
    shuffle_items INTEGER DEFAULT 0,
    has_been_shuffled INTEGER DEFAULT 0,
    PRIMARY KEY (container_pid)
);

CREATE TABLE IF NOT EXISTS rental_info (
    item_pid INTEGER NOT NULL,
    rental_date_started INTEGER DEFAULT 0,
    rental_duration INTEGER DEFAULT 0,
    rental_playback_date_started INTEGER DEFAULT 0,
    rental_playback_duration INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0,
    PRIMARY KEY (item_pid)
);
"""

# Core Data epoch offset
CORE_DATA_EPOCH = 978307200


def write_dynamic_itdb(
    path: str,
    tracks: list[TrackInfo],
    playlists: Optional[list[PlaylistInfo]] = None,
    smart_playlists: Optional[list[PlaylistInfo]] = None,
    master_pid: int = 0,
    tz_offset: int = 0,
) -> None:
    """Write Dynamic.itdb SQLite database.

    Args:
        path: Output file path.
        tracks: List of TrackInfo objects.
        playlists: User playlists (for container_ui entries).
        smart_playlists: Smart playlists.
        master_pid: PID of the master playlist (for container_ui).
        tz_offset: Timezone offset in seconds.
    """
    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    cur = conn.cursor()

    cur.executescript(_DYNAMIC_SCHEMA)

    # ── item_stats ─────────────────────────────────────────────────────
    for track in tracks:
        has_been_played = 1 if track.play_count > 0 else 0

        # Convert timestamps to Core Data (0 must stay 0)
        date_played = 0
        if track.last_played and track.last_played > 0:
            date_played = track.last_played - CORE_DATA_EPOCH - tz_offset

        date_skipped = 0
        if track.last_skipped and track.last_skipped > 0:
            date_skipped = track.last_skipped - CORE_DATA_EPOCH - tz_offset

        cur.execute(
            """INSERT INTO item_stats (
                item_pid, has_been_played, date_played,
                play_count_user, play_count_recent,
                date_skipped, skip_count_user, skip_count_recent,
                bookmark_time_ms, bookmark_time_ms_common,
                user_rating, user_rating_common,
                rental_expired,
                play_count_user_original, skip_count_user_original,
                genius_id
            ) VALUES (?, ?, ?, ?, 0, ?, ?, 0, ?, ?, ?, ?, 0, ?, ?, 0)""",
            (
                _s64(track.dbid), has_been_played, date_played,
                track.play_count,
                date_skipped, track.skip_count,
                float(track.bookmark_time), float(track.bookmark_time),
                track.rating, track.app_rating,
                track.play_count, track.skip_count,
            )
        )

    # ── container_ui ───────────────────────────────────────────────────
    # One row per playlist
    if master_pid:
        cur.execute(
            "INSERT INTO container_ui (container_pid, play_order, is_reversed, "
            "album_field_order, repeat_mode, shuffle_items, has_been_shuffled) "
            "VALUES (?, 0, 0, 1, 0, 0, 0)",
            (_s64(master_pid),)
        )

    pl_pid = master_pid + 1 if master_pid else 2
    for pl in (playlists or []):
        cur.execute(
            "INSERT INTO container_ui (container_pid, play_order, is_reversed, "
            "album_field_order, repeat_mode, shuffle_items, has_been_shuffled) "
            "VALUES (?, 0, 0, 1, 0, 0, 0)",
            (_s64(pl_pid),)
        )
        pl_pid += 1

    for spl in (smart_playlists or []):
        cur.execute(
            "INSERT INTO container_ui (container_pid, play_order, is_reversed, "
            "album_field_order, repeat_mode, shuffle_items, has_been_shuffled) "
            "VALUES (?, 0, 0, 1, 0, 0, 0)",
            (_s64(pl_pid),)
        )
        pl_pid += 1

    conn.commit()
    conn.close()

    logger.info("Wrote Dynamic.itdb: %d item_stats, %d container_ui",
                len(tracks),
                1 + len(playlists or []) + len(smart_playlists or []))
