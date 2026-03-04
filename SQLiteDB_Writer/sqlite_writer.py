"""SQLite database writer — orchestrates writing all SQLite databases.

This is the main entry point for the SQLiteDB_Writer module. It
coordinates writing all five databases plus the checksum file for
iPod Nano 6G/7G.

The databases are written to:
    /iPod_Control/iTunes/iTunes Library.itlp/

Usage:
    from SQLiteDB_Writer import write_sqlite_databases

    write_sqlite_databases(
        ipod_path="/media/ipod",
        tracks=tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name="iPod",
    )
"""

import os
import shutil
import time
import logging
import tempfile
from typing import Optional

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Writer.mhyp_writer import PlaylistInfo
from ipod_models import ChecksumType, DeviceCapabilities
from device_info import detect_checksum_type, get_firewire_id

from .library_writer import write_library_itdb
from .locations_writer import write_locations_itdb
from .dynamic_writer import write_dynamic_itdb
from .extras_writer import write_extras_itdb
from .genius_writer import write_genius_itdb
from .cbk_writer import write_locations_cbk

logger = logging.getLogger(__name__)

# Directory within iPod where SQLite databases live
ITLP_DIR = os.path.join("iPod_Control", "iTunes", "iTunes Library.itlp")


def write_sqlite_databases(
    ipod_path: str,
    tracks: list[TrackInfo],
    playlists: Optional[list[PlaylistInfo]] = None,
    smart_playlists: Optional[list[PlaylistInfo]] = None,
    master_playlist_name: str = "iPod",
    db_pid: int = 0,
    capabilities: Optional[DeviceCapabilities] = None,
    firewire_id: Optional[bytes] = None,
    backup: bool = True,
) -> bool:
    """Write all SQLite databases for iPod Nano 6G/7G.

    Writes the databases to a temp directory first, then atomically
    replaces the files in the iTunes Library.itlp directory.

    Args:
        ipod_path: Mount point of iPod (e.g. "E:\\")
        tracks: List of TrackInfo objects (dbid must already be assigned).
        playlists: User playlists (master is auto-generated).
        smart_playlists: Smart playlists.
        master_playlist_name: Name for the master playlist.
        db_pid: Database persistent ID (from mhbd db_id).
        capabilities: Device capabilities.
        firewire_id: 8-byte FireWire GUID for signing.
        backup: Whether to backup existing databases.

    Returns:
        True if all databases were written successfully.
    """
    itlp_path = os.path.join(ipod_path, ITLP_DIR)

    # Ensure the directory exists
    os.makedirs(itlp_path, exist_ok=True)

    # Determine timezone offset
    if time.daylight:
        tz_offset = -time.altzone
    else:
        tz_offset = -time.timezone

    # Determine checksum type
    checksum_type = ChecksumType.NONE
    if capabilities:
        checksum_type = capabilities.checksum
    else:
        checksum_type = detect_checksum_type(ipod_path)

    # Get FireWire ID if needed and not provided
    if firewire_id is None and checksum_type in (
        ChecksumType.HASHAB, ChecksumType.HASH58
    ):
        try:
            firewire_id = get_firewire_id(ipod_path)
        except Exception as e:
            logger.warning("Could not get FireWire ID for cbk signing: %s", e)

    # Generate db_pid if not provided
    if not db_pid:
        import random
        db_pid = random.getrandbits(64)

    # Master playlist PID = db_pid (matches libgpod convention)
    master_pid = db_pid

    # Backup existing databases
    if backup:
        for fname in ("Library.itdb", "Locations.itdb", "Dynamic.itdb",
                      "Extras.itdb", "Genius.itdb", "Locations.itdb.cbk"):
            fpath = os.path.join(itlp_path, fname)
            if os.path.exists(fpath):
                try:
                    shutil.copy2(fpath, fpath + ".backup")
                except Exception as e:
                    logger.warning("Could not backup %s: %s", fname, e)

    # Write all databases to temp directory first, then move
    # This gives us atomicity — if any write fails, the originals are intact.
    with tempfile.TemporaryDirectory(prefix="iOpenPod_sqlite_", ignore_cleanup_errors=True) as tmp_dir:
        try:
            # 1. Library.itdb (tracks, albums, artists, playlists, …)
            lib_path = os.path.join(tmp_dir, "Library.itdb")
            write_library_itdb(
                path=lib_path,
                tracks=tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=master_playlist_name,
                db_pid=db_pid,
                tz_offset=tz_offset,
            )

            # 2. Locations.itdb (file path mappings)
            loc_path = os.path.join(tmp_dir, "Locations.itdb")
            write_locations_itdb(
                path=loc_path,
                tracks=tracks,
                tz_offset=tz_offset,
            )

            # 3. Dynamic.itdb (play counts, ratings, bookmarks)
            dyn_path = os.path.join(tmp_dir, "Dynamic.itdb")
            write_dynamic_itdb(
                path=dyn_path,
                tracks=tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_pid=master_pid,
                tz_offset=tz_offset,
            )

            # 4. Extras.itdb (lyrics, chapters)
            extras_path = os.path.join(tmp_dir, "Extras.itdb")
            write_extras_itdb(
                path=extras_path,
                tracks=tracks,
            )

            # 5. Genius.itdb (empty tables)
            genius_path = os.path.join(tmp_dir, "Genius.itdb")
            write_genius_itdb(path=genius_path)

            # 6. Locations.itdb.cbk (HASHAB-signed block checksums)
            cbk_path = os.path.join(tmp_dir, "Locations.itdb.cbk")
            try:
                write_locations_cbk(
                    cbk_path=cbk_path,
                    locations_itdb_path=loc_path,
                    checksum_type=checksum_type,
                    firewire_id=firewire_id,
                )
            except Exception as e:
                logger.error("Failed to write Locations.itdb.cbk: %s", e)
                # CBK is critical for HASHAB devices — fail the whole write
                if checksum_type == ChecksumType.HASHAB:
                    raise
                # For other devices, continue without it
                cbk_path = None

            # Move all files to the target directory
            files_to_move = [
                ("Library.itdb", lib_path),
                ("Locations.itdb", loc_path),
                ("Dynamic.itdb", dyn_path),
                ("Extras.itdb", extras_path),
                ("Genius.itdb", genius_path),
            ]
            if cbk_path and os.path.exists(cbk_path):
                files_to_move.append(("Locations.itdb.cbk", cbk_path))

            for fname, src_path in files_to_move:
                dst_path = os.path.join(itlp_path, fname)
                try:
                    shutil.copy2(src_path, dst_path)
                except Exception as e:
                    logger.error("Failed to copy %s to iPod: %s", fname, e)
                    raise

            logger.info("SQLite databases written to %s "
                        "(%d tracks, %d playlists, %d smart playlists)",
                        itlp_path, len(tracks),
                        len(playlists or []),
                        len(smart_playlists or []))
            return True

        except Exception as e:
            logger.error("Failed to write SQLite databases: %s", e,
                         exc_info=True)
            return False
