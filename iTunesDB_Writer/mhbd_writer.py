"""MHBD Writer — Write complete iTunesDB database files.

This is the top-level writer that assembles all components into
a valid iTunesDB (or iTunesCDB for Nano 5G+) file.

Dataset write order (matches libgpod):
  mhbd (database header, 244 bytes)
    mhsd type 1 (tracks dataset)
      mhlt (track list)
        mhit (track) x N
          mhod (string) x M
    mhsd type 3 (podcasts dataset) — MUST appear between types 1 and 2
      mhlp (playlist list) — same data as type 2
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
    +0x24: id_0x24 (8B) — secondary ID (written in every MHIT)
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
  - iTunesDB_Parser/mhbd_parser.py parse_db()
  - libgpod itdb_itunesdb.c: mk_mhbd() / parse_mhbd()
"""

import struct
import random
import os
import shutil
import time
import logging
from typing import List, Optional

from .mhlt_writer import write_mhlt
from .mhsd_writer import (
    write_mhsd_type1, write_mhsd_type2, write_mhsd_type4,
    write_mhsd_type3, write_mhsd_smart_type5,
    write_mhsd_type8, write_mhsd_empty_stub,
)
from .mhlp_writer import write_mhlp_with_playlists, write_mhlp_smart
from .mhla_writer import write_mhla
from .mhli_writer import write_mhli
from .mhit_writer import TrackInfo
from .mhyp_writer import PlaylistInfo
from ipod_models import ChecksumType, DeviceCapabilities
from device_info import detect_checksum_type
from .hash58 import write_hash58
from .hashab import write_hashab
from iTunesDB_Shared.field_base import (
    read_fields,
    write_fields,
    write_generic_header,
)
from iTunesDB_Shared.mhbd_defs import (
    MHBD_HEADER_SIZE,
    MHBD_OFFSET_HASHING_SCHEME,
)

logger = logging.getLogger(__name__)

# Default database version — 0x4F (79) works for iPod Classic / Nano 3G+.
# For older devices, callers should pass `db_version` from
# ``ipod_models.DeviceCapabilities.db_version``.
DATABASE_VERSION_DEFAULT = 0x4F


def extract_db_info(itdb_path: str) -> dict:
    """
    Extract useful information from an existing iTunesDB.

    This can be used to get:
    - db_id: To preserve identity across rewrites
    - hashing_scheme: What hash type is used
    - hash58/hash72: The actual hash values

    All keys use canonical ``field_defs`` names (e.g. ``'db_id_2'`` not
    ``'id_0x24'``, ``'timezone_offset'`` not ``'timezone'``).

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
    if (len(itdb_data) > header_length + 2
            and struct.unpack('<H', itdb_data[0xA8:0xAA])[0] == 1
            and itdb_data[header_length] == 0x78):
        try:
            import zlib as _zlib
            decompressed = _zlib.decompress(itdb_data[header_length:])
            itdb_data = itdb_data[:header_length] + decompressed
            logger.debug("extract_preserved_mhsd_blobs: decompressed CDB payload")
        except Exception:
            pass  # Fall through — loop will find no mhsd magic and return []

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
    tracks: List[TrackInfo],
    db_id: Optional[int] = None,
    language: str = "en",
    reference_info: Optional[dict] = None,
    playlists_type2: Optional[List[PlaylistInfo]] = None,
    playlists_type5: Optional[List[PlaylistInfo]] = None,
    preserved_mhsd_blobs: Optional[List[bytes]] = None,
    capabilities: Optional[DeviceCapabilities] = None,
    master_playlist_name: str = "iPod",
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
        playlists_type5: List of PlaylistInfo for dataset 5 smart playlists
                         (iPod browsing categories like Music, Movies, etc.)
        preserved_mhsd_blobs: Raw MHSD byte blobs (types 6+) extracted from
                              an existing database via extract_preserved_mhsd_blobs().
                              Appended verbatim after the 5 standard datasets to
                              preserve Genius and other iTunes-generated data.
        capabilities: Device capabilities from ``ipod_models``.  When provided,
                      ``db_version`` and ``supports_podcast`` are respected.
        master_playlist_name: Display name for the auto-generated master playlist.

    Returns:
        Complete iTunesDB file content as bytes
    """
    # Determine database ID, passed, preserved, or random
    if db_id is None:
        if reference_info and 'db_id' in reference_info:
            db_id = reference_info['db_id']
        else:
            db_id = generate_database_id()

    # Generate id_0x24 early - needed for both the MHBD header AND every MHIT, preserved or random.
    if reference_info and 'id_0x24' in reference_info:
        id_0x24 = reference_info['id_0x24']
    else:
        id_0x24 = random.getrandbits(64)

    # Build album list first to get album IDs for tracks (Type 4 dataset)
    global_id_start_index = 1

    mhla_data, album_map, last_id = write_mhla(tracks, starting_index_for_album_id=global_id_start_index)
    mhsd_type4 = write_mhsd_type4(mhla_data)

    # Build artist list to get artist IDs for tracks (Type 8 dataset)
    mhli_data, artist_map, last_id = write_mhli(tracks, starting_index_for_artist_id=last_id + 1)
    mhsd_type8 = write_mhsd_type8(mhli_data)

    # Assign album_id and artist_id to each track
    from .mhla_writer import _album_key
    for track in tracks:
        key = _album_key(track)
        track.album_id = album_map.get(key, 0)

        # Artist ID from the artist list
        artist_name = track.artist or ""
        if artist_name:
            track.artist_id = artist_map.get(artist_name, 0)

        # Composer ID
        # TODO: Implement composer list and IDs like albums/artists, and assign real composer_id here instead of 0.
        composer_name = track.composer or ""
        if composer_name:
            track.composer_id = 0

    # Build track list (Type 1 dataset)
    # This also returns next_track_id which tells us track IDs used

    mhlt_data, next_track_id = write_mhlt(tracks, id_0x24=id_0x24, capabilities=capabilities, start_track_id=last_id + 1)
    mhsd_type1 = write_mhsd_type1(mhlt_data)

    # Collect all track IDs for the master playlist
    # Track IDs are sequential starting from 1
    track_ids = list(range(last_id + 1, next_track_id))

    # Build db_id → sequential track_id map so playlists can reference
    # tracks by their 32-bit MHIT trackID (not 64-bit db_id).
    # The sync executor stores db_ids in PlaylistInfo.track_ids because
    # db_ids are the stable identifier, but MHIP entries need 32-bit IDs.
    db_id_to_track_id: dict[int, int] = {}
    for i, track in enumerate(tracks):
        if track.db_id:
            db_id_to_track_id[track.db_id] = i + last_id + 1

    # Remap playlist track_ids from 64-bit db_id → 32-bit sequential track_id.
    #
    # PlaylistInfo.track_ids stores db_ids (the stable cross-session identifier),
    # but MHIP entries in the iTunesDB need sequential track IDs assigned by
    # write_mhlt.  We build new PlaylistInfo copies with remapped IDs instead
    # of mutating the caller's objects — if write_mhbd() were retried (e.g.
    # after an I/O error) the original db_id-based track_ids must still be intact.
    from dataclasses import replace as _dc_replace

    def _remap_playlist(pl: PlaylistInfo) -> PlaylistInfo:
        """Return a copy of pl with thee db_ids translated to track IDs."""
        new_ids: list[int] = []
        new_meta: list | None = [] if pl.item_metadata is not None else None

        meta = pl.item_metadata  # capture for type narrowing
        for i, db_id in enumerate(pl.track_ids):
            track_id = db_id_to_track_id.get(db_id)
            if track_id is None:
                continue  # track not in this database — skip
            new_ids.append(track_id)
            if new_meta is not None and meta is not None:
                new_meta.append(meta[i])

        return _dc_replace(pl, track_ids=new_ids, item_metadata=new_meta)

    # Build playlist list WITH master playlist (Type 2 dataset)
    # The master playlist is REQUIRED and must reference ALL tracks
    # Pass tracks so master playlist can generate library index MHODs (type 52/53)
    #
    # Generate a single master playlist_id shared by DS2 and DS3 so that
    # the GUI dedup logic (by playlist_id) correctly collapses the two
    # copies of the master playlist into one.
    from .mhyp_writer import generate_playlist_id
    master_playlist_id = generate_playlist_id()

    remapped_playlists_type2 = [_remap_playlist(pl) for pl in (playlists_type2 or [])]
    mhsd_type2_data = write_mhlp_with_playlists(
        track_ids, playlists=remapped_playlists_type2,
        tracks=tracks, id_0x24=id_0x24, capabilities=capabilities,
        master_playlist_name=master_playlist_name,
        master_playlist_id=master_playlist_id,
    )
    mhsd_type2 = write_mhsd_type2(mhsd_type2_data)

    # Build podcast list (Type 3 dataset)
    # libgpod writes type 3 with the SAME playlists as type 2, but the
    # podcast playlist uses grouped MHIPs where episodes are nested
    # under their podcast show (album).  Non-podcast playlists are
    # written identically to type 2.

    # Pre-podcast devices (iPod 1G-3G, Mini 1G-2G, Shuffle 1G-2G)
    # don't understand type 3; skip it when capabilities say so.
    include_podcasts = True
    if capabilities is not None and not capabilities.supports_podcast:
        include_podcasts = False

    if include_podcasts:
        # Build track_id → album map for podcast grouping.
        # Sequential track IDs start after last_id (same as track_ids range).
        track_album_map: dict[int, str] = {}
        for i, track in enumerate(tracks):
            seq_id = i + last_id + 1
            track_album_map[seq_id] = track.album or ""

        from .mhlp_writer import write_mhlp_with_playlists_type3
        mhsd_type3_data = write_mhlp_with_playlists_type3(
            track_ids, playlists=remapped_playlists_type2,
            id_0x24=id_0x24, track_album_map=track_album_map,
            tracks=tracks, capabilities=capabilities,
            master_playlist_name=master_playlist_name,
            next_mhip_id_start=next_track_id,
            master_playlist_id=master_playlist_id,
        )
        mhsd_type3 = write_mhsd_type3(mhsd_type3_data)
    else:
        mhsd_type3 = b''

    # Build smart playlist list (Type 5 dataset) — same non-mutating remap
    remapped_playlists_type5 = [_remap_playlist(pl) for pl in (playlists_type5 or [])]
    mhsd_type5_data = write_mhlp_smart(remapped_playlists_type5, id_0x24=id_0x24)
    mhsd_type5 = write_mhsd_smart_type5(mhsd_type5_data)

    mhsd_type6 = write_mhsd_empty_stub(6)
    mhsd_type10 = write_mhsd_empty_stub(10)

    # Concatenate all datasets
    #
    # Default order matches libgpod: Type 1, 3, 2, 4, 8, 6, 10, 5
    #   - Type 3 MUST appear between types 1 and 2 for podcast support
    #   - Type 1 MUST be first — older iPod firmware (Video 5G, Nano 1G-2G)
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
    if reference_info and 'mhsd_types' in reference_info:
        rt = reference_info['mhsd_types']
        # Only use ref_types if extraction found meaningful data (at least type 1)
        if rt and 1 in rt:
            ref_types = rt
        logger.debug("Reference MHSD types: %s", sorted(ref_types) if ref_types else "none (fallback to all)")

    # Build the candidate datasets in priority order
    # Each entry: (type_number, data_bytes, required_flag)
    # When ref_types is available, only include types that are present in it.
    # Otherwise, include all types (libgpod-compatible default).

    def _include(dtype: int, required: bool = False) -> bool:
        if required:
            return True
        if ref_types is None:
            return True  # no reference → include everything
        return dtype in ref_types

    # Assemble datasets in libgpod order, skipping those not in the reference
    dataset_entries: list[tuple[int, bytes]] = []
    dataset_entries.append((1, mhsd_type1))  # always required
    if include_podcasts and _include(3):
        dataset_entries.append((3, mhsd_type3))
    if _include(2):
        dataset_entries.append((2, mhsd_type2))
    dataset_entries.append((4, mhsd_type4))  # always required
    dataset_entries.append((8, mhsd_type8))  # always required
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

    # +0x10: Version — highest of reference and device capabilities.
    ref_version = reference_info.get('version', 0) if reference_info else 0
    cap_version = capabilities.db_version if capabilities else DATABASE_VERSION_DEFAULT
    db_version = max(ref_version, cap_version) or DATABASE_VERSION_DEFAULT
    logger.debug("Using db_version=0x%X (ref=0x%X, cap=0x%X, default=0x%X)",
                 db_version, ref_version, cap_version, DATABASE_VERSION_DEFAULT)

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

    # +0x48: Library Persistent ID — must match iTunesPrefs (macOS protection)
    try:
        from device_info import generate_library_id
        lib_pid = struct.unpack('<Q', generate_library_id())[0]
    except Exception:
        lib_pid = reference_info.get('db_persistent_id', db_id) if reference_info else db_id

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

    header = bytearray(MHBD_HEADER_SIZE)
    write_generic_header(header, 0, b'mhbd', MHBD_HEADER_SIZE, total_length)

    values: dict = {
        'compressed': compressed,
        'version': db_version,
        'child_count': child_count,
        'db_id': db_id,
        'platform': 2,
        'unk0x22': reference_info.get('unk0x22', 611) if reference_info else 611,
        'db_id_2': id_0x24,
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


def write_itunesdb(
    ipod_path: str,
    tracks: List[TrackInfo],
    db_id: Optional[int] = None,
    backup: bool = True,
    force_checksum: Optional[ChecksumType] = None,
    firewire_id: Optional[bytes] = None,
    reference_itdb_path: Optional[str] = None,
    pc_file_paths: Optional[dict] = None,
    playlists: Optional[List[PlaylistInfo]] = None,
    smart_playlists: Optional[List[PlaylistInfo]] = None,
    capabilities: Optional[DeviceCapabilities] = None,
    master_playlist_name: str = "iPod",
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
        pc_file_paths: Dict mapping track db_id (int) → PC source file path (str)
                       for extracting embedded album art. If provided, ArtworkDB
                       and ithmb files will be written and mhii_link set on tracks.
        playlists: List of PlaylistInfo for user playlists (dataset 2).
                   Master playlist is auto-generated; does NOT belong in this list.
        smart_playlists: List of PlaylistInfo for dataset 5 smart playlists.
        capabilities: Device capabilities from ``ipod_models``.  Auto-detected
                      from the current device if not provided.
        master_playlist_name: Display name for the auto-generated master playlist.

    Returns:
        True if successful
    """
    from device_info import resolve_itdb_path, itdb_write_filename

    # Determine the correct database filename for this device (iTunesDB or iTunesCDB)
    db_filename = itdb_write_filename(ipod_path)
    itdb_path = os.path.join(ipod_path, "iPod_Control", "iTunes", db_filename)

    # Auto-detect capabilities from the centralized device store
    if capabilities is None:
        try:
            from device_info import get_current_device
            from ipod_models import capabilities_for_family_gen
            dev = get_current_device()
            if dev and dev.model_family and dev.generation:
                capabilities = capabilities_for_family_gen(
                    dev.model_family, dev.generation,
                )
                if capabilities:
                    logger.debug(
                        "Auto-detected capabilities: %s %s (db_version=0x%X, "
                        "podcast=%s, gapless=%s, video=%s, music_dirs=%d)",
                        dev.model_family, dev.generation,
                        capabilities.db_version,
                        capabilities.supports_podcast,
                        capabilities.supports_gapless,
                        capabilities.supports_video,
                        capabilities.music_dirs,
                    )
        except Exception as e:
            logger.debug("Could not auto-detect capabilities: %s", e)

    # Read existing database for reference (for db_id and hash info extraction)
    # Check both iTunesCDB and iTunesDB — the existing database may be under
    # either name, and we may be switching filenames (e.g. first iOpenPod write
    # to a device that previously only had iTunesCDB from iTunes).
    existing_itdb = None
    existing_itdb_path = resolve_itdb_path(ipod_path)
    if existing_itdb_path:
        try:
            with open(existing_itdb_path, 'rb') as f:
                existing_itdb = f.read()
        except Exception:
            pass

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

    # Extract reference info to copy device-specific fields
    reference_info = None
    source_itdb = reference_itdb or existing_itdb
    if source_itdb and source_itdb[:4] == b'mhbd' and len(source_itdb) >= 244:
        # Decompress iTunesCDB payload if needed — the MHBD header is always
        # uncompressed, but MHSD children (needed for type extraction) are
        # in the zlib-compressed payload.
        source_itdb_full = source_itdb  # uncompressed view for MHSD parsing
        hdr_len_ref = struct.unpack('<I', source_itdb[4:8])[0]
        # Check if unk_0xA8 == 1 (compressed indicator) and payload starts with
        # zlib header (0x78) — if so, decompress for structural inspection.
        if (len(source_itdb) > hdr_len_ref + 2
                and struct.unpack('<H', source_itdb[0xA8:0xAA])[0] == 1
                and source_itdb[hdr_len_ref] == 0x78):
            try:
                import zlib as _zlib
                decompressed = _zlib.decompress(source_itdb[hdr_len_ref:])
                source_itdb_full = source_itdb[:hdr_len_ref] + decompressed
                logger.debug("Decompressed reference iTunesCDB for structural inspection: "
                             "%d → %d bytes", len(source_itdb), len(source_itdb_full))
            except Exception as e:
                logger.debug("Could not decompress reference CDB: %s", e)

        try:
            # Use read_fields() for MHBD header extraction (field_defs names)
            reference_info = read_fields(source_itdb, 0, 'mhbd', hdr_len_ref)

            # Extract reference MHSD types to match dataset structure
            # Use the decompressed view so we can see the MHSD children
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
                ref_mhsd_types.add(ref_mhsd_type)
                ref_mhsd_total = struct.unpack('<I', source_itdb_full[ref_off + 8:ref_off + 12])[0]
                ref_off += ref_mhsd_total
            reference_info['mhsd_types'] = ref_mhsd_types

            # Extract reference MHIT header size for matching
            _off = ref_hdr_len
            for _j in range(ref_cc):
                if _off + 16 > len(source_itdb_full):
                    break
                _stotal = struct.unpack('<I', source_itdb_full[_off + 8:_off + 12])[0]
                _dtype = struct.unpack('<I', source_itdb_full[_off + 12:_off + 16])[0]
                if _dtype == 1:  # tracks dataset
                    _mhlt_off = _off + struct.unpack('<I', source_itdb_full[_off + 4:_off + 8])[0]
                    _mhlt_hdr = struct.unpack('<I', source_itdb_full[_mhlt_off + 4:_mhlt_off + 8])[0]
                    _tc = struct.unpack('<I', source_itdb_full[_mhlt_off + 8:_mhlt_off + 12])[0]
                    if _tc > 0:
                        _mhit_off = _mhlt_off + _mhlt_hdr
                        reference_info['mhit_header_size'] = struct.unpack('<I', source_itdb_full[_mhit_off + 4:_mhit_off + 8])[0]
                    break
                _off += _stotal

            logger.debug("Using reference database fields: db_id_2=%016X, lib_pid=%016X, "
                         "version=0x%X, mhsd_types=%s, mhit_hdr=%s",
                         reference_info['db_id_2'], reference_info['db_persistent_id'],
                         reference_info.get('version', 0),
                         sorted(ref_mhsd_types),
                         hex(reference_info.get('mhit_header_size', 0)))
        except Exception as e:
            logger.warning("Could not extract reference info: %s", e)
            reference_info = None

    # --- Generate db_ids for all tracks BEFORE artwork ---
    # write_mhit() generates db_ids lazily, but we need them now so
    # write_artworkdb can match tracks to PC file paths.
    from .mhit_writer import generate_db_id
    for track in tracks:
        if track.db_id == 0:
            track.db_id = generate_db_id()

    # --- Write ArtworkDB if PC file paths provided ---
    pending_artwork = None  # PendingArtworkWrite if defer_commit used
    if pc_file_paths:
        logger.debug("ART: pc_file_paths has %d entries, tracks has %d tracks",
                     len(pc_file_paths), len(tracks))

        # Remap pc_file_paths: the sync executor may have used id(track_info) as keys
        # because db_ids weren't assigned yet. Now that db_ids are assigned, remap.
        remapped_paths: dict[int, str] = {}
        obj_id_to_db_id = {id(t): t.db_id for t in tracks}
        remap_count = 0
        for key, path in pc_file_paths.items():
            if key in obj_id_to_db_id:
                # Key is an object id — remap to db_id
                remapped_paths[obj_id_to_db_id[key]] = path
                remap_count += 1
            elif isinstance(key, int) and key > 0:
                # Key is already a db_id (from matched_pc_paths)
                remapped_paths[key] = path

        logger.debug("ART: remapped %d new-track paths from object-id to db_id, "
                     "%d existing-track paths kept by db_id",
                     remap_count, len(remapped_paths) - remap_count)
        pc_file_paths = remapped_paths

        # Log sample of pc_file_paths
        for i, (db_id, path) in enumerate(list(pc_file_paths.items())[:5]):
            # Find track title for this db_id
            title = "?"
            for t in tracks:
                if t.db_id == db_id:
                    title = t.title
                    break
            logger.debug("ART:   [%d] db_id=%d title='%s' path=%s", i, db_id, title, path)

        # Check how many tracks have matching pc_file_paths
        matched = sum(1 for t in tracks if t.db_id in pc_file_paths)
        logger.debug("ART: %d/%d tracks have a PC source path", matched, len(tracks))

        try:
            from ArtworkDB_Writer.artwork_writer import write_artworkdb, PendingArtworkWrite
            ref_artdb = os.path.join(ipod_path, "iPod_Control", "Artwork", "ArtworkDB")
            ref_artdb_path = ref_artdb if os.path.exists(ref_artdb) else None

            art_result = write_artworkdb(
                ipod_path=ipod_path,
                tracks=tracks,
                pc_file_paths=pc_file_paths,
                reference_artdb_path=ref_artdb_path,
                defer_commit=True,
            )

            # Extract the mapping — works for both deferred and immediate results
            if isinstance(art_result, PendingArtworkWrite):
                pending_artwork = art_result
                db_id_to_img_id = art_result.db_id_to_art_info
            else:
                pending_artwork = None
                db_id_to_img_id = art_result

            if db_id_to_img_id:
                # Update mhii_link and artwork_size on tracks
                art_count = 0
                for track in tracks:
                    art_info = db_id_to_img_id.get(track.db_id)
                    if art_info:
                        img_id, src_img_size = art_info
                        track.mhii_link = img_id
                        track.artwork_count = 1
                        track.artwork_size = src_img_size
                        art_count += 1
                    else:
                        # Clear stale art references — ArtworkDB was rewritten
                        # so old img_ids no longer exist
                        track.mhii_link = 0
                        track.artwork_count = 0
                        track.artwork_size = 0
                logger.debug("ART: linked %d/%d tracks to %d unique images",
                             art_count, len(tracks), len(db_id_to_img_id))
                for t in tracks[:5]:
                    logger.debug("ART:   '%s' mhii_link=%d artwork_count=%d artwork_size=%d",
                                 t.title, t.mhii_link, t.artwork_count, t.artwork_size)
            else:
                logger.warning("ART: write_artworkdb returned empty dict — no artwork was generated")
        except Exception as e:
            logger.error("ART: ArtworkDB write failed: %s", e, exc_info=True)
    else:
        logger.debug("ART: pc_file_paths is %s — skipping ArtworkDB",
                     'None' if pc_file_paths is None else 'empty dict')

    # Extract preserved MHSD blobs (Genius data, types 6+) from existing database
    preserved_blobs: list[bytes] = []
    if existing_itdb:
        preserved_blobs = extract_preserved_mhsd_blobs(existing_itdb)

    # Build database with reference info
    itdb_data = bytearray(write_mhbd(
        tracks, db_id, reference_info=reference_info,
        playlists_type2=playlists, playlists_type5=smart_playlists,
        preserved_mhsd_blobs=preserved_blobs,
        capabilities=capabilities,
        master_playlist_name=master_playlist_name,
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
        import zlib
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

    # Detect checksum type (or use forced type)
    # Use reference or existing database as the source for hash extraction
    source_itdb = reference_itdb or existing_itdb

    if force_checksum is not None:
        checksum_type = force_checksum
        logger.debug("Using forced checksum type: %s", checksum_type.name)
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

        # Step 1: Write HASH72 first (if reference has it)
        if source_itdb and len(source_itdb) >= 0xA0 and source_itdb[0x72:0x74] == bytes([0x01, 0x00]):
            from .hash72 import extract_hash_info_to_dict, _compute_itunesdb_sha1, _hash_generate
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
                from device_info import get_firewire_id
                firewire_id = get_firewire_id(ipod_path)
            except Exception as e:
                logger.warning("Could not get FireWire ID: %s", e)

        if firewire_id:
            write_hash58(itdb_data, firewire_id)
            logger.info("HASH58 signature computed with FireWire ID: %s", firewire_id.hex())
        elif source_itdb and len(source_itdb) >= 0x6C and source_itdb[0x58:0x6C] != bytes(20):
            # Last resort: copy hash58 from reference database
            # NOTE: This is WRONG if the database content changed! hash58 is content-dependent.
            # This fallback only works if the database is byte-identical to the reference.
            itdb_data[0x58:0x6C] = source_itdb[0x58:0x6C]
            logger.warning("HASH58 copied from reference (content-dependent — may be invalid!)")
            logger.warning("  To fix: connect iPod so FireWire GUID can be read from USB serial")
        else:
            logger.error("No FireWire ID and no reference hash58 — database will be rejected!")

        # Set hashing_scheme to 1 (hash58 is the primary scheme)
        struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 1)

    elif checksum_type == ChecksumType.HASH72:
        # Try to get hash info from centralized store first, then fall back to disk
        from .hash72 import extract_hash_info_to_dict, read_hash_info, _compute_itunesdb_sha1, _hash_generate, HashInfo

        hash_info = None
        try:
            from device_info import get_current_device
            dev = get_current_device()
            if dev and dev.hash_info_iv and dev.hash_info_rndpart:
                hash_info = HashInfo(uuid=b'\x00' * 20, rndpart=dev.hash_info_rndpart, iv=dev.hash_info_iv)
                logger.debug("HashInfo loaded from centralized device store")
        except Exception:
            pass

        if hash_info is None:
            # Fallback: read_hash_info checks the store again (harmless)
            # then reads from disk if needed
            try:
                hash_info = read_hash_info(ipod_path)
            except Exception:
                pass

        if hash_info is None:
            # Try to extract from reference database
            source_itdb = reference_itdb or existing_itdb
            if source_itdb:
                logger.debug("Attempting to extract hash info from reference database...")
                hash_dict = extract_hash_info_to_dict(source_itdb)
                if hash_dict:
                    logger.debug("  IV: %s", hash_dict['iv'].hex())
                    logger.debug("  rndpart: %s", hash_dict['rndpart'].hex())

                    # Compute SHA1 of new database
                    sha1 = _compute_itunesdb_sha1(itdb_data)

                    # Generate new signature
                    signature = _hash_generate(sha1, hash_dict['iv'], hash_dict['rndpart'])

                    # Write to database
                    itdb_data[0x72:0x72 + 46] = signature
                    # Set hash_scheme=1 to match iTunes behavior
                    # (iTunes writes both hash58 and hash72, with hash_scheme=1)
                    struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 1)
                    logger.info("HASH72 signature written successfully")
                else:
                    logger.warning("Could not extract hash info from reference database")
            else:
                logger.warning("No HashInfo file and no reference database available")
        else:
            # Use existing HashInfo file
            sha1 = _compute_itunesdb_sha1(itdb_data)
            signature = _hash_generate(sha1, hash_info.iv, hash_info.rndpart)
            itdb_data[0x72:0x72 + 46] = signature
            # Set hash_scheme=1 to match iTunes behavior
            struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 1)
            logger.info("HASH72 signature written from HashInfo file")

    elif checksum_type == ChecksumType.HASHAB:
        # iPod Nano 6G/7G — white-box AES via WASM module
        # Requires FireWire ID (same as HASH58)
        if firewire_id is None:
            try:
                from device_info import get_firewire_id
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
                logger.error("HASHAB dependency missing: %s", e)
                if pending_artwork:
                    pending_artwork.abort()
                return False
            except FileNotFoundError as e:
                logger.error("HASHAB WASM module missing: %s", e)
                if pending_artwork:
                    pending_artwork.abort()
                return False
        else:
            logger.error(
                "No FireWire ID available — cannot compute HASHAB. "
                "Ensure the iPod is connected so the FireWire GUID can be "
                "read from USB serial number."
            )
            if pending_artwork:
                pending_artwork.abort()
            return False

    elif checksum_type == ChecksumType.UNSUPPORTED:
        logger.error("Device requires an unsupported hashing scheme")
        if pending_artwork:
            pending_artwork.abort()
        return False
    else:
        # ChecksumType.NONE or UNKNOWN - set hash_scheme to 0
        struct.pack_into('<H', itdb_data, MHBD_OFFSET_HASHING_SCHEME, 0)

    # Backup existing file(s)
    if backup:
        for _bpath in (itdb_path, existing_itdb_path):
            if _bpath and os.path.exists(_bpath):
                try:
                    shutil.copy2(_bpath, _bpath + ".backup")
                except Exception as e:
                    logger.warning("Could not backup %s: %s", os.path.basename(_bpath), e)

    # Write atomically — os.replace is atomic on NTFS and POSIX
    temp_path = itdb_path + ".tmp"
    try:
        with open(temp_path, 'wb') as f:
            f.write(itdb_data)
            f.flush()
            os.fsync(f.fileno())

        # Commit ArtworkDB and ithmb files FIRST (before swapping CDB),
        # then swap CDB.  Both happen here to ensure they stay in sync.
        if pending_artwork:
            pending_artwork.commit()
            logger.info("ART: committed ArtworkDB + ithmb files")

        os.replace(temp_path, itdb_path)

        # Truncate the stale database file to 0 bytes if the filename changed
        # (e.g. migrating from iTunesDB → iTunesCDB or vice versa).
        # libgpod truncates rather than deletes because some firmwares may
        # check for the file's existence and behave unexpectedly if it's gone.
        if existing_itdb_path and existing_itdb_path != itdb_path:
            try:
                with open(existing_itdb_path, 'wb') as f:
                    f.truncate(0)
                logger.info("Truncated stale %s to 0 bytes (now using %s)",
                            os.path.basename(existing_itdb_path), db_filename)
            except Exception as e:
                logger.warning("Could not truncate stale %s: %s",
                               os.path.basename(existing_itdb_path), e)

        logger.info("Wrote %s (%d bytes%s)", db_filename, len(itdb_data),
                    f", uncompressed {uncompressed_size}" if db_filename == "iTunesCDB" else "")
        return True

    except Exception as e:
        logger.error("Error writing iTunesDB: %s", e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        # Note: if we reached this point, pending_artwork was already
        # committed (it happens before os.replace for the CDB).  A CDB
        # write failure after artwork commit is unlikely (same filesystem)
        # but if it happens the artwork is still in sync with the CDB
        # data that was built from the same track list.
        return False
