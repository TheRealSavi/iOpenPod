"""Shared helpers for SQLiteDB_Writer modules.

Centralises utilities that were previously duplicated across
library_writer, locations_writer, dynamic_writer, extras_writer,
and genius_writer.
"""

import os
import sqlite3

# ── Timestamp helpers ──────────────────────────────────────────────────
# SQLite databases use Core Data timestamps: seconds since 2001-01-01 UTC
# (the Cocoa/Core Foundation reference date).
CORE_DATA_EPOCH = 978307200  # Unix timestamp of 2001-01-01 00:00:00 UTC


def unix_to_coredata(unix_ts: int, tz_offset: int = 0) -> int:
    """Convert Unix timestamp to Core Data timestamp.

    Args:
        unix_ts: Unix timestamp (seconds since 1970-01-01)
        tz_offset: Timezone offset in seconds (positive = east of UTC)

    Returns:
        Core Data timestamp (seconds since 2001-01-01) adjusted for timezone.
        Returns 0 if input is 0.
    """
    if unix_ts == 0:
        return 0
    return unix_ts - CORE_DATA_EPOCH - tz_offset


def s64(val: int) -> int:
    """Convert unsigned 64-bit int to signed for SQLite INTEGER storage.

    SQLite INTEGER is signed 64-bit (max 2^63-1).  iPod db_ids and PIDs
    are unsigned 64-bit values that may exceed this limit.
    """
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


def open_db(path: str, extra_pragmas: list[str] | None = None) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    """Create a fresh SQLite database at *path*.

    Deletes any existing file, opens a new connection with performance
    PRAGMAs (journal_mode=OFF, synchronous=OFF), and returns (conn, cursor).

    Args:
        path: Output file path.
        extra_pragmas: Additional PRAGMA statements to execute
                       (e.g. ``["encoding='UTF-8'"]``).
    """
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    for pragma in extra_pragmas or []:
        conn.execute(f"PRAGMA {pragma}")

    return conn, conn.cursor()
