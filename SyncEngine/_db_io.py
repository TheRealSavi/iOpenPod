"""iPod database read/write helpers — parse existing DB, write final DB.

Extracted from sync_executor.py to keep the orchestrator focused on
sync flow control.
"""

import logging
import os
import struct
from collections.abc import Callable
from pathlib import Path

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Writer.mhyp_writer import PlaylistInfo

logger = logging.getLogger(__name__)


def read_existing_database(ipod_path: Path) -> dict:
    """Read existing tracks, playlists, and smart playlists from iTunesDB.

    Also reads the Play Counts file (if present) and merges per-track
    deltas into the track dicts.  After merging:
    - ``play_count_1`` / ``skip_count`` are the new cumulative values
    - ``recent_playcount`` / ``recent_skipcount`` are the deltas
    - ``rating`` may be overridden if the user rated on the iPod
    """
    from iTunesDB_Parser import parse_itunesdb
    from iTunesDB_Parser.playcounts import merge_playcounts, parse_playcounts
    from iTunesDB_Shared.extraction import (
        extract_datasets,
        extract_mhod_strings,
        extract_playlist_extras,
    )
    from iTunesDB_Shared.field_base import filetype_to_string

    empty = {"tracks": [], "playlists": [], "smart_playlists": []}
    from ipod_device import resolve_itdb_path
    _resolved = resolve_itdb_path(str(ipod_path))
    itdb_path = Path(_resolved) if _resolved else ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"
    if not itdb_path.exists():
        return empty

    try:
        raw = parse_itunesdb(str(itdb_path))
        data = extract_datasets(raw)
        tracks = data.get("mhlt", [])

        # Flatten MHOD strings and convert values for each track
        for t in tracks:
            children = t.pop("children", [])
            t.update(extract_mhod_strings(children))
            if "filetype" in t:
                t["filetype"] = filetype_to_string(t["filetype"])
            # sample_rate_1 is already converted from 16.16 fixed-point
            # to Hz by the read_transform in mhit_defs.py

        # ── Merge Play Counts file (iPod-generated deltas) ──────────
        pc_path = ipod_path / "iPod_Control" / "iTunes" / "Play Counts"
        pc_entries = parse_playcounts(pc_path)
        if pc_entries is not None:
            merge_playcounts(tracks, pc_entries)
        else:
            # No Play Counts file → zero deltas for all tracks
            for t in tracks:
                t.setdefault("recent_playcount", 0)
                t.setdefault("recent_skipcount", 0)

        # NOTE: GUI track edits (rating, flags, etc.) are no longer
        # silently applied here.  They flow through the diff engine as
        # proper SyncItems so they appear in the sync review UI.

        def _process_playlist_list(pl_list):
            for pl in pl_list:
                mhod_children = pl.pop("mhod_children", [])
                pl.update(extract_mhod_strings(mhod_children))
                pl.update(extract_playlist_extras(mhod_children))
                mhip_children = pl.pop("mhip_children", [])
                # parse_children wraps each item as {"chunk_type": ..., "data": {...}}.
                # Flatten to the inner data dict so _build_regular_playlists can
                # access track_id, group_id, etc. directly via item.get().
                pl["items"] = [c["data"] for c in mhip_children if "data" in c]

        # Dataset 2: regular + user playlists (mhlp)
        # libgpod prefers DS3 over DS2 and only reads ONE.  We prefer
        # DS2 when present, but fall back to DS3 ("mhlp_podcast") when
        # DS2 is empty — some devices (Nano 5G+) only write type 3.
        all_playlists = data.get("mhlp", [])
        if not all_playlists:
            all_playlists = data.get("mhlp_podcast", [])
        _process_playlist_list(all_playlists)
        # Deduplicate by playlist_id
        seen_ids: set[int] = set()
        playlists: list[dict] = []
        for pl in all_playlists:
            pid = pl.get("playlist_id", 0)
            if pid not in seen_ids:
                seen_ids.add(pid)
                playlists.append(pl)

        # Dataset 5: smart playlists for browsing (mhlp_smart)
        smart_playlists = data.get("mhlp_smart", [])
        _process_playlist_list(smart_playlists)

        # Import On-The-Go playlists from OTGPlaylistInfo files.
        # These are device-created playlists stored outside the iTunesDB; we
        # inject them as regular playlists so they are committed to the
        # iTunesDB on the next write.
        from iTunesDB_Parser.otg import load_otg_playlists
        itunes_dir = itdb_path.parent
        otg = load_otg_playlists(str(itunes_dir), tracks)
        for pl in otg:
            if pl.get("playlist_id", 0) not in seen_ids:
                seen_ids.add(pl["playlist_id"])
                playlists.append(pl)

        logger.info(
            "Parsed iPod database: %d tracks, %d playlists, %d smart playlists",
            len(tracks), len(playlists), len(smart_playlists),
        )
        return {
            "tracks": tracks,
            "playlists": playlists,
            "smart_playlists": smart_playlists,
        }
    except Exception as e:
        logger.error("Failed to parse iTunesDB: %s", e)
        return empty


def write_database(
    ipod_path: Path,
    tracks: list[TrackInfo],
    pc_file_paths: dict | None = None,
    playlists: list[PlaylistInfo] | None = None,
    smart_playlists: list[PlaylistInfo] | None = None,
    master_playlist_name: str = "iPod",
    progress_callback: Callable[[str], None] | None = None,
    raise_on_error: bool = False,
) -> bool:
    """Write tracks to iTunesDB (and ArtworkDB if pc_file_paths provided).

    Automatically detects device capabilities from the centralized store
    and passes them to the writer for db_version, gapless/video filtering,
    and conditional podcast MHSD inclusion.

    For devices with ``uses_sqlite_db`` (Nano 6G/7G), also writes the
    SQLite databases to ``iTunes Library.itlp/``.  The firmware on those
    devices reads the SQLite databases exclusively.
    """
    from iTunesDB_Writer import write_itunesdb

    logger.debug("ART: _write_database called with %d tracks, pc_file_paths=%s",
                 len(tracks), 'None' if pc_file_paths is None else len(pc_file_paths))
    logger.debug(
        "DB: playlists=%s, smart_playlists=%s",
        len(playlists) if playlists else 0,
        len(smart_playlists) if smart_playlists else 0,
    )

    # Resolve capabilities once for the writer
    capabilities = None
    try:
        from ipod_device import capabilities_for_family_gen, get_current_device
        dev = get_current_device()
        if dev and dev.model_family:
            capabilities = capabilities_for_family_gen(
                dev.model_family, dev.generation or "",
            )
    except Exception as exc:
        logger.debug("Could not load device capabilities: %s", exc)

    try:
        ok = write_itunesdb(
            str(ipod_path),
            tracks,
            pc_file_paths=pc_file_paths,
            playlists=playlists,
            smart_playlists=smart_playlists,
            capabilities=capabilities,
            master_playlist_name=master_playlist_name,
            progress_callback=progress_callback,
        )
    except Exception as e:
        logger.exception("Failed to write iTunesDB: %s", e)
        if raise_on_error:
            raise
        return False

    # ── SQLite databases (Nano 5G/6G/7G) ─────────────────────────
    # Write SQLite databases if the device declares uses_sqlite_db OR
    # if the iTunes Library.itlp directory already exists (e.g. Nano 5G
    # where iTunes created the directory but the capability flag is off).
    itlp_dir = os.path.join(str(ipod_path), "iPod_Control", "iTunes", "iTunes Library.itlp")
    has_itlp = os.path.isdir(itlp_dir)
    if (capabilities and capabilities.uses_sqlite_db) or has_itlp:
        if progress_callback is not None:
            progress_callback("Writing SQLite databases")
        logger.info("Writing SQLite databases to iTunes Library.itlp/ "
                    "(uses_sqlite_db=%s, itlp_exists=%s)",
                    capabilities.uses_sqlite_db if capabilities else False,
                    has_itlp)
        try:
            from SQLiteDB_Writer import write_sqlite_databases

            # Extract db_pid from the CDB we just wrote so SQLite databases
            # use the same persistent ID — firmware cross-references both.
            db_pid = 0
            try:
                from ipod_device import resolve_itdb_path
                cdb_path = resolve_itdb_path(str(ipod_path))
                if cdb_path:
                    with open(cdb_path, "rb") as _f:
                        _hdr = _f.read(0x20)
                    if len(_hdr) >= 0x20 and _hdr[:4] == b"mhbd":
                        db_pid = struct.unpack_from('<Q', _hdr, 0x18)[0]
                        logger.debug("Extracted db_pid=%016X from CDB for SQLite", db_pid)
            except Exception as exc:
                logger.warning("Could not extract db_pid from CDB: %s", exc)

            # Get FireWire ID for cbk signing
            firewire_id = None
            try:
                from ipod_device import get_firewire_id
                firewire_id = get_firewire_id(str(ipod_path))
            except Exception as e:
                logger.warning("Could not get FireWire ID for SQLite cbk: %s", e)

            sqlite_ok = write_sqlite_databases(
                ipod_path=str(ipod_path),
                tracks=tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=master_playlist_name,
                db_pid=db_pid,
                capabilities=capabilities,
                firewire_id=firewire_id,
            )
            if not sqlite_ok:
                logger.error("SQLite database write failed")
                if raise_on_error:
                    raise RuntimeError("SQLite database write failed")
                return False
        except Exception as e:
            logger.exception("Failed to write SQLite databases: %s", e)
            if raise_on_error:
                raise
            return False

    return ok
