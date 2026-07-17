"""iPod database read/write helpers — parse existing DB, write final DB.

Extracted from sync_executor.py to keep the orchestrator focused on
sync flow control.
"""

import logging
import os
import struct
from collections.abc import Callable
from pathlib import Path

from iopenpod.device.durability import durable_unlink
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.path_safety import UnsafeDevicePathError, resolve_device_path
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo

logger = logging.getLogger(__name__)


class DatabaseVerificationError(RuntimeError):
    """Raised when a freshly written iPod database fails read-back checks."""


def read_existing_database(
    ipod_path: Path,
    *,
    raise_on_error: bool = False,
) -> dict:
    """Read existing tracks, playlists, and smart playlists from iTunesDB.

    Also reads the Play Counts file (if present) and merges per-track
    deltas into the track dicts.  After merging:
    - ``play_count_1`` / ``skip_count`` are the new cumulative values
    - ``play_count_2`` is the transient iPod play delta slot
    - ``recent_playcount`` / ``recent_skipcount`` are the Play Counts deltas
    - ``rating`` may be overridden if the user rated on the iPod
    """
    from iopenpod.itunesdb_parser import parse_itunesdb
    from iopenpod.itunesdb_parser.playcounts import merge_playcounts, parse_playcounts
    from iopenpod.itunesdb_shared.extraction import (
        extract_datasets,
        extract_mhod_strings,
        extract_playlist_extras,
        extract_playlist_item_extras,
        extract_track_extras,
    )
    from iopenpod.itunesdb_shared.field_base import filetype_to_string

    empty = {
        "tracks": [],
        "dataset2_standard_playlists": [],
        "dataset3_podcast_playlists": [],
        "dataset5_smart_playlists": [],
    }
    from iopenpod.device import resolve_itdb_path
    _resolved = resolve_itdb_path(str(ipod_path))
    itdb_path = Path(_resolved) if _resolved else ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"
    if not itdb_path.exists():
        if raise_on_error:
            raise FileNotFoundError(f"iTunesDB was not found at {itdb_path}")
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

        from iopenpod.itunesdb_parser.artwork_links import hydrate_track_artwork_refs

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
        from iopenpod.itunesdb_parser.otg import load_otg_playlists
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
        if raise_on_error:
            raise
        return empty


def verify_written_database(
    ipod_path: Path,
    *,
    expected_track_count: int,
    case_sensitive_paths: bool | None = None,
) -> None:
    """Reparse a committed database and verify every media reference."""
    from iopenpod.device.filesystem import detect_filesystem_type

    from .ipod_track_paths import expected_ipod_track_file_path

    try:
        parsed = read_existing_database(ipod_path, raise_on_error=True)
    except Exception as exc:
        raise DatabaseVerificationError(
            f"Freshly written iTunesDB could not be reparsed: {exc}"
        ) from exc

    parsed_tracks = parsed.get("tracks", [])
    problems: list[str] = []
    if len(parsed_tracks) != expected_track_count:
        problems.append(
            "track count mismatch "
            f"(expected {expected_track_count}, read back {len(parsed_tracks)})"
        )

    if case_sensitive_paths is None:
        filesystem_type = detect_filesystem_type(ipod_path)
        case_sensitive_paths = filesystem_type == "hfsx"
    ipod_root = ipod_path.resolve()
    seen_media_paths: dict[str, str] = {}
    for track in parsed_tracks:
        title = str(track.get("Title") or "?")
        location = str(track.get("Location") or "").strip()
        if not location:
            problems.append(f"track '{title}' has no Location")
            continue
        media_path = expected_ipod_track_file_path(ipod_path, location)
        if media_path is None:
            problems.append(
                f"track '{title}' has an invalid or outside the iPod media path {location}"
            )
            continue

        resolved_media_path = media_path.resolve()
        try:
            resolved_media_path.relative_to(ipod_root)
        except ValueError:
            problems.append(
                f"track '{title}' references media outside the iPod {location}"
            )
            continue

        media_key = _database_media_path_key(
            resolved_media_path,
            case_sensitive=case_sensitive_paths,
        )
        previous_location = seen_media_paths.get(media_key)
        if previous_location is not None:
            problems.append(
                "duplicate media location "
                f"{location} (already referenced as {previous_location})"
            )
        else:
            seen_media_paths[media_key] = location

        if not resolved_media_path.is_file():
            problems.append(f"track '{title}' references missing media {location}")

    if problems:
        detail = "; ".join(problems[:5])
        if len(problems) > 5:
            detail += f"; and {len(problems) - 5} more problem(s)"
        raise DatabaseVerificationError(
            f"Freshly written iTunesDB failed verification: {detail}"
        )

    logger.info(
        "Verified freshly written iTunesDB: %d tracks and all media paths exist",
        len(parsed_tracks),
    )


def _database_media_path_key(path: Path, *, case_sensitive: bool) -> str:
    """Return a duplicate-comparison key matching the mounted filesystem."""
    key = str(path).replace("\\", "/")
    return key if case_sensitive else key.casefold()


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
    case_sensitive_paths: bool | None = None,
    before_database_replace: Callable[[], None] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> bool:
    """Write tracks to iTunesDB (and ArtworkDB if pc_file_paths provided).

    Automatically detects device capabilities from the centralized store
    and passes them to the writer for db_version, gapless/video filtering,
    and conditional podcast MHSD inclusion.

    For devices with ``uses_sqlite_db`` (Nano 6G/7G), also writes the
    SQLite databases to ``iTunes Library.itlp/``.  The firmware on those
    devices reads the SQLite databases exclusively.
    """
    from iopenpod.itunesdb_writer import write_itunesdb

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
        from iopenpod.device import (
            capabilities_for_family_gen,
            get_current_device_for_path,
        )
        dev = get_current_device_for_path(str(ipod_path))
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
            before_database_replace=before_database_replace,
            before_device_mutation=before_device_mutation,
        )
    except Exception as e:
        logger.exception(
            "Database write failed during iTunesDB serialization; output was not committed. Error: %s",
            e,
        )
        if raise_on_error:
            raise
        return False

    if not ok:
        return False

    try:
        verify_written_database(
            ipod_path,
            expected_track_count=len(tracks),
            case_sensitive_paths=case_sensitive_paths,
        )
    except DatabaseVerificationError as exc:
        logger.error("Database read-back verification failed: %s", exc)
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
            from iopenpod.sqlitedb_writer import write_sqlite_databases

            # Extract db_pid from the CDB we just wrote so SQLite databases
            # use the same persistent ID — firmware cross-references both.
            db_pid = 0
            try:
                from iopenpod.device import resolve_itdb_path
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
                from iopenpod.device import get_firewire_id
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
                before_device_mutation=before_device_mutation,
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


def delete_playcounts_files(
    ipod_path: Path,
    *,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    """Delete Play Counts (and related) files after committing deltas."""
    relative_dir = Path("iPod_Control") / "iTunes"
    for name in (
        "Play Counts",
        "iTunesStats",
        "PlayCounts.plist",
        "OTGPlaylistInfo",
    ):
        try:
            if before_device_mutation is not None:
                before_device_mutation()
            path = resolve_device_path(
                ipod_path,
                relative_dir / name,
                allowed_subtree=relative_dir,
            )
            durable_unlink(path, missing_ok=True)
        except (OSError, UnsafeDevicePathError) as exc:
            raise DeviceWriteSafetyError(
                "The iPod database was committed, but its device-generated "
                f"sync state could not be cleared ({name}): {exc}"
            ) from exc
        logger.info("Cleared device-generated sync state %s", path)


def commit_playcounts_if_needed(ipod_path: Path) -> bool:
    """Merge Play Counts into the database immediately when present."""
    from iopenpod.itunesdb_parser.playcounts import parse_playcounts

    pc_path = ipod_path / "iPod_Control" / "iTunes" / "Play Counts"
    entries = parse_playcounts(pc_path)
    if entries is None or not any(entry.has_data for entry in entries):
        return False

    profile = inspect_device_write_readiness(ipod_path)
    with DeviceWriteGuard(
        ipod_path,
        volume_key=volume_lock_key(profile),
    ) as write_guard:
        return _commit_playcounts_guarded(
            ipod_path,
            filesystem_profile=profile,
            write_guard=write_guard,
        )


def _commit_playcounts_guarded(
    ipod_path: Path,
    *,
    filesystem_profile: FilesystemProfile,
    write_guard: DeviceWriteGuard,
) -> bool:
    """Commit play deltas while one verified device write session is held."""

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
    )

    from .database_commit import DatabaseCommitPayload, write_database_commit

    if not write_database_commit(
        ipod_path,
        DatabaseCommitPayload(
            all_tracks=all_tracks,
            playlists=playlists,
            podcast_playlists=podcast_playlists,
            smart_playlists=smart_playlists,
            master_playlist_name=master_name,
            master_playlist_id=master_playlist_id,
            podcast_master_playlist_name=podcast_master_name,
            podcast_master_playlist_id=podcast_master_playlist_id,
        ),
        protect_itunes=True,
        write_guard=write_guard,
        filesystem_profile=filesystem_profile,
    ):
        return False

    def _revalidate() -> None:
        nonlocal filesystem_profile
        filesystem_profile = revalidate_device_write_readiness(filesystem_profile)

    delete_playcounts_files(
        ipod_path,
        before_device_mutation=_revalidate,
    )
    return True
