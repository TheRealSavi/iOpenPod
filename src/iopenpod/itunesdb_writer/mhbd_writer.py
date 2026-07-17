"""MHBD Writer — Write complete iTunesDB database files.

This is the top-level writer that assembles all components into
a valid iTunesDB (or iTunesCDB for Nano 5G+) file.

Dataset write order (matches libgpod):
  mhbd (database header, 244 bytes)
    mhsd type 1 (tracks dataset)
      mhlt (track list)
        mhit (track) x N
          mhod (string) x M
    mhsd type 3 (playlist dataset with podcast-aware grouping)
      mhlp (playlist list) — often mirrors type 2, but remains distinct
    mhsd type 2 (playlists dataset)
      mhlp (playlist list)
        mhyp (master playlist) — REQUIRED, always first
          mhod types 52/53 (library indices)
          mhip (track ref) x N
        mhyp (user playlist) x M
    mhsd type 4 (albums dataset)
      mhla (album list)
        mhia (album item) x N
    mhsd type 8 (artist list)
      mhli (artist list)
        mhii (artist item) x N
          mhod type 300 (artist name)
    mhsd type 6 (empty stub — mhlt with 0 children)
    mhsd type 10 (empty stub — mhlt with 0 children)
    mhsd type 5 (smart playlists dataset)
      mhlp (smart playlist list)

MHBD header layout (MHBD_HEADER_SIZE = 244 bytes):
    +0x00: 'mhbd' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — entire file size
    +0x0C: unk1 (4B) — always 1
    +0x10: version (4B) — 0x4F
    +0x14: children_count (4B) — 5
    +0x18: database_id (8B)
    +0x20: platform (2B) — 1=Mac, 2=Windows
    +0x22: unk_0x22 (2B) — ~611
    +0x24: db_id_2 (8B) — secondary ID (written in every MHIT)
    +0x2C: unk_0x2c (4B)
    +0x30: hashing_scheme (2B) — 0=none, 1=hash58
    +0x32: unk_0x32 (20B) — zeroed before hash58
    +0x46: language (2B)
    +0x48: lib_persistent_id (8B)
    +0x50: unk_0x50 (4B)
    +0x54: unk_0x54 (4B)
    +0x58: hash58 (20B)
    +0x6C: timezone_offset (4B signed)
    +0x70: unk_0x70 (2B)
    +0x72: hash72 (46B)
    +0xA0: audio_language (2B)
    +0xA2: subtitle_language (2B)

Cross-referenced against:
  - src/iopenpod/itunesdb_parser/mhbd_parser.py parse_db()
  - libgpod itdb_itunesdb.c: mk_mhbd() / parse_mhbd()
"""

import logging
import os
import random
import shutil
import stat
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import replace as _dc_replace
from pathlib import Path

from iopenpod.device import ChecksumType, DeviceCapabilities, detect_checksum_type
from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.filesystem import (
    detect_filesystem_type,
    resolve_itunesdb_platform,
)
from iopenpod.device.path_safety import resolve_device_path
from iopenpod.device.storage_safety import (
    allocated_size,
    effective_max_file_size_bytes,
    require_file_size_supported,
)
from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.device.write_readiness import inspect_device_write_readiness
from iopenpod.itunesdb_shared.album_identity import album_identity_from_track
from iopenpod.itunesdb_shared.field_base import (
    read_fields,
    write_fields,
    write_generic_header,
)
from iopenpod.itunesdb_shared.mhbd_defs import (
    MHBD_HEADER_SIZE,
    MHBD_OFFSET_HASHING_SCHEME,
)

from .hash58 import write_hash58
from .hashab import write_hashab
from .mhit_writer import TrackInfo
from .mhla_writer import write_mhla
from .mhli_writer import write_mhli
from .mhlp_writer import write_mhlp_smart, write_mhlp_with_playlists
from .mhlt_writer import write_mhlt
from .mhsd_writer import (
    write_mhsd_empty_stub,
    write_mhsd_smart_type5,
    write_mhsd_type1,
    write_mhsd_type2,
    write_mhsd_type3,
    write_mhsd_type4,
    write_mhsd_type8,
)
from .mhyp_writer import PlaylistInfo, generate_playlist_id

logger = logging.getLogger(__name__)

# Default database version — 0x4F (79) works for iPod Classic / Nano 3G+.
# For older devices, callers should pass `db_version` from
# ``iopenpod.device.DeviceCapabilities.db_version``.
DATABASE_VERSION_DEFAULT = 0x4F


def _maybe_decompress_cdb(itdb_data: bytes) -> bytes:
    """Decompress an iTunesCDB payload if the compressed indicator is set.

    Returns the full (header + decompressed children) bytes if the data
    is a compressed iTunesCDB, or the original bytes unchanged otherwise.
    """
    hdr_len = struct.unpack('<I', itdb_data[4:8])[0]
    if (len(itdb_data) > hdr_len + 2
            and struct.unpack('<H', itdb_data[0xA8:0xAA])[0] == 1
            and itdb_data[hdr_len] == 0x78):
        try:
            decompressed = zlib.decompress(itdb_data[hdr_len:])
            return itdb_data[:hdr_len] + decompressed
        except zlib.error:
            pass
    return itdb_data


def _valid_itunesdb_platform(itdb_data: bytes | None) -> int | None:
    """Read a valid MHBD platform flag without trusting other header fields."""
    if not itdb_data or len(itdb_data) < 0x22 or itdb_data[:4] != b"mhbd":
        return None
    platform = struct.unpack_from("<H", itdb_data, 0x20)[0]
    return platform if platform in (1, 2) else None


def _validate_existing_itunesdb(itdb_data: bytes, path: str) -> None:
    """Reject an existing on-device database that is unsafe to rewrite from."""
    if len(itdb_data) < MHBD_HEADER_SIZE or itdb_data[:4] != b"mhbd":
        raise RuntimeError(
            f"The existing iPod database is truncated or malformed: {path}. "
            "iOpenPod stopped before replacing it."
        )
    header_len = struct.unpack_from("<I", itdb_data, 4)[0]
    total_len = struct.unpack_from("<I", itdb_data, 8)[0]
    if (
        header_len < MHBD_HEADER_SIZE
        or header_len > total_len
        or total_len > len(itdb_data)
    ):
        raise RuntimeError(
            f"The existing iPod database has invalid size fields: {path}. "
            "iOpenPod stopped before replacing it."
        )
    compressed = struct.unpack_from("<H", itdb_data, 0xA8)[0] == 1
    if compressed:
        try:
            zlib.decompress(itdb_data[header_len:total_len])
        except zlib.error as exc:
            raise RuntimeError(
                f"The existing compressed iPod database is corrupt: {path}. "
                "iOpenPod stopped before replacing it."
            ) from exc


def extract_db_info(itdb_path: str) -> dict:
    """
    Extract useful information from an existing iTunesDB.

    This can be used to get:
    - db_id: To preserve identity across rewrites
    - hashing_scheme: What hash type is used
    - hash58/hash72: The actual hash values

    All keys use canonical ``field_defs`` names (e.g. ``'db_id_2'`` not
    ``'db_id_2'``, ``'timezone_offset'`` not ``'timezone'``).

    Args:
        itdb_path: Path to iTunesDB file

    Returns:
        Dictionary with extracted information (field_defs key names)
    """
    with open(itdb_path, 'rb') as f:
        data = f.read(MHBD_HEADER_SIZE)

    if data[:4] != b'mhbd':
        raise ValueError(f"Not an iTunesDB file: {itdb_path}")

    header_length = struct.unpack_from('<I', data, 4)[0]
    return read_fields(data, 0, 'mhbd', header_length)


def extract_preserved_mhsd_blobs(itdb_data: bytes) -> list[bytes]:
    """Extract raw MHSD blobs for dataset types we don't generate.

    iTunes 9+ writes additional MHSD children for Genius features
    (types 6-10).  We now generate types 6, 8, and 10 ourselves
    (empty stubs for 6/10, artist list for 8), so we only preserve
    types we don't generate: 7 and 9 (Genius Chill).

    Args:
        itdb_data: Complete original iTunesDB file bytes.

    Returns:
        List of raw MHSD byte blobs for dataset types we don't generate,
        in the order they appeared in the original database.
    """
    if len(itdb_data) < 24 or itdb_data[:4] != b'mhbd':
        return []

    header_length = struct.unpack('<I', itdb_data[4:8])[0]

    # Decompress iTunesCDB payload if needed — the MHSD children are in
    # the zlib-compressed payload, so we can't walk them without this.
    itdb_data = _maybe_decompress_cdb(itdb_data)

    children_count = struct.unpack('<I', itdb_data[0x14:0x18])[0]

    # Types we now generate ourselves — don't preserve these
    GENERATED_TYPES = {1, 2, 3, 4, 5, 6, 8, 10}

    blobs: list[bytes] = []
    offset = header_length

    for _ in range(children_count):
        if offset + 16 > len(itdb_data):
            break
        magic = itdb_data[offset:offset + 4]
        if magic != b'mhsd':
            break
        mhsd_total = struct.unpack('<I', itdb_data[offset + 8:offset + 12])[0]
        mhsd_type = struct.unpack('<I', itdb_data[offset + 12:offset + 16])[0]

        if mhsd_type not in GENERATED_TYPES:
            blob = itdb_data[offset:offset + mhsd_total]
            blobs.append(bytes(blob))
            logger.debug("Preserved MHSD type %d blob (%d bytes)", mhsd_type, mhsd_total)

        offset += mhsd_total

    if blobs:
        logger.info("Preserved %d extra MHSD blob(s) from existing database.", len(blobs))
    return blobs


def generate_database_id() -> int:
    """Generate a random 64-bit database ID."""
    return random.getrandbits(64)


def write_mhbd(
    tracks: list[TrackInfo],
    db_id: int | None = None,
    language: str = "en",
    reference_info: dict | None = None,
    playlists_type2: list[PlaylistInfo] | None = None,
    playlists_type3: list[PlaylistInfo] | None = None,
    playlists_type5: list[PlaylistInfo] | None = None,
    preserved_mhsd_blobs: list[bytes] | None = None,
    capabilities: DeviceCapabilities | None = None,
    master_playlist_name: str = "iPod",
    master_playlist_id: int | None = None,
    podcast_master_playlist_name: str | None = None,
    podcast_master_playlist_id: int | None = None,
    *,
    platform: int | None = None,
) -> bytes:
    """
    Write a complete iTunesDB database.

    Args:
        tracks: List of TrackInfo objects to include
        db_id: Database ID (generated if not provided)
        language: 2-letter language code
        reference_info: Dict from extract_db_info() to copy device-specific fields
        playlists_type2: List of PlaylistInfo for user playlists (dataset 2).
                   Master playlist is auto-generated; does NOT belong in this list.
        playlists_type3: List of PlaylistInfo for podcast-list playlists
                         (dataset 3). If None, dataset 2 playlists are cloned
                         for libgpod-compatible new-database output. Passing
                         an empty list is meaningful: write dataset 3 with
                         only its generated master playlist.
        playlists_type5: List of PlaylistInfo for dataset 5 smart playlists
                         (iPod browsing categories like Music, Movies, etc.)
        preserved_mhsd_blobs: Raw MHSD byte blobs (types 6+) extracted from
                              an existing database via extract_preserved_mhsd_blobs().
                              Appended verbatim after the 5 standard datasets to
                              preserve Genius and other iTunes-generated data.
        capabilities: Device capabilities from ``ipod_device``.  When provided,
                      ``db_version`` and ``supports_podcast`` are respected.
        master_playlist_name: Display name for the dataset 2 master playlist.
        master_playlist_id: Existing dataset 2 master playlist ID, if any.
        podcast_master_playlist_name: Display name for the dataset 3 master
                                      playlist. Defaults to master_playlist_name.
        podcast_master_playlist_id: Existing dataset 3 master playlist ID, if any.
        platform: Explicit MHBD OS flag (1=Mac, 2=Windows). When omitted,
                  preserves a valid value from ``reference_info``.

    Returns:
        Complete iTunesDB file content as bytes
    """
    # Determine database ID, passed, preserved, or random
    if db_id is None:
        if reference_info and 'db_id' in reference_info:
            db_id = reference_info['db_id']
        else:
            db_id = generate_database_id()

    # Generate db_id_2 early - needed for both the MHBD header AND every MHIT, preserved or random.
    # Field is named 'db_id_2' in the shared field definitions (offset 0x24).
    if reference_info and 'db_id_2' in reference_info:
        db_id_2 = reference_info['db_id_2']
    else:
        db_id_2 = random.getrandbits(64)

    # Build album list first to get album IDs for tracks (Type 4 dataset)
    global_id_start_index = 1

    mhla_data, album_map, last_id = write_mhla(tracks, starting_index_for_album_id=global_id_start_index)
    mhsd_type4 = write_mhsd_type4(mhla_data)

    # Build artist list to get artist IDs for tracks (Type 8 dataset)
    mhli_data, artist_map, last_id = write_mhli(tracks, starting_index_for_artist_id=last_id + 1)
    mhsd_type8 = write_mhsd_type8(mhli_data)

    # Build composer ID map (no dataset — composers don't have their own
    # MHSD type, but the iPod firmware uses composer_id in mhit for
    # grouping and sorting).
    composer_map: dict[str, int] = {}  # lowercase composer → composer_id
    composer_id = last_id + 1
    for track in tracks:
        composer_name = track.composer or ""
        if not composer_name:
            continue
        key = composer_name.lower()
        if key not in composer_map:
            composer_map[key] = composer_id
            composer_id += 1
    last_id = composer_id - 1 if composer_map else last_id

    # Assign album_id, artist_id, and composer_id to each track
    for track in tracks:
        if not track.album_id:
            identity = album_identity_from_track(track)
            album_name = identity.album or ""
            album_artist = identity.album_artist or identity.artist or ""
            key = (album_name, album_artist)
            track.album_id = album_map.get(key, 0)

        # Artist ID from the artist list (artist_map is keyed by lowercase)
        artist_name = track.artist or ""
        if artist_name:
            track.artist_id = artist_map.get(artist_name.lower(), 0)

        # Composer ID from the composer map
        composer_name = track.composer or ""
        if composer_name:
            track.composer_id = composer_map.get(composer_name.lower(), 0)

    # ── Compute db_version early — needed for MHIT header sizing ────
    ref_version = reference_info.get('version', 0) if reference_info else 0
    cap_version = capabilities.db_version if capabilities else 0
    if cap_version:
        # Device identified — use the higher of reference and capability
        db_version = max(ref_version, cap_version)
    elif ref_version:
        # Device unknown — preserve the existing database's version
        db_version = ref_version
    else:
        # No reference, no capabilities — use safe default
        db_version = DATABASE_VERSION_DEFAULT
    logger.debug("Using db_version=0x%X (ref=0x%X, cap=0x%X, default=0x%X)",
                 db_version, ref_version, cap_version, DATABASE_VERSION_DEFAULT)

    # Build track list (Type 1 dataset)
    # This also returns next_track_id which tells us track IDs used

    mhlt_data, next_track_id = write_mhlt(tracks, db_id_2=db_id_2, capabilities=capabilities,
                                          db_version=db_version, start_track_id=last_id + 1)
    mhsd_type1 = write_mhsd_type1(mhlt_data)

    # Collect all track IDs for the master playlist
    # Track IDs are sequential starting from 1
    track_ids = list(range(last_id + 1, next_track_id))

    # Build db_track_id → sequential track_id map so playlists can reference
    # tracks by their 32-bit MHIT trackID (not 64-bit db_track_id).
    # The sync executor stores db_track_ids in PlaylistInfo.track_ids because
    # db_track_ids are the stable identifier, but MHIP entries need 32-bit IDs.
    db_track_id_to_track_id: dict[int, int] = {}
    for i, track in enumerate(tracks):
        if track.db_track_id:
            db_track_id_to_track_id[track.db_track_id] = i + last_id + 1

    # Remap playlist track_ids from 64-bit db_track_id → 32-bit sequential track_id.
    #
    # PlaylistInfo.track_ids stores db_track_ids (the stable cross-session identifier),
    # but MHIP entries in the iTunesDB need sequential track IDs assigned by
    # write_mhlt.  We build new PlaylistInfo copies with remapped IDs instead
    # of mutating the caller's objects — if write_mhbd() were retried (e.g.
    # after an I/O error) the original db_track_id-based track_ids must still be intact.
    def _remap_playlist(pl: PlaylistInfo) -> PlaylistInfo:
        """Return a copy of pl with the db_track_ids translated to track IDs."""
        new_ids: list[int] = []
        new_meta: list | None = [] if pl.item_metadata is not None else None

        meta = pl.item_metadata  # capture for type narrowing
        for i, db_track_id in enumerate(pl.track_ids):
            track_id = db_track_id_to_track_id.get(db_track_id)
            if track_id is None:
                continue  # track not in this database — skip
            new_ids.append(track_id)
            if new_meta is not None and meta is not None and i < len(meta):
                new_meta.append(meta[i])

        if new_meta is not None and len(new_meta) != len(new_ids):
            new_meta = None

        return _dc_replace(pl, track_ids=new_ids, item_metadata=new_meta)

    # Build playlist list WITH master playlist (Type 2 dataset)
    # The master playlist is REQUIRED and must reference ALL tracks
    # Pass tracks so master playlist can generate library index MHODs (type 52/53)
    #
    remapped_playlists_type2 = [_remap_playlist(pl) for pl in (playlists_type2 or [])]
    if master_playlist_id is None:
        master_playlist_id = generate_playlist_id()
    mhsd_type2_data = write_mhlp_with_playlists(
        track_ids, playlists=remapped_playlists_type2,
        tracks=tracks, db_id_2=db_id_2, capabilities=capabilities,
        master_playlist_name=master_playlist_name,
        master_playlist_id=master_playlist_id,
    )
    mhsd_type2 = write_mhsd_type2(mhsd_type2_data)

    # Build podcast list (Type 3 dataset). If an explicit list is supplied,
    # preserve that dataset independently. Otherwise keep the historical
    # libgpod-compatible behavior of cloning dataset 2 into dataset 3. The
    # clone path is only for new/default writes; it is not evidence that parsed
    # dataset-2 and dataset-3 rows are interchangeable.

    # Pre-podcast devices (iPod 1G-3G, Mini 1G-2G, Shuffle 1G-2G)
    # don't understand type 3; skip it when capabilities say so.
    include_podcasts = True
    if capabilities is not None and not capabilities.supports_podcast:
        include_podcasts = False

    if include_podcasts:
        source_playlists_type3 = (
            playlists_type2 if playlists_type3 is None else playlists_type3
        )
        remapped_playlists_type3 = [
            _remap_playlist(pl) for pl in (source_playlists_type3 or [])
        ]
        if podcast_master_playlist_id is None:
            podcast_master_playlist_id = generate_playlist_id()
        # Build track_id → album map for podcast grouping.
        # Sequential track IDs start after last_id (same as track_ids range).
        track_album_map: dict[int, str] = {}
        for i, track in enumerate(tracks):
            seq_id = i + last_id + 1
            track_album_map[seq_id] = track.album or ""

        from .mhlp_writer import write_mhlp_with_playlists_type3
        mhsd_type3_data = write_mhlp_with_playlists_type3(
            track_ids, playlists=remapped_playlists_type3,
            db_id_2=db_id_2, track_album_map=track_album_map,
            tracks=tracks, capabilities=capabilities,
            master_playlist_name=podcast_master_playlist_name or master_playlist_name,
            next_mhip_id_start=next_track_id,
            master_playlist_id=podcast_master_playlist_id,
        )
        mhsd_type3 = write_mhsd_type3(mhsd_type3_data)
    else:
        mhsd_type3 = b''

    # Build smart playlist list (Type 5 dataset) — same non-mutating remap
    remapped_playlists_type5 = [_remap_playlist(pl) for pl in (playlists_type5 or [])]
    mhsd_type5_data = write_mhlp_smart(remapped_playlists_type5, db_id_2=db_id_2)
    mhsd_type5 = write_mhsd_smart_type5(mhsd_type5_data)

    mhsd_type6 = write_mhsd_empty_stub(6)
    mhsd_type10 = write_mhsd_empty_stub(10)

    # Concatenate all datasets
    #
    # Default order matches libgpod: Type 1, 3, 2, 4, 8, 6, 10, 5
    #   - Type 3 MUST appear between types 1 and 2 for podcast support
    #   - Type 1 MUST be first — older iPod firmware (iPod 5G, Nano 1G-2G)
    #     may assume dataset[0] is the track list.
    #   - Types 8, 6, 10 come between albums (4) and smart playlists (5).
    #
    # When a reference database is available, we match write only those types.
    # For example, iTunes on Nano 6G writes only [4,8,1,3,5]
    # (no playlist type 2 or empty stubs 6/10).  Including types the
    # firmware doesn't expect can cause it to reject or mis-parse the
    # database.  We still keep the libgpod order to stay compatible
    # with devices where no reference is available.

    # Determine which MHSD types the reference database uses (if any)
    ref_types: set[int] | None = None
    ref_order: list[int] | None = None
    if reference_info and 'mhsd_types' in reference_info:
        rt = reference_info['mhsd_types']
        # Only use ref_types if extraction found meaningful data (at least type 1)
        if rt and 1 in rt:
            ref_types = rt
            ref_order = reference_info.get('mhsd_order')
        logger.debug("Reference MHSD types: %s (order: %s)",
                     sorted(ref_types) if ref_types else "none (fallback to all)",
                     ref_order if ref_order else "default")

    legacy_excluded_types: set[int] = set()
    if capabilities is not None and capabilities.db_version <= 0x19:
        # Types 6, 8, and 10 are newer generated browsing/stub datasets.
        # They are useful on Classic/Nano 3G+ era databases, but older
        # firmware can treat them as a malformed library. Strip them even
        # when a previous iOpenPod write already introduced them.
        legacy_excluded_types = {6, 8, 10}

    required_ref_types: set[int] = set()
    if ref_types is not None:
        # A usable binary iTunesDB needs a track list plus whichever playlist
        # universe the reference database already used. MHSD type 3 devices
        # still need the regular type 2 playlist list as a companion; otherwise
        # creating a user playlist can leave only the podcast-aware mirror.
        # Do not invent newer browsing datasets here: older firmware can reject
        # unfamiliar MHSDs even though iOpenPod's parser can read them back.
        required_ref_types.add(1)
        needs_regular_playlist_dataset = False
        if 2 in ref_types:
            required_ref_types.add(2)
            needs_regular_playlist_dataset = True
        if include_podcasts and 3 in ref_types:
            required_ref_types.add(3)
            needs_regular_playlist_dataset = True
        if needs_regular_playlist_dataset:
            required_ref_types.add(2)
        if not required_ref_types.intersection({2, 3}):
            required_ref_types.add(2)

    # Build the candidate datasets in priority order
    # Each entry: (type_number, data_bytes, required_flag)
    # When ref_types is available, only include types that are present in it.
    # Otherwise, include all types (libgpod-compatible default).

    def _include(dtype: int, required: bool = False) -> bool:
        if dtype in legacy_excluded_types:
            return False
        if required:
            return True
        if ref_types is None:
            return True  # no reference → include everything
        return dtype in ref_types

    # Map type numbers to their data blobs
    type_to_data: dict[int, bytes] = {
        1: mhsd_type1,
        2: mhsd_type2,
        3: mhsd_type3 if (include_podcasts and mhsd_type3) else b'',
        4: mhsd_type4,
        5: mhsd_type5,
        6: mhsd_type6,
        8: mhsd_type8,
        10: mhsd_type10,
    }

    # Assemble datasets — use reference order if available, else libgpod order
    dataset_entries: list[tuple[int, bytes]] = []
    if ref_order:
        # Follow the exact order from the reference database
        inserted_required_type2 = False
        for dtype in ref_order:
            if dtype not in type_to_data:
                continue
            # Type 3 (podcasts) requires include_podcasts flag
            if dtype == 3 and not include_podcasts:
                continue
            if _include(dtype, required=(dtype in required_ref_types)):
                data = type_to_data[dtype]
                if data:
                    dataset_entries.append((dtype, data))
                    if (
                        dtype == 3
                        and 2 in required_ref_types
                        and ref_types is not None
                        and 2 not in ref_types
                        and not inserted_required_type2
                    ):
                        dataset_entries.append((2, type_to_data[2]))
                        inserted_required_type2 = True
        # Add any required core types that weren't in the reference order.
        for dtype in (1, 3, 2):
            if dtype not in required_ref_types:
                continue
            if not any(t == dtype for t, _ in dataset_entries):
                dataset_entries.append((dtype, type_to_data[dtype]))
    else:
        # Default libgpod order: 1, 3, 2, 4, 8, 6, 10, 5
        dataset_entries.append((1, mhsd_type1))  # always required
        if include_podcasts and _include(3):
            dataset_entries.append((3, mhsd_type3))
        if _include(2):
            dataset_entries.append((2, mhsd_type2))
        dataset_entries.append((4, mhsd_type4))  # always required
        if _include(8):
            dataset_entries.append((8, mhsd_type8))
        if _include(6):
            dataset_entries.append((6, mhsd_type6))
        if _include(10):
            dataset_entries.append((10, mhsd_type10))
        if _include(5):
            dataset_entries.append((5, mhsd_type5))

    all_datasets = b''.join(data for _, data in dataset_entries)
    child_count = len(dataset_entries)
    logger.debug("Writing %d MHSD datasets: %s", child_count, [t for t, _ in dataset_entries])

    # Append preserved MHSD blobs from original database (Type 7 and 9).
    extra_blobs = preserved_mhsd_blobs or []
    for blob in extra_blobs:
        all_datasets += blob
    child_count += len(extra_blobs)

    # Total file length
    total_length = MHBD_HEADER_SIZE + len(all_datasets)

    # ── Compute all field values before writing ──────────────────────

    # +0x0C: compressed — 2 for devices with iTunesCDB, 1 otherwise
    compressed = 2 if (capabilities and capabilities.supports_compressed_db) else 1

    # +0x10: Version — already computed above (before MHLT build)

    # +0x32: unk0x32 — preserve from reference (libgpod does this)
    unk0x32 = b'\x00' * 20
    if reference_info and 'unk0x32' in reference_info:
        raw = reference_info['unk0x32']
        if isinstance(raw, (bytes, bytearray)) and len(raw) == 20:
            unk0x32 = bytes(raw)

    # +0x46: Language ID (2 bytes, e.g. "en")
    if reference_info and 'language' in reference_info:
        lang_val = reference_info['language']
        if isinstance(lang_val, str):
            lang_val = lang_val.encode('utf-8')[:2].ljust(2, b'\x00')
    else:
        lang_val = language.encode('utf-8')[:2].ljust(2, b'\x00')

    # +0x48: Library Persistent ID — preserve the original device/library ID
    # so it continues to match iTunesPrefs and the device's historical owner.
    if reference_info and reference_info.get('db_persistent_id'):
        lib_pid = reference_info['db_persistent_id']
    else:
        lib_pid = db_id

    # +0x6C: timezone_offset (signed)
    if reference_info and 'timezone_offset' in reference_info:
        tz_offset = reference_info['timezone_offset']
    else:
        tz_offset = -time.altzone if time.daylight else -time.timezone

    # +0x70: hash_type_indicator — HASHAB→4, HASH72→2, default→0
    if reference_info:
        hash_type_ind = reference_info.get('hash_type_indicator', 0)
    elif capabilities:
        _ck_to_ind = {ChecksumType.HASHAB: 4, ChecksumType.HASH72: 2}
        hash_type_ind = _ck_to_ind.get(capabilities.checksum, 0)
    else:
        hash_type_ind = 0

    # ── Build the header using shared field definitions ──────────────

    platform_flag = platform
    if platform_flag not in (1, 2):
        platform_flag = reference_info.get('platform', 2) if reference_info else 2
    if platform_flag not in (1, 2):
        platform_flag = 2

    header = bytearray(MHBD_HEADER_SIZE)
    write_generic_header(header, 0, b'mhbd', MHBD_HEADER_SIZE, total_length)

    values: dict = {
        'compressed': compressed,
        'version': db_version,
        'child_count': child_count,
        'db_id': db_id,
        'platform': platform_flag,
        'unk0x22': reference_info.get('unk0x22', 611) if reference_info else 611,
        'db_id_2': db_id_2,
        'unk0x2c': 0,
        'hashing_scheme': 0,  # write_itunesdb() patches after checksum
        'unk0x32': unk0x32,
        'language': lang_val,
        'db_persistent_id': lib_pid,
        'unk0x50': reference_info.get('unk0x50', 1) if reference_info else 1,
        'unk0x54': reference_info.get('unk0x54', 15) if reference_info else 15,
        # hash58, hash72 left as defaults (zeros) — filled by write_itunesdb
        'timezone_offset': tz_offset,
        'hash_type_indicator': hash_type_ind,
    }

    # Extended fields — preserved from reference if available
    if reference_info:
        for key in ('audio_language', 'subtitle_language',
                    'unk0xa4', 'unk0xa6', 'cdb_flag'):
            if key in reference_info:
                values[key] = reference_info[key]

    write_fields(header, 0, 'mhbd', values, MHBD_HEADER_SIZE)

    return bytes(header) + all_datasets


def _run_before_mutation(callback: Callable[[], None] | None) -> None:
    if callback is not None:
        callback()


def _cleanup_device_temp(
    path: str | os.PathLike[str],
    *,
    before_device_mutation: Callable[[], None] | None,
) -> None:
    try:
        _run_before_mutation(before_device_mutation)
        durable_unlink(Path(path), missing_ok=True)
    except Exception as exc:
        logger.warning("Could not safely remove temporary device file %s: %s", path, exc)


def _copy_device_file_durably(
    source: str,
    target: str,
    *,
    before_device_mutation: Callable[[], None] | None,
) -> None:
    """Copy a device file through a flushed sibling and atomic replacement."""
    _run_before_mutation(before_device_mutation)
    before = os.stat(source)
    temp_path, temp_file = open_unique_sibling_temp(target, mode="wb")
    try:
        with temp_file as dst:
            with open(source, "rb") as src:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                flush_written_file(dst)
        after = os.stat(source)
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_dev,
            before.st_ino,
        ) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_dev,
            after.st_ino,
        ):
            raise RuntimeError(f"Source changed while backing up {source}")
        _run_before_mutation(before_device_mutation)
        durable_replace(temp_path, target)
    except Exception:
        _cleanup_device_temp(
            temp_path,
            before_device_mutation=before_device_mutation,
        )
        raise


def _database_filename_for_capabilities(
    capabilities: DeviceCapabilities | None,
) -> str | None:
    if capabilities is None:
        return None
    return "iTunesCDB" if capabilities.supports_compressed_db else "iTunesDB"


def _preflight_database_install(
    ipod_path: str,
    itdb_path: str,
    database_size: int,
    *,
    capabilities: DeviceCapabilities | None,
    backup_sources: tuple[str | None, ...] = (),
) -> None:
    """Enforce firmware, filesystem, and staging-space limits before mutation."""
    profile = inspect_device_write_readiness(ipod_path)
    firmware_limit = (
        int(capabilities.max_database_bytes or 0)
        if capabilities is not None
        else None
    )
    maximum = effective_max_file_size_bytes(
        profile.max_file_size_bytes,
        firmware_limit,
    )
    require_file_size_supported(
        database_size,
        max_file_size_bytes=maximum,
        display_name=os.path.basename(itdb_path) or "iTunes database",
    )

    required_free = allocated_size(
        database_size,
        profile.allocation_unit_size,
    )
    seen_sources: set[str] = set()
    for source in backup_sources:
        if not source:
            continue
        source_key = os.path.normcase(os.path.realpath(source))
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        try:
            source_stat = os.stat(source)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DeviceWriteSafetyError(
                "Could not verify space needed to back up the existing iPod "
                f"database: {exc}"
            ) from exc
        required_free += allocated_size(
            source_stat.st_size,
            profile.allocation_unit_size,
        )

    try:
        free_bytes = int(shutil.disk_usage(Path(itdb_path).parent).free)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not verify iPod free space before writing the database: {exc}"
        ) from exc
    if free_bytes < required_free:
        raise DeviceWriteSafetyError(
            "The iPod does not have enough free space to stage and safely "
            "commit its database. "
            f"At least {required_free:,} bytes are required, but only "
            f"{free_bytes:,} bytes are available. iOpenPod stopped before "
            "replacing the database."
        )


def _resolve_existing_itdb_for_write(
    ipod_path: str,
    *,
    preferred_filename: str | None,
) -> str | None:
    """Select one on-disk DB without consulting mutable device selection."""
    filenames = (
        (preferred_filename, "iTunesDB" if preferred_filename == "iTunesCDB" else "iTunesCDB")
        if preferred_filename is not None
        else ("iTunesCDB", "iTunesDB")
    )
    paths = [
        resolve_device_path(
            ipod_path,
            os.path.join("iPod_Control", "iTunes", filename),
            allowed_subtree=os.path.join("iPod_Control", "iTunes"),
        )
        for filename in filenames
    ]
    existing: list[str] = []
    for path in paths:
        try:
            metadata = path.stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"iPod database path is not a regular file: {path}")
        existing.append(str(path))
        if metadata.st_size > 0:
            return str(path)
    return existing[0] if existing else None


def write_itunesdb(
    ipod_path: str,
    tracks: list[TrackInfo],
    db_id: int | None = None,
    backup: bool = True,
    force_checksum: ChecksumType | None = None,
    firewire_id: bytes | None = None,
    reference_itdb_path: str | None = None,
    pc_file_paths: dict | None = None,
    playlists: list[PlaylistInfo] | None = None,
    podcast_playlists: list[PlaylistInfo] | None = None,
    smart_playlists: list[PlaylistInfo] | None = None,
    capabilities: DeviceCapabilities | None = None,
    master_playlist_name: str = "iPod",
    master_playlist_id: int | None = None,
    podcast_master_playlist_name: str | None = None,
    podcast_master_playlist_id: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
    before_database_replace: Callable[[], None] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> bool:
    """
    Write a complete iTunesDB to an iPod.

    This function:
    1. Optionally writes ArtworkDB + ithmb files from PC embedded art
    2. Builds the database structure
    3. Applies the appropriate checksum/hash for the device
    4. Writes atomically (temp file + rename)

    Args:
        ipod_path: Mount point of iPod
        tracks: List of TrackInfo objects
        db_id: Database ID (uses existing or generates new)
        backup: Whether to backup existing iTunesDB
        force_checksum: Override auto-detected checksum type (for devices with empty SysInfo)
        firewire_id: 8-byte FireWire ID for HASH58 (can be extracted from existing database)
        reference_itdb_path: Path to a known-good iTunesDB to extract hash info from
                            (useful for devices with empty SysInfo)
        pc_file_paths: Dict mapping track db_track_id (int) → PC source file path (str)
                       for extracting embedded album art. If provided, ArtworkDB
                       and ithmb files will be written and mhii_link set on tracks.
        playlists: List of PlaylistInfo for user playlists (dataset 2).
                   Master playlist is auto-generated; does NOT belong in this list.
        podcast_playlists: List of PlaylistInfo for dataset 3 playlists. If
                           None, dataset 2 playlists are cloned into dataset 3.
                           Pass [] to preserve an empty dataset-3 user list.
        smart_playlists: List of PlaylistInfo for dataset 5 smart playlists.
        capabilities: Device capabilities from ``ipod_device``.  Auto-detected
                      from the current device if not provided.
        master_playlist_name: Display name for the auto-generated master playlist.
        master_playlist_id: Existing dataset 2 master playlist ID, if any.

    Returns:
        True if successful
    """
    def _progress(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    _progress("Preparing database")

    # Resolve capabilities for this exact path before selecting the database
    # filename. A retained caller snapshot always wins over mutable UI/global
    # device selection; disk state is only a fallback when identity is unknown.
    if capabilities is None:
        try:
            from iopenpod.device import (
                capabilities_for_family_gen,
                get_current_device_for_path,
            )

            dev = get_current_device_for_path(ipod_path)
            if dev and dev.model_family:
                capabilities = capabilities_for_family_gen(
                    dev.model_family,
                    dev.generation or "",
                )
                if capabilities:
                    logger.debug(
                        "Auto-detected capabilities: %s %s (db_version=0x%X, "
                        "podcast=%s, gapless=%s, video=%s, music_dirs=%d)",
                        dev.model_family,
                        dev.generation or "(family fallback)",
                        capabilities.db_version,
                        capabilities.supports_podcast,
                        capabilities.supports_gapless,
                        capabilities.supports_video,
                        capabilities.music_dirs,
                    )
        except Exception as e:
            logger.debug("Could not auto-detect capabilities: %s", e)

    retained_filename = _database_filename_for_capabilities(capabilities)
    selected_existing_itdb_path = _resolve_existing_itdb_for_write(
        ipod_path,
        preferred_filename=retained_filename,
    )
    disk_filename = None
    if (
        selected_existing_itdb_path is not None
        and os.path.getsize(selected_existing_itdb_path) > 0
    ):
        disk_filename = os.path.basename(selected_existing_itdb_path)
    db_filename = retained_filename or (
        disk_filename
        if disk_filename is not None
        else "iTunesDB"
    )
    itunes_subtree = os.path.join("iPod_Control", "iTunes")
    itdb_path = str(
        resolve_device_path(
            ipod_path,
            os.path.join(itunes_subtree, db_filename),
            allowed_subtree=itunes_subtree,
        )
    )

    def _before_precommit_mutation() -> None:
        _run_before_mutation(before_device_mutation)
        _run_before_mutation(before_database_replace)

    # Read existing database for reference (for db_id and hash info extraction)
    # Check both iTunesCDB and iTunesDB — the existing database may be under
    # either name, and we may be switching filenames (e.g. first iOpenPod write
    # to a device that previously only had iTunesCDB from iTunes).
    existing_itdb = None
    existing_itdb_path = selected_existing_itdb_path
    if existing_itdb_path:
        existing_itdb_path = str(
            resolve_device_path(
                ipod_path,
                os.path.join(
                    itunes_subtree,
                    os.path.basename(existing_itdb_path),
                ),
                allowed_subtree=itunes_subtree,
            )
        )
        existing_size = os.path.getsize(existing_itdb_path)
        try:
            with open(existing_itdb_path, 'rb') as f:
                existing_itdb = f.read()
        except Exception as exc:
            if existing_size > 0:
                raise RuntimeError(
                    "The existing iPod database could not be read safely: "
                    f"{existing_itdb_path}. iOpenPod stopped before replacing it: {exc}"
                ) from exc
            logger.warning(
                "Could not read zero-byte database marker %s: %s",
                existing_itdb_path,
                exc,
            )
        else:
            if existing_size > 0 and not existing_itdb:
                raise RuntimeError(
                    "The existing iPod database became empty while it was being read. "
                    "iOpenPod stopped before replacing it."
                )
            if existing_itdb:
                _validate_existing_itunesdb(existing_itdb, existing_itdb_path)
            logger.debug(
                "Read existing database from %s (%d bytes)",
                existing_itdb_path,
                len(existing_itdb),
            )

    # Also read reference iTunesDB if provided
    reference_itdb = None
    if reference_itdb_path and os.path.exists(reference_itdb_path):
        try:
            with open(reference_itdb_path, 'rb') as f:
                reference_itdb = f.read()
        except Exception:
            pass

    # Try to preserve existing db_id if file exists
    if db_id is None and existing_itdb and existing_itdb[:4] == b'mhbd' and len(existing_itdb) >= 32:
        db_id = struct.unpack('<Q', existing_itdb[24:32])[0]
        logger.debug("Preserved db_id=0x%016X from existing database", db_id)
    elif db_id is None:
        logger.debug("No existing database found — db_id will be generated"
                     " (existing_itdb=%s, path=%s)",
                     'None' if existing_itdb is None else f'{len(existing_itdb)}B',
                     existing_itdb_path)

    # Extract reference info to copy device-specific fields
    reference_info = None
    source_itdb = reference_itdb or existing_itdb
    if source_itdb and source_itdb[:4] == b'mhbd' and len(source_itdb) >= 244:
        # Decompress iTunesCDB payload if needed — the MHSD children
        # (needed for type extraction) are in the zlib-compressed payload.
        source_itdb_full = _maybe_decompress_cdb(source_itdb)
        hdr_len_ref = struct.unpack('<I', source_itdb[4:8])[0]

        try:
            # Use read_fields() for MHBD header extraction (field_defs names)
            reference_info = read_fields(source_itdb, 0, 'mhbd', hdr_len_ref)

            # Extract reference MHSD types to match dataset structure
            # Use the decompressed view so we can see the MHSD children
            # Store as ordered list — firmware may be sensitive to dataset order
            # (e.g. Nano 5G expects 4,8,1,3,5 not 1,3,4,8,5)
            ref_mhsd_order: list[int] = []
            ref_mhsd_types: set[int] = set()
            ref_hdr_len = struct.unpack('<I', source_itdb_full[4:8])[0]
            ref_cc = struct.unpack('<I', source_itdb_full[0x14:0x18])[0]
            ref_off = ref_hdr_len
            for _i in range(ref_cc):
                if ref_off + 16 > len(source_itdb_full):
                    break
                if source_itdb_full[ref_off:ref_off + 4] != b'mhsd':
                    break
                ref_mhsd_type = struct.unpack('<I', source_itdb_full[ref_off + 12:ref_off + 16])[0]
                if ref_mhsd_type not in ref_mhsd_types:
                    ref_mhsd_order.append(ref_mhsd_type)
                ref_mhsd_types.add(ref_mhsd_type)
                ref_mhsd_total = struct.unpack('<I', source_itdb_full[ref_off + 8:ref_off + 12])[0]
                ref_off += ref_mhsd_total
            reference_info['mhsd_types'] = ref_mhsd_types
            reference_info['mhsd_order'] = ref_mhsd_order

            # Extract reference MHIT header size for matching
            mhsd_off = ref_hdr_len
            for _ in range(ref_cc):
                if mhsd_off + 16 > len(source_itdb_full):
                    break
                mhsd_total = struct.unpack('<I', source_itdb_full[mhsd_off + 8:mhsd_off + 12])[0]
                mhsd_type = struct.unpack('<I', source_itdb_full[mhsd_off + 12:mhsd_off + 16])[0]
                if mhsd_type == 1:  # tracks dataset
                    mhlt_off = mhsd_off + struct.unpack('<I', source_itdb_full[mhsd_off + 4:mhsd_off + 8])[0]
                    mhlt_hdr_len = struct.unpack('<I', source_itdb_full[mhlt_off + 4:mhlt_off + 8])[0]
                    track_count = struct.unpack('<I', source_itdb_full[mhlt_off + 8:mhlt_off + 12])[0]
                    if track_count > 0:
                        mhit_off = mhlt_off + mhlt_hdr_len
                        reference_info['mhit_header_size'] = struct.unpack('<I', source_itdb_full[mhit_off + 4:mhit_off + 8])[0]
                    break
                mhsd_off += mhsd_total

            logger.debug("Using reference database fields: db_id_2=%016X, lib_pid=%016X, "
                         "version=0x%X, mhsd_types=%s, mhit_hdr=%s",
                         reference_info['db_id_2'], reference_info['db_persistent_id'],
                         reference_info.get('version', 0),
                         sorted(ref_mhsd_types),
                         hex(reference_info.get('mhit_header_size', 0)))
        except Exception as e:
            logger.warning("Could not extract reference info: %s", e)
            reference_info = None

    filesystem_type = detect_filesystem_type(ipod_path)
    existing_platform = _valid_itunesdb_platform(existing_itdb)
    external_reference_platform = _valid_itunesdb_platform(reference_itdb)
    if existing_platform is not None:
        reference_platform = existing_platform
        platform_evidence_source = "existing_database"
    elif external_reference_platform is not None:
        reference_platform = external_reference_platform
        platform_evidence_source = "reference_database"
    else:
        reference_platform = None
        platform_evidence_source = ""
    platform_resolution = resolve_itunesdb_platform(
        filesystem_type=filesystem_type,
        reference_platform=reference_platform,
    )
    if reference_platform is not None:
        platform_resolution = _dc_replace(
            platform_resolution,
            source=platform_evidence_source,
        )
    platform_name = (
        "Mac" if platform_resolution.flag == 1 else "Windows"
    )
    logger.info(
        "iTunesDB platform selection: flag=%d (%s) source=%s "
        "filesystem=%s reference=%s",
        platform_resolution.flag,
        platform_name,
        platform_resolution.source,
        platform_resolution.filesystem_type or "unknown",
        platform_resolution.reference_platform or "none",
    )
    if platform_resolution.mismatch:
        inferred_name = (
            "Mac" if platform_resolution.inferred_flag == 1 else "Windows"
        )
        preserved_from = (
            "the existing on-device database"
            if platform_resolution.source == "existing_database"
            else "the supplied reference database"
        )
        logger.warning(
            "iTunesDB platform/filesystem mismatch: preserving flag=%d (%s) "
            "from %s although filesystem=%s suggests %s",
            platform_resolution.flag,
            platform_name,
            preserved_from,
            platform_resolution.filesystem_type,
            inferred_name,
        )

    # --- Generate db_track_ids for all tracks BEFORE artwork ---
    # write_mhit() generates db_track_ids lazily, but we need them now so
    # write_artworkdb can match tracks to PC file paths.
    from .mhit_writer import generate_db_track_id
    for track in tracks:
        if track.db_track_id == 0:
            track.db_track_id = generate_db_track_id()

    # --- Write ArtworkDB if the caller requested artwork reconciliation ---
    pending_artwork = None  # PendingArtworkWrite if defer_commit used
    if pc_file_paths is not None:
        artwork_formats = None
        if capabilities is not None and not capabilities.supports_artwork:
            try:
                from iopenpod.device import ITHMB_FORMAT_MAP

                fallback_format_id = 1060
                fallback = ITHMB_FORMAT_MAP.get(fallback_format_id)
                if fallback is not None:
                    artwork_formats = {
                        fallback_format_id: (int(fallback.width), int(fallback.height))
                    }
                    _progress("Artwork — generating iOpenPod-only artwork")
                    logger.info(
                        "ART: device reports no artwork support; writing fallback format %d for iOpenPod view",
                        fallback_format_id,
                    )
            except Exception as exc:
                logger.warning("ART: could not resolve fallback artwork format: %s", exc)

        logger.debug("ART: pc_file_paths has %d entries, tracks has %d tracks",
                     len(pc_file_paths), len(tracks))

        # Log sample of pc_file_paths
        for i, (db_track_id, path) in enumerate(list(pc_file_paths.items())[:5]):
            # Find track title for this db_track_id
            title = "?"
            for t in tracks:
                if t.db_track_id == db_track_id:
                    title = t.title
                    break
            logger.debug("ART:   [%d] db_track_id=%d title='%s' path=%s", i, db_track_id, title, path)

        # Check how many tracks have matching pc_file_paths
        matched = sum(1 for t in tracks if t.db_track_id in pc_file_paths)
        logger.debug("ART: %d/%d tracks have a PC source path", matched, len(tracks))

        try:
            from iopenpod.artworkdb_writer.artwork_writer import PendingArtworkWrite, write_artworkdb
            ref_artdb = os.path.join(ipod_path, "iPod_Control", "Artwork", "ArtworkDB")
            ref_artdb_path = ref_artdb if os.path.exists(ref_artdb) else None

            art_result = write_artworkdb(
                ipod_path=ipod_path,
                tracks=tracks,
                pc_file_paths=pc_file_paths,
                reference_artdb_path=ref_artdb_path,
                artwork_formats=artwork_formats,
                defer_commit=True,
                progress_callback=_progress,
                before_device_mutation=_before_precommit_mutation,
            )

            # Extract the mapping — works for both deferred and immediate results
            if isinstance(art_result, PendingArtworkWrite):
                pending_artwork = art_result
                db_track_id_to_img_id = art_result.db_track_id_to_art_info
            else:
                pending_artwork = None
                db_track_id_to_img_id = art_result

            # Update mhii_link and artwork_size on every track. The artwork
            # writer always converges the device to its final state, including
            # the zero-art case, so any missing entry here must clear stale refs.
            art_count = 0
            for track in tracks:
                art_info = db_track_id_to_img_id.get(track.db_track_id)
                if art_info:
                    img_id, src_img_size = art_info
                    track.mhii_link = img_id
                    track.artwork_count = 1
                    track.artwork_size = src_img_size
                    art_count += 1
                else:
                    track.mhii_link = 0
                    track.artwork_count = 0
                    track.artwork_size = 0
            logger.debug("ART: linked %d/%d tracks to %d unique images",
                         art_count, len(tracks), len(db_track_id_to_img_id))
            for t in tracks[:5]:
                logger.debug("ART:   '%s' mhii_link=%d artwork_count=%d artwork_size=%d",
                             t.title, t.mhii_link, t.artwork_count, t.artwork_size)
        except Exception as e:
            if pending_artwork:
                pending_artwork.abort()
                pending_artwork = None
            logger.error("ART: ArtworkDB write failed: %s", e, exc_info=True)
            raise
    else:
        _progress("Skipping artwork (no sources)")
        logger.debug("ART: pc_file_paths is %s — skipping ArtworkDB",
                     'None' if pc_file_paths is None else 'empty dict')

    _progress("Building database structure")

    # Extract preserved MHSD blobs (Genius data, types 6+) from existing database
    preserved_blobs: list[bytes] = []
    if existing_itdb:
        preserved_blobs = extract_preserved_mhsd_blobs(existing_itdb)

    # Build database with reference info
    itdb_data = bytearray(write_mhbd(
        tracks, db_id, reference_info=reference_info,
        platform=platform_resolution.flag,
        playlists_type2=playlists,
        playlists_type3=podcast_playlists,
        playlists_type5=smart_playlists,
        preserved_mhsd_blobs=preserved_blobs,
        capabilities=capabilities,
        master_playlist_name=master_playlist_name,
        master_playlist_id=master_playlist_id,
        podcast_master_playlist_name=podcast_master_playlist_name,
        podcast_master_playlist_id=podcast_master_playlist_id,
    ))

    # ── Compress for iTunesCDB if needed ──────────────────────────────
    #   MUST happen BEFORE checksum — the iPod firmware verifies the hash
    #   against the on-disk bytes, which are the compressed form.
    #   See docs/iTunesCDB-internals.md §5 "Write Path — Compression & Signing".
    #
    #   On-disk format: uncompressed mhbd header (244 bytes) +
    #   zlib-compressed payload (all mhsd children).  total_length is
    #   patched to the compressed file size.  unk_0xA8 is set to 1.
    uncompressed_size = len(itdb_data)
    if db_filename == "iTunesCDB":
        hdr_len = struct.unpack_from('<I', itdb_data, 4)[0]
        payload = bytes(itdb_data[hdr_len:])
        compressed = zlib.compress(payload, 1)  # Z_BEST_SPEED — matches libgpod/iTunes
        cdb_buf = bytearray(itdb_data[:hdr_len]) + bytearray(compressed)
        # Patch total_length to compressed file size
        struct.pack_into('<I', cdb_buf, 8, len(cdb_buf))
        # Set unk_0xA8 = 1 to indicate compressed payload (per libgpod)
        struct.pack_into('<H', cdb_buf, 0xA8, 1)
        logger.info("Compressed %d -> %d bytes for iTunesCDB (level 1)",
                    uncompressed_size, len(cdb_buf))
        # All subsequent checksum code must operate on the compressed buffer
        itdb_data = cdb_buf

    _progress("Signing database")

    # Detect checksum type (or use forced type)
    # Use reference or existing database as the source for hash extraction
    source_itdb = reference_itdb or existing_itdb
    hash_error: str | None = None  # set on fatal hash failure

    if force_checksum is not None:
        checksum_type = force_checksum
        logger.debug("Using forced checksum type: %s", checksum_type.name)
    elif capabilities is not None and capabilities.checksum != ChecksumType.UNKNOWN:
        checksum_type = capabilities.checksum
        logger.debug(
            "Using checksum type from retained device capabilities: %s",
            checksum_type.name,
        )
    else:
        checksum_type = detect_checksum_type(ipod_path)
        # If detection returned NONE but we have an existing database with hashing,
        # infer the checksum type from it
        if checksum_type == ChecksumType.NONE and source_itdb and len(source_itdb) >= 0xA0:
            existing_scheme = struct.unpack('<H', source_itdb[0x30:0x32])[0]
            # Check if existing database has a valid hash72 signature (01 00 marker)
            has_valid_hash72 = source_itdb[0x72:0x74] == bytes([0x01, 0x00])
            # Check if existing database has a non-zero hash58
            has_valid_hash58 = source_itdb[0x58:0x6C] != bytes(20)

            if existing_scheme == 1 and has_valid_hash58 and has_valid_hash72:
                checksum_type = ChecksumType.HASH58
                logger.debug("Detected iPod Classic pattern (hash_scheme=1 with both hashes)")
            elif has_valid_hash72:
                checksum_type = ChecksumType.HASH72
                logger.debug("Detected valid HASH72 signature in existing database")
            elif existing_scheme == 1:
                checksum_type = ChecksumType.HASH58
                logger.debug("Detected HASH58 from existing database")
            elif existing_scheme == 2:
                checksum_type = ChecksumType.HASH72
                logger.debug("Detected HASH72 from existing database")

    if checksum_type == ChecksumType.HASH58:
        # iPod Classic requires HASH58 (and often HASH72 too)
        # IMPORTANT: hash72 must be written BEFORE hash58!
        #   - hash72 computation zeros both hash58 and hash72 fields → doesn't depend on either
        #   - hash58 computation zeros db_id, unk_0x32, hash58 but NOT hash72
        #   - So hash58 depends on hash72 being present in the data
        #   - iTunes writes hash72 first, then hash58

        # Set hashing_scheme BEFORE computing any hashes — hash72's SHA1
        # includes this field (not zeroed), so it must have its final value.
        struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 1)

        # Step 1: Write HASH72 first (if reference has it)
        if source_itdb and len(source_itdb) >= 0xA0 and source_itdb[0x72:0x74] == bytes([0x01, 0x00]):
            from .hash72 import _compute_itunesdb_sha1, _hash_generate, extract_hash_info_to_dict
            hash_dict = extract_hash_info_to_dict(source_itdb)
            if hash_dict:
                sha1 = _compute_itunesdb_sha1(itdb_data)
                signature = _hash_generate(sha1, hash_dict['iv'], hash_dict['rndpart'])
                itdb_data[0x72:0x72 + 46] = signature
                logger.debug("HASH72 signature written first (hash58 depends on it)")

        # Step 2: Write HASH58 (HMAC-SHA1 using key derived from device FireWire GUID)
        # Try to get FireWire ID from parameter, SysInfo, SysInfoExtended, or Windows registry
        if firewire_id is None:
            try:
                from iopenpod.device import get_firewire_id
                firewire_id = get_firewire_id(ipod_path)
            except Exception as e:
                logger.warning("Could not get FireWire ID: %s", e)

        if firewire_id:
            write_hash58(itdb_data, firewire_id)
            logger.info("HASH58 signature computed with FireWire ID: %s", firewire_id.hex())
        else:
            hash_error = (
                "No FireWire ID is available to compute the required HASH58 "
                "signature. iOpenPod stopped before writing a database the "
                "iPod firmware would reject."
            )

    elif checksum_type == ChecksumType.HASH72:
        # Try to get hash info from centralized store first, then fall back to disk
        from .hash72 import HashInfo, _compute_itunesdb_sha1, _hash_generate, extract_hash_info_to_dict, read_hash_info

        hash_info = None
        try:
            from iopenpod.device import get_current_device_for_path
            dev = get_current_device_for_path(ipod_path)
            if dev and dev.hash_info_iv and dev.hash_info_rndpart:
                hash_info = HashInfo(uuid=b'\x00' * 20, rndpart=dev.hash_info_rndpart, iv=dev.hash_info_iv)
                logger.debug("HashInfo loaded from centralized device store")
        except Exception:
            pass

        hash72_written = False
        if hash_info is None:
            # Fallback: read_hash_info checks the store again (harmless)
            # then reads from disk if needed
            try:
                hash_info = read_hash_info(ipod_path)
            except Exception:
                pass

        # Set hashing_scheme BEFORE computing hash72 — the SHA1 includes
        # this field (it is NOT zeroed), so it must have its final value
        # when the hash is computed.  libgpod itdb_hash72_write_hash sets
        # this to ITDB_CHECKSUM_HASH72 (2), not 1.  Using 1 causes the
        # Nano 5G firmware to check hash58 instead of hash72.
        struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 2)

        # Write HASH72 signature
        if hash_info is None:
            # Try to extract from reference database
            source_itdb = reference_itdb or existing_itdb
            if source_itdb:
                logger.debug("Attempting to extract hash info from reference database...")
                hash_dict = extract_hash_info_to_dict(source_itdb)
                if hash_dict:
                    logger.debug("  IV: %s", hash_dict['iv'].hex())
                    logger.debug("  rndpart: %s", hash_dict['rndpart'].hex())
                    sha1 = _compute_itunesdb_sha1(itdb_data)
                    signature = _hash_generate(sha1, hash_dict['iv'], hash_dict['rndpart'])
                    itdb_data[0x72:0x72 + 46] = signature
                    hash72_written = True
                    logger.info("HASH72 signature written successfully")
                else:
                    logger.warning("Could not extract hash info from reference database")
            else:
                logger.warning("No HashInfo file and no reference database available")
        else:
            sha1 = _compute_itunesdb_sha1(itdb_data)
            signature = _hash_generate(sha1, hash_info.iv, hash_info.rndpart)
            itdb_data[0x72:0x72 + 46] = signature
            hash72_written = True
            logger.info("HASH72 signature written from HashInfo file")

        if not hash72_written:
            hash_error = (
                "No valid HashInfo material is available to compute the "
                "required HASH72 signature. iOpenPod stopped before writing "
                "a database the iPod firmware would reject."
            )

        # Nano 5G uses HASH72 only — do NOT write hash58.
        # libgpod itdb_hash72_write_hash only computes hash72 (hashing_scheme=2).
        # Writing hash58 here with scheme=1 causes the firmware to verify
        # hash58 and potentially reject the database if hash58 is wrong.

    elif checksum_type == ChecksumType.HASHAB:
        # iPod Nano 6G/7G — white-box AES via WASM module
        # Requires FireWire ID (same as HASH58)
        if firewire_id is None:
            try:
                from iopenpod.device import get_firewire_id
                firewire_id = get_firewire_id(ipod_path)
            except Exception as e:
                logger.warning("Could not get FireWire ID for HASHAB: %s", e)

        if firewire_id:
            try:
                write_hashab(itdb_data, firewire_id)
                # Set hashing_scheme to 3 (matches iTunes-written HASHAB databases)
                struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 3)
                logger.info("HASHAB signature computed with FireWire ID: %s",
                            firewire_id.hex())
            except ImportError as e:
                hash_error = f"HASHAB dependency missing: {e}"
            except FileNotFoundError as e:
                hash_error = f"HASHAB WASM module missing: {e}"
        else:
            hash_error = (
                "No FireWire ID available — cannot compute HASHAB. "
                "Ensure the iPod is connected so the FireWire GUID can be "
                "read from USB serial number."
            )

    elif checksum_type == ChecksumType.UNSUPPORTED:
        hash_error = "Device requires an unsupported hashing scheme"
    elif checksum_type == ChecksumType.UNKNOWN:
        hash_error = (
            "Cannot write iTunesDB: device checksum type is UNKNOWN. "
            "The device was not fully identified — the iPod will reject "
            "this database. Please report this as a bug."
        )

    else:
        # ChecksumType.NONE — pre-2007 devices that need no hash
        struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 0)

    if hash_error:
        logger.error(hash_error)
        if pending_artwork:
            pending_artwork.abort(before_remove=before_device_mutation)
        return False

    try:
        _run_before_mutation(before_device_mutation)
        _preflight_database_install(
            ipod_path,
            itdb_path,
            len(itdb_data),
            capabilities=capabilities,
            backup_sources=(itdb_path, existing_itdb_path) if backup else (),
        )
    except Exception:
        if pending_artwork:
            pending_artwork.abort(before_remove=before_device_mutation)
        raise

    # Backup existing file(s)
    if backup:
        backup_sources = dict.fromkeys((itdb_path, existing_itdb_path))
        for _bpath in backup_sources:
            if _bpath and os.path.exists(_bpath):
                try:
                    _copy_device_file_durably(
                        _bpath,
                        _bpath + ".backup",
                        before_device_mutation=_before_precommit_mutation,
                    )
                except Exception as e:
                    logger.error(
                        "Could not safely backup %s: %s",
                        os.path.basename(_bpath),
                        e,
                    )
                    if pending_artwork:
                        pending_artwork.abort(
                            before_remove=before_device_mutation
                        )
                    return False

    _progress("Writing to iPod")

    # Write atomically — os.replace is atomic on NTFS and POSIX
    temp_path: os.PathLike[str] | None = None
    database_committed = False
    stale_temp: os.PathLike[str] | None = None
    try:
        _run_before_mutation(before_device_mutation)
        temp_path, temp_file = open_unique_sibling_temp(itdb_path, mode="wb")
        with temp_file as f:
            f.write(itdb_data)
            flush_written_file(f)

        # Commit ArtworkDB and ithmb files FIRST (before swapping CDB),
        # then swap CDB.  Both happen here to ensure they stay in sync.
        if pending_artwork:
            pending_artwork.commit(before_replace=_before_precommit_mutation)
            logger.info("ART: committed ArtworkDB + ithmb files")

        # Serialization, checksumming, and artwork preparation can take long
        # enough for another process to replace the live database.  Let the
        # guarded caller re-check its generation at the actual commit point,
        # after every preparatory step but before the atomic replacement.
        _before_precommit_mutation()
        durable_replace(temp_path, itdb_path)
        database_committed = True

        # Truncate the stale database file to 0 bytes if the filename changed
        # (e.g. migrating from iTunesDB → iTunesCDB or vice versa).
        # libgpod truncates rather than deletes because some firmwares may
        # check for the file's existence and behave unexpectedly if it's gone.
        if existing_itdb_path and existing_itdb_path != itdb_path:
            _run_before_mutation(before_device_mutation)
            stale_temp, stale_file = open_unique_sibling_temp(
                existing_itdb_path,
                mode="wb",
            )
            with stale_file as f:
                flush_written_file(f)
            _run_before_mutation(before_device_mutation)
            durable_replace(stale_temp, existing_itdb_path)
            logger.info(
                "Truncated stale %s to 0 bytes (now using %s)",
                os.path.basename(existing_itdb_path),
                db_filename,
            )

        logger.info("Wrote %s (%d bytes%s)", db_filename, len(itdb_data),
                    f", uncompressed {uncompressed_size}" if db_filename == "iTunesCDB" else "")
        return True

    except Exception as e:
        logger.error("Error writing iTunesDB: %s", e)
        if temp_path is not None and os.path.exists(temp_path):
            _cleanup_device_temp(
                temp_path,
                before_device_mutation=before_device_mutation,
            )
        if stale_temp and os.path.exists(stale_temp):
            _cleanup_device_temp(
                stale_temp,
                before_device_mutation=before_device_mutation,
            )
        if not database_committed and pending_artwork:
            pending_artwork.abort(before_remove=before_device_mutation)
        # Note: if we reached this point, pending_artwork was already
        # committed (it happens before os.replace for the CDB).  A CDB
        # write failure after artwork commit is unlikely (same filesystem)
        # but if it happens the artwork is still in sync with the CDB
        # data that was built from the same track list.
        return False
