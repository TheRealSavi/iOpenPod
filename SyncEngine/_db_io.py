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
    - ``play_count_2`` is the transient iPod play delta slot
    - ``recent_playcount`` / ``recent_skipcount`` are the Play Counts deltas
    - ``rating`` may be overridden if the user rated on the iPod
    """
    from iTunesDB_Parser import parse_itunesdb
    from iTunesDB_Parser.playcounts import merge_playcounts, parse_playcounts
    from iTunesDB_Shared.extraction import (
        extract_datasets,
        extract_mhod_strings,
        extract_playlist_extras,
        extract_playlist_item_extras,
        extract_track_extras,
    )
    from iTunesDB_Shared.field_base import filetype_to_string

    empty = {
        "tracks": [],
        "dataset2_standard_playlists": [],
        "dataset3_podcast_playlists": [],
        "dataset5_smart_playlists": [],
    }
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
            t.update(extract_track_extras(children))
            if "filetype" in t:
                t["filetype"] = filetype_to_string(t["filetype"])
            # sample_rate_1 is already converted from 16.16 fixed-point
            # to Hz by the read_transform in mhit_defs.py

        from iTunesDB_Parser.artwork_links import hydrate_track_artwork_refs

        hydrate_track_artwork_refs(tracks, itdb_path)

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
                items = []
                for child in mhip_children:
                    if "data" not in child:
                        continue
                    item = child["data"]
                    item.update(extract_playlist_item_extras(item.get("children", [])))
                    items.append(item)
                pl["items"] = items

        # Keep playlist datasets separate. Dataset 2 and dataset 3 are both
        # MHLP lists, but they have different firmware semantics.
        dataset2_standard_playlists = data.get("mhlp", [])
        dataset3_podcast_playlists = data.get("mhlp_podcast", [])
        dataset5_smart_playlists = data.get("mhlp_smart", [])

        _process_playlist_list(dataset2_standard_playlists)
        _process_playlist_list(dataset3_podcast_playlists)
        _process_playlist_list(dataset5_smart_playlists)

        dataset2_seen_ids: set[int] = {
            int(pl.get("playlist_id", 0) or 0)
            for pl in dataset2_standard_playlists
            if pl.get("playlist_id", 0)
        }

        # Import On-The-Go playlists from OTGPlaylistInfo files.
        # These are device-created playlists stored outside the iTunesDB; we
        # inject them into dataset 2 only, never into dataset 3 or 5.
        from iTunesDB_Parser.otg import load_otg_playlists
        itunes_dir = itdb_path.parent
        otg = load_otg_playlists(str(itunes_dir), tracks)
        for pl in otg:
            playlist_id = int(pl.get("playlist_id", 0) or 0)
            if playlist_id and playlist_id not in dataset2_seen_ids:
                dataset2_seen_ids.add(playlist_id)
                dataset2_standard_playlists.append(pl)

        logger.info(
            "Parsed iPod database: %d tracks, ds2_playlists=%d, ds3_playlists=%d, ds5_playlists=%d",
            len(tracks),
            len(dataset2_standard_playlists),
            len(dataset3_podcast_playlists),
            len(dataset5_smart_playlists),
        )
        return {
            "tracks": tracks,
            "dataset2_standard_playlists": dataset2_standard_playlists,
            "dataset3_podcast_playlists": dataset3_podcast_playlists,
            "dataset5_smart_playlists": dataset5_smart_playlists,
        }
    except Exception as e:
        logger.error("Failed to parse iTunesDB: %s", e)
        return empty


def write_database(
    ipod_path: Path,
    tracks: list[TrackInfo],
    pc_file_paths: dict | None = None,
    playlists: list[PlaylistInfo] | None = None,
    podcast_playlists: list[PlaylistInfo] | None = None,
    smart_playlists: list[PlaylistInfo] | None = None,
    master_playlist_name: str = "iPod",
    master_playlist_id: int | None = None,
    podcast_master_playlist_name: str | None = None,
    podcast_master_playlist_id: int | None = None,
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
        "DB: ds2_playlists=%s, ds3_playlists=%s, ds5_playlists=%s",
        len(playlists) if playlists else 0,
        len(podcast_playlists) if podcast_playlists else 0,
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
            podcast_playlists=podcast_playlists,
            smart_playlists=smart_playlists,
            capabilities=capabilities,
            master_playlist_name=master_playlist_name,
            master_playlist_id=master_playlist_id,
            podcast_master_playlist_name=podcast_master_playlist_name,
            podcast_master_playlist_id=podcast_master_playlist_id,
            progress_callback=progress_callback,
        )
    except Exception as e:
        logger.exception(
            "Database write failed during iTunesDB serialization; output was not committed. Error: %s",
            e,
        )
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

            # SQLite-era devices do not expose MHSD 2/3/5 buckets directly;
            # they use container tables. Today we write dataset-2-style
            # playlists plus dataset-5 smart/category containers. Dataset-3
            # podcast-list rows are intentionally not duplicated into SQLite
            # until we have device samples that show a distinct SQLite analogue.
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


def delete_playcounts_files(ipod_path: Path) -> None:
    """Delete Play Counts (and related) files after committing deltas."""
    itunes_dir = ipod_path / "iPod_Control" / "iTunes"
    for name in ("Play Counts", "iTunesStats", "PlayCounts.plist"):
        path = itunes_dir / name
        if path.exists():
            try:
                path.unlink()
                logger.info("Deleted %s", path)
            except OSError as exc:
                logger.warning("Could not delete %s: %s", path, exc)

    from iTunesDB_Parser.otg import delete_otg_files

    delete_otg_files(str(itunes_dir))


def commit_playcounts_if_needed(ipod_path: Path) -> bool:
    """Merge Play Counts into the database immediately when present."""
    from iTunesDB_Parser.playcounts import parse_playcounts

    pc_path = ipod_path / "iPod_Control" / "iTunes" / "Play Counts"
    entries = parse_playcounts(pc_path)
    if entries is None or not any(entry.has_data for entry in entries):
        return False

    existing = read_existing_database(ipod_path)
    tracks_data = existing.get("tracks", [])
    if not tracks_data:
        return False

    from ._playlist_builder import build_and_evaluate_playlists
    from ._track_conversion import track_dict_to_info

    all_tracks = [track_dict_to_info(t) for t in tracks_data]
    (
        master_name,
        master_playlist_id,
        playlists,
        podcast_master_name,
        podcast_master_playlist_id,
        podcast_playlists,
        smart_playlists,
    ) = build_and_evaluate_playlists(
        tracks_data,
        existing.get("dataset2_standard_playlists", []),
        existing.get("dataset3_podcast_playlists", []),
        existing.get("dataset5_smart_playlists", []),
        all_tracks,
        [],
    )

    if not write_database(
        ipod_path,
        all_tracks,
        playlists=playlists,
        podcast_playlists=podcast_playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
        master_playlist_id=master_playlist_id,
        podcast_master_playlist_name=podcast_master_name,
        podcast_master_playlist_id=podcast_master_playlist_id,
    ):
        return False

    delete_playcounts_files(ipod_path)
    return True
