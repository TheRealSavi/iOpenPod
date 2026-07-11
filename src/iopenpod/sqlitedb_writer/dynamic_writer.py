"""Dynamic.itdb writer — play counts, ratings, and bookmark data.

Contains item_stats (per-track play/skip counts, ratings, bookmarks)
and container_ui (playlist UI state like play order, repeat, shuffle).

Reference: libgpod itdb_sqlite.c mk_Dynamic()
"""

import logging

from iopenpod.itunesdb_writer.mhit_writer import TrackInfo

from ._helpers import open_db, unix_to_coredata
from ._helpers import s64 as _s64

logger = logging.getLogger(__name__)


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


def write_dynamic_itdb(
    path: str,
    tracks: list[TrackInfo],
    playlist_pids: list[int] | None = None,
    tz_offset: int = 0,
) -> None:
    """Write Dynamic.itdb SQLite database.

    Args:
        path: Output file path.
        tracks: List of TrackInfo objects.
        playlist_pids: All playlist PIDs (master + user + smart), as returned
                       by ``write_library_itdb()``.  One ``container_ui`` row
                       is written per PID.
        tz_offset: Timezone offset in seconds.
    """
    conn, cur = open_db(path)

    cur.executescript(_DYNAMIC_SCHEMA)

    # ── item_stats ─────────────────────────────────────────────────────
    for track in tracks:
        has_been_played = 1 if track.play_count > 0 else 0

        date_played = unix_to_coredata(track.last_played or 0, tz_offset)
        date_skipped = unix_to_coredata(track.last_skipped or 0, tz_offset)

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
                _s64(track.db_track_id), has_been_played, date_played,
                track.play_count,
                date_skipped, track.skip_count,
                float(track.bookmark_time), float(track.bookmark_time),
                track.rating, track.app_rating,
                track.play_count, track.skip_count,
            )
        )

    # ── container_ui ───────────────────────────────────────────────────
    # One row per playlist PID (master + user + smart)
    for pid in (playlist_pids or []):
        cur.execute(
            "INSERT INTO container_ui (container_pid, play_order, is_reversed, "
            "album_field_order, repeat_mode, shuffle_items, has_been_shuffled) "
            "VALUES (?, 0, 0, 1, 0, 0, 0)",
            (_s64(pid),)
        )

    conn.commit()
    conn.close()

    logger.info("Wrote Dynamic.itdb: %d item_stats, %d container_ui",
                len(tracks), len(playlist_pids or []))
