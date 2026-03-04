"""Locations.itdb writer — iPod file path mapping database.

Maps track PIDs to their physical file locations on the iPod filesystem.

Schema:
    base_location: single row with root path "iPod_Control/Music"
    location: one row per track, mapping item_pid → "Fxx/ABCD.mp3"

Reference: libgpod itdb_sqlite.c mk_Locations()
"""

import sqlite3
import time
import logging

from iTunesDB_Writer.mhit_writer import TrackInfo, FILETYPE_CODES

logger = logging.getLogger(__name__)

# Core Data epoch offset (same as library_writer)
CORE_DATA_EPOCH = 978307200


def _s64(val: int) -> int:
    """Convert unsigned 64-bit int to signed for SQLite INTEGER storage."""
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


# location_type = 0x46494C45 = "FILE" as big-endian int
LOCATION_TYPE_FILE = 0x46494C45

# Extension codes — same as FILETYPE_CODES (big-endian 4-byte ASCII)
_EXTENSION_CODES = FILETYPE_CODES

# kind_id mapping — matches location_kind_map in Library.itdb
# IDs from real iTunes-written databases on Nano 6G
_KIND_ID = {
    'mp3': 1,   # "MPEG audio file"
    'aac': 3,   # "AAC audio file"
    'm4a': 3,   # "AAC audio file" (or ALAC in M4A container)
    'm4p': 2,   # "Purchased AAC audio file"
    'm4b': 3,   # "AAC audio file" (audiobook)
    'm4v': 3,   #
    'mp4': 3,   #
    'wav': 1,   #
    'aif': 1,   #
    'aiff': 1,  #
    'alac': 3,  # ALAC is in M4A container
}


def _ipod_path_to_location(ipod_path: str) -> str:
    """Convert iPod colon-separated path to slash-based location.

    Input:  ":iPod_Control:Music:F04:ZEUN.mp3"
    Output: "F04/ZEUN.mp3"

    The location field stores the path relative to the base_location
    ("iPod_Control/Music"), using forward slashes.
    """
    # Strip leading colon and split
    parts = ipod_path.strip(':').split(':')
    # Skip "iPod_Control" and "Music" prefix
    # The path format is :iPod_Control:Music:Fxx:filename
    # We want: Fxx/filename
    if len(parts) >= 4 and parts[0] == 'iPod_Control' and parts[1] == 'Music':
        return '/'.join(parts[2:])
    elif len(parts) >= 2:
        # Fallback: just take the last two parts
        return '/'.join(parts[-2:])
    else:
        return ipod_path.strip(':').replace(':', '/')


_LOCATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS base_location (
    id INTEGER NOT NULL,
    path TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS location (
    item_pid INTEGER NOT NULL,
    sub_id INTEGER NOT NULL DEFAULT 0,
    base_location_id INTEGER DEFAULT 0,
    location_type INTEGER,
    location TEXT,
    extension INTEGER,
    kind_id INTEGER DEFAULT 0,
    date_created INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    file_creator INTEGER,
    file_type INTEGER,
    num_dir_levels_file INTEGER,
    num_dir_levels_lib INTEGER,
    PRIMARY KEY (item_pid, sub_id)
);
"""


def write_locations_itdb(
    path: str,
    tracks: list[TrackInfo],
    tz_offset: int = 0,
) -> None:
    """Write Locations.itdb SQLite database.

    Args:
        path: Output file path.
        tracks: List of TrackInfo objects (with dbid and location set).
        tz_offset: Timezone offset in seconds (positive = east of UTC).
    """
    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    cur = conn.cursor()

    cur.executescript(_LOCATIONS_SCHEMA)

    # Single base_location entry
    cur.execute(
        "INSERT INTO base_location (id, path) VALUES (1, 'iPod_Control/Music')"
    )

    # One location per track
    now = int(time.time())

    for track in tracks:
        location = _ipod_path_to_location(track.location)
        ft = track.filetype.lower()
        extension = _EXTENSION_CODES.get(ft, _EXTENSION_CODES.get('mp3', 0x4D503320))
        kind_id = _KIND_ID.get(ft, 0)

        # date_created: Core Data timestamp of when the file was added
        date_added = track.date_added or now
        date_cd = date_added - CORE_DATA_EPOCH - tz_offset if date_added else 0

        cur.execute(
            """INSERT INTO location (
                item_pid, sub_id, base_location_id, location_type,
                location, extension, kind_id, date_created, file_size,
                file_creator, file_type,
                num_dir_levels_file, num_dir_levels_lib
            ) VALUES (?, 0, 1, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)""",
            (
                _s64(track.dbid), LOCATION_TYPE_FILE,
                location, extension, kind_id,
                date_cd, track.size,
            )
        )

    conn.commit()
    conn.close()

    logger.info("Wrote Locations.itdb: %d locations", len(tracks))
