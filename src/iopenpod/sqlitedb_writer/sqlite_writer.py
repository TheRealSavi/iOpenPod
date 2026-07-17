"""SQLite database writer — orchestrates writing all SQLite databases.

This is the main entry point for the SQLiteDB_Writer module. It
coordinates writing all five databases plus the checksum file for
iPod Nano 6G/7G.

The databases are written to:
    /iPod_Control/iTunes/iTunes Library.itlp/

Usage:
    from iopenpod.sqlitedb_writer import write_sqlite_databases

    write_sqlite_databases(
        ipod_path="/media/ipod",
        tracks=tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name="iPod",
    )
"""

import logging
import os
import random
import shutil
import tempfile
import time
from collections.abc import Callable

from iopenpod.device import ChecksumType, DeviceCapabilities, detect_checksum_type, get_firewire_id
from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.path_safety import resolve_device_path
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo

from .cbk_writer import write_locations_cbk
from .dynamic_writer import write_dynamic_itdb
from .extras_writer import write_extras_itdb
from .genius_writer import write_genius_itdb
from .library_writer import write_library_itdb
from .locations_writer import write_locations_itdb

logger = logging.getLogger(__name__)

# Directory within iPod where SQLite databases live
ITLP_DIR = os.path.join("iPod_Control", "iTunes", "iTunes Library.itlp")


def _install_database_file(
    src_path: str,
    dst_path: str,
    *,
    before_device_mutation: Callable[[], None],
) -> None:
    """Durably install one generated database without truncating the old one."""
    temp_path = None
    try:
        before_device_mutation()
        temp_path, temp_file = open_unique_sibling_temp(dst_path, mode="wb")
        with temp_file as written_file:
            with open(src_path, "rb") as source_file:
                shutil.copyfileobj(source_file, written_file)
            flush_written_file(written_file)
        before_device_mutation()
        durable_replace(temp_path, dst_path)
    finally:
        if temp_path is not None:
            try:
                before_device_mutation()
                durable_unlink(temp_path, missing_ok=True)
            except OSError as cleanup_error:
                logger.warning(
                    "Could not remove incomplete SQLite database temp file %s: %s",
                    temp_path,
                    cleanup_error,
                )


def write_sqlite_databases(
    ipod_path: str,
    tracks: list[TrackInfo],
    playlists: list[PlaylistInfo] | None = None,
    smart_playlists: list[PlaylistInfo] | None = None,
    master_playlist_name: str = "iPod",
    db_pid: int = 0,
    capabilities: DeviceCapabilities | None = None,
    firewire_id: bytes | None = None,
    backup: bool = True,
    before_device_mutation: Callable[[], None] | None = None,
    reported_volume_format: str = "",
    expected_volume_identity_key: str = "",
) -> bool:
    """Write all SQLite databases for iPod Nano 6G/7G.

    Writes the databases to a temp directory first, then atomically
    replaces the files in the iTunes Library.itlp directory.

    Args:
        ipod_path: Mount point of iPod (e.g. "E:\\")
        tracks: List of TrackInfo objects (db_track_id must already be assigned).
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
    if before_device_mutation is None:
        profile = inspect_device_write_readiness(
            ipod_path,
            reported_volume_format=reported_volume_format,
        )
        current_key = volume_lock_key(profile)
        if (
            expected_volume_identity_key
            and current_key != expected_volume_identity_key
        ):
            raise DeviceWriteSafetyError(
                "A different volume is mounted at the selected iPod path. "
                "iOpenPod stopped before writing SQLite databases."
            )
        with DeviceWriteGuard(ipod_path, volume_key=current_key):
            profile = revalidate_device_write_readiness(
                profile,
                probe_case_sensitivity=True,
            )

            def _revalidate() -> None:
                nonlocal profile
                profile = revalidate_device_write_readiness(profile)

            return write_sqlite_databases(
                ipod_path,
                tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=master_playlist_name,
                db_pid=db_pid,
                capabilities=capabilities,
                firewire_id=firewire_id,
                backup=backup,
                before_device_mutation=_revalidate,
                reported_volume_format=reported_volume_format,
                expected_volume_identity_key=expected_volume_identity_key,
            )

    itlp_path = str(
        resolve_device_path(
            ipod_path,
            ITLP_DIR,
            allowed_subtree=ITLP_DIR,
        )
    )

    # Ensure the directory exists
    if not os.path.isdir(itlp_path):
        before_device_mutation()
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
        db_pid = random.getrandbits(64)

    # Backup existing databases
    if backup:
        try:
            for fname in (
                "Library.itdb",
                "Locations.itdb",
                "Dynamic.itdb",
                "Extras.itdb",
                "Genius.itdb",
                "Locations.itdb.cbk",
            ):
                fpath = os.path.join(itlp_path, fname)
                if os.path.exists(fpath):
                    _install_database_file(
                        fpath,
                        fpath + ".backup",
                        before_device_mutation=before_device_mutation,
                    )
        except DeviceWriteSafetyError:
            raise
        except Exception as exc:
            logger.error("Could not safely back up SQLite databases: %s", exc)
            return False

    # Write all databases to temp directory first, then move
    # This gives us atomicity — if any write fails, the originals are intact.
    with tempfile.TemporaryDirectory(prefix="iOpenPod_sqlite_", ignore_cleanup_errors=True) as tmp_dir:
        try:
            # 1. Library.itdb (tracks, albums, artists, playlists, …)
            lib_path = os.path.join(tmp_dir, "Library.itdb")
            playlist_pids = write_library_itdb(
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
                playlist_pids=playlist_pids,
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
                    ipod_path=ipod_path,
                )
            except Exception as e:
                logger.error("Failed to write Locations.itdb.cbk: %s", e)
                # CBK is critical for signed devices — fail the whole write
                if checksum_type in (ChecksumType.HASHAB, ChecksumType.HASH72):
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
                    _install_database_file(
                        src_path,
                        dst_path,
                        before_device_mutation=before_device_mutation,
                    )
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
