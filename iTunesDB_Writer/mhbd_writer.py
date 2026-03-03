"""MHBD Writer — Write complete iTunesDB database files.

This is the top-level writer that assembles all components into
a valid iTunesDB (or iTunesCDB for Nano 5G+) file.

Dataset write order (matches libgpod):
  mhbd (database header, 244 bytes)
    mhsd type 1 (tracks dataset)
      mhlt (track list)
        mhit (track) × N
          mhod (string) × M
    mhsd type 3 (podcasts dataset) — MUST appear between types 1 and 2
      mhlp (playlist list) — same data as type 2
    mhsd type 2 (playlists dataset)
      mhlp (playlist list)
        mhyp (master playlist) — REQUIRED, always first
          mhod types 52/53 (library indices)
          mhip (track ref) × N
        mhyp (user playlist) × M
    mhsd type 4 (albums dataset)
      mhla (album list)
        mhia (album item) × N
    mhsd type 8 (artist list)
      mhli (artist list)
        mhii (artist item) × N
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
    write_mhsd_tracks, write_mhsd_playlists, write_mhsd_albums,
    write_mhsd_podcasts, write_mhsd_smart_playlists,
    write_mhsd_artists, write_mhsd_empty_stub,
    MHSD_TYPE_EMPTY_6, MHSD_TYPE_EMPTY_10,
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

logger = logging.getLogger(__name__)

# MHBD header size (version 0x4F+)
MHBD_HEADER_SIZE = 244

# Default database version — 0x4F (79) works for iPod Classic / Nano 3G+.
# For older devices, callers should pass `db_version` from
# ``ipod_models.DeviceCapabilities.db_version``.
DATABASE_VERSION_DEFAULT = 0x4F


def extract_db_info(itdb_path: str) -> dict:
    """
    Extract useful information from an existing iTunesDB.

    This can be used to get:
    - db_id: To preserve identity across rewrites
    - hash_scheme: What hash type is used
    - hash58/hash72: The actual hash values

    Args:
        itdb_path: Path to iTunesDB file

    Returns:
        Dictionary with extracted information
    """
    with open(itdb_path, 'rb') as f:
        data = f.read(244)  # Read header

    if data[:4] != b'mhbd':
        raise ValueError(f"Not an iTunesDB file: {itdb_path}")

    return {
        'db_id': struct.unpack('<Q', data[0x18:0x20])[0],
        'platform': struct.unpack('<H', data[0x20:0x22])[0],
        'unk_0x22': struct.unpack('<H', data[0x22:0x24])[0],
        'id_0x24': struct.unpack('<Q', data[0x24:0x2C])[0],
        'hash_scheme': struct.unpack('<H', data[0x30:0x32])[0],
        'unk_0x32': data[0x32:0x46],
        'language': data[0x46:0x48].decode('utf-8', errors='ignore'),
        'lib_persistent_id': struct.unpack('<Q', data[0x48:0x50])[0],
        'unk_0x50': struct.unpack('<I', data[0x50:0x54])[0],
        'unk_0x54': struct.unpack('<I', data[0x54:0x58])[0],
        'hash58': data[0x58:0x6C],
        'timezone': struct.unpack('<i', data[0x6C:0x70])[0],
        'unk_0x70': struct.unpack('<H', data[0x70:0x72])[0],
        'hash72': data[0x72:0xA0],
        'audio_language': struct.unpack('<H', data[0xA0:0xA2])[0],
        'subtitle_language': struct.unpack('<H', data[0xA2:0xA4])[0],
        'unk_0xa4': struct.unpack('<H', data[0xA4:0xA6])[0],
        'unk_0xa6': struct.unpack('<H', data[0xA6:0xA8])[0],
        'unk_0xa8': struct.unpack('<H', data[0xA8:0xAA])[0],
    }


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
        logger.info("Preserved %d extra MHSD blob(s) from existing database (Genius etc.)", len(blobs))
    return blobs


def generate_database_id() -> int:
    """Generate a random 64-bit database ID."""
    return random.getrandbits(64)


def write_mhbd(
    tracks: List[TrackInfo],
    db_id: Optional[int] = None,
    language: str = "en",
    reference_info: Optional[dict] = None,
    playlists: Optional[List[PlaylistInfo]] = None,
    smart_playlists: Optional[List[PlaylistInfo]] = None,
    preserved_mhsd_blobs: Optional[List[bytes]] = None,
    capabilities: Optional[DeviceCapabilities] = None,
) -> bytes:
    """
    Write a complete iTunesDB database.

    Args:
        tracks: List of TrackInfo objects to include
        db_id: Database ID (generated if not provided)
        language: 2-letter language code
        reference_info: Dict from extract_db_info() to copy device-specific fields
        playlists: List of PlaylistInfo for user playlists (dataset 2).
                   The master playlist is always generated automatically.
        smart_playlists: List of PlaylistInfo for dataset 5 smart playlists
                         (iPod browsing categories like Music, Movies, etc.)
        preserved_mhsd_blobs: Raw MHSD byte blobs (types 6+) extracted from
                              an existing database via extract_preserved_mhsd_blobs().
                              Appended verbatim after the 5 standard datasets to
                              preserve Genius and other iTunes-generated data.
        capabilities: Device capabilities from ``ipod_models``.  When provided,
                      ``db_version`` and ``supports_podcast`` are respected.

    Returns:
        Complete iTunesDB file content as bytes
    """
    if db_id is None:
        if reference_info and 'db_id' in reference_info:
            db_id = reference_info['db_id']
        else:
            db_id = generate_database_id()

    # Generate id_0x24 early - needed for both the MHBD header AND every MHIT
    if reference_info and 'id_0x24' in reference_info:
        id_0x24 = reference_info['id_0x24']
    else:
        id_0x24 = random.getrandbits(64)

    # Build album list first to get album IDs for tracks (Type 4 dataset)
    mhla_data, album_map = write_mhla(tracks)
    mhsd_albums = write_mhsd_albums(mhla_data)

    # Build artist list to get artist IDs for tracks (Type 8 dataset)
    mhli_data, artist_map = write_mhli(tracks)
    mhsd_artists = write_mhsd_artists(mhli_data)

    # Assign album_id and artist_id to each track
    from .mhla_writer import _album_key
    for track in tracks:
        key = _album_key(track)
        track.album_id = album_map.get(key, 0)

        # Artist ID from the artist list (case-insensitive lookup)
        artist_name = track.artist or ""
        if artist_name:
            track.artist_id = artist_map.get(artist_name.lower(), 0)

    # Build track list (Type 1 dataset)
    # This also returns next_track_id which tells us track IDs used
    mhlt_data, next_track_id = write_mhlt(tracks, id_0x24=id_0x24, capabilities=capabilities)
    mhsd_tracks = write_mhsd_tracks(mhlt_data)

    # Collect all track IDs for the master playlist
    # Track IDs are sequential starting from 1
    track_ids = list(range(1, next_track_id))

    # Build dbid → sequential track_id map so playlists can reference
    # tracks by their 32-bit MHIT trackID (not 64-bit dbid).
    # The sync executor stores dbids in PlaylistInfo.track_ids because
    # dbids are the stable identifier, but MHIP entries need 32-bit IDs.
    dbid_to_track_id: dict[int, int] = {}
    for i, track in enumerate(tracks):
        if track.dbid:
            dbid_to_track_id[track.dbid] = i + 1  # track IDs start at 1

    # Remap playlist track_ids from dbid → sequential track_id
    user_playlists = playlists or []
    for pl in user_playlists:
        pl.track_ids = [
            dbid_to_track_id[d] for d in pl.track_ids if d in dbid_to_track_id
        ]

    # Build playlist list WITH master playlist (Type 2 dataset)
    # The master playlist is REQUIRED and must reference ALL tracks
    # Pass tracks so master playlist can generate library index MHODs (type 52/53)
    user_playlists = playlists or []

    # Use the iPod's user-assigned name for the master playlist
    master_name = "iPod"
    try:
        from device_info import get_current_device
        dev = get_current_device()
        if dev and dev.ipod_name:
            master_name = dev.ipod_name
    except Exception:
        pass

    mhlp_data = write_mhlp_with_playlists(
        track_ids, playlists=user_playlists, device_name=master_name,
        tracks=tracks, id_0x24=id_0x24, capabilities=capabilities,
    )
    mhsd_playlists = write_mhsd_playlists(mhlp_data)

    # Build podcast list (Type 3 dataset)
    # libgpod writes type 3 with the SAME playlist data as type 2,
    # just with the MHSD type byte set to 3. An empty podcast section
    # causes the iPod Classic to reject the database.
    #
    # Pre-podcast devices (iPod 1G-3G, Mini 1G-2G, Shuffle 1G-2G)
    # don't understand type 3; skip it when capabilities say so.
    include_podcasts = True
    if capabilities is not None and not capabilities.supports_podcast:
        include_podcasts = False
    mhsd_podcasts = write_mhsd_podcasts(mhlp_data) if include_podcasts else b''

    # Build smart playlist list (Type 5 dataset)
    ds5_playlists = smart_playlists or []
    for pl in ds5_playlists:
        pl.track_ids = [
            dbid_to_track_id[d] for d in pl.track_ids if d in dbid_to_track_id
        ]
    mhlp_smart = write_mhlp_smart(ds5_playlists, id_0x24=id_0x24)
    mhsd_smart = write_mhsd_smart_playlists(mhlp_smart)

    # Concatenate all datasets
    #
    # Default order matches libgpod: Type 1, 3, 2, 4, 8, 6, 10, 5
    #   - Type 3 MUST appear between types 1 and 2 for podcast support
    #   - Type 1 MUST be first — older iPod firmware (Video 5G, Nano 1G-2G)
    #     may assume dataset[0] is the track list.
    #   - Types 8, 6, 10 come between albums (4) and smart playlists (5).
    #
    # When a reference database is available, we match its exact dataset
    # types.  For example, iTunes on Nano 6G writes only [4,8,1,3,5]
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
    mhsd_empty_6 = write_mhsd_empty_stub(MHSD_TYPE_EMPTY_6)
    mhsd_empty_10 = write_mhsd_empty_stub(MHSD_TYPE_EMPTY_10)

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
    dataset_entries.append((1, mhsd_tracks))  # always required
    if include_podcasts and _include(3):
        dataset_entries.append((3, mhsd_podcasts))
    if _include(2):
        dataset_entries.append((2, mhsd_playlists))
    dataset_entries.append((4, mhsd_albums))  # always required
    dataset_entries.append((8, mhsd_artists))  # always required
    if _include(6):
        dataset_entries.append((6, mhsd_empty_6))
    if _include(10):
        dataset_entries.append((10, mhsd_empty_10))
    if _include(5):
        dataset_entries.append((5, mhsd_smart))

    all_datasets = b''.join(data for _, data in dataset_entries)
    child_count = len(dataset_entries)
    logger.debug("Writing %d MHSD datasets: %s", child_count,
                 [t for t, _ in dataset_entries])

    # Append preserved MHSD blobs (Genius data, type 9 etc.) from original database.
    # Types 6, 8, 10 are generated above; only types we DON'T generate are preserved.
    extra_blobs = preserved_mhsd_blobs or []
    for blob in extra_blobs:
        all_datasets += blob
    child_count += len(extra_blobs)

    # Total file length
    total_length = MHBD_HEADER_SIZE + len(all_datasets)

    # Build MHBD header
    # Layout based on libgpod mk_mhbd() and MhbdHeader struct
    header = bytearray(MHBD_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhbd'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHBD_HEADER_SIZE)

    # +0x08: Total length (entire file)
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: 1 for most iPods, 2 for devices with compressed iTunesDB
    # (Nano 5G+, iPhone 3.0+).  iPod Classic 3G won't work if set to 2.
    # See libgpod mk_mhbd(): itdb_device_supports_compressed_itunesdb().
    unk_0x0c = 2 if (capabilities and capabilities.supports_compressed_db) else 1
    struct.pack_into('<I', header, 0x0C, unk_0x0c)

    # +0x10: Version — use the highest of reference, device-specific, or default.
    # The reference version reflects what was actually working on this device
    # (e.g. iTunes wrote 0x6F on Nano 6G).  We take max() to avoid regressing
    # when the reference is our own previous (possibly too-low) write.
    ref_version = reference_info.get('version', 0) if reference_info else 0
    cap_version = capabilities.db_version if capabilities else 0
    db_version = max(ref_version, cap_version, DATABASE_VERSION_DEFAULT)
    struct.pack_into('<I', header, 0x10, db_version)
    logger.debug("Using db_version=0x%X (ref=0x%X, cap=0x%X, default=0x%X)",
                 db_version, ref_version, cap_version, DATABASE_VERSION_DEFAULT)

    # +0x14: Child count (number of MHSDs)
    struct.pack_into('<I', header, 0x14, child_count)

    # +0x18: Database ID (64-bit)
    struct.pack_into('<Q', header, 0x18, db_id)

    # +0x20: Platform (1 = Mac, 2 = Windows)
    # NOTE: libgpod preserves this from the existing DB, but we recalculate
    # from the current OS. Firmware doesn't check this field.
    import sys
    platform_id = 2 if sys.platform == 'win32' else 1
    struct.pack_into('<H', header, 0x20, platform_id)

    # +0x22: unk_0x22 - iTunes version indicator
    # Value 611 observed in working databases
    struct.pack_into('<H', header, 0x22, reference_info.get('unk_0x22', 611) if reference_info else 611)

    # +0x24: id_0x24 (8 bytes) - secondary 64-bit ID
    # Already generated above and written into every MHIT at offset 0x124
    struct.pack_into('<Q', header, 0x24, id_0x24)

    # +0x2C: unk_0x2c
    struct.pack_into('<I', header, 0x2C, 0)

    # +0x30: hashing_scheme (0=none, 1=hash58, 2=hash72, 4=hashAB)
    # Default to 0 (none).  write_itunesdb() sets the correct value
    # after detecting/computing the checksum.  Baking in 1 here would
    # break pre-2007 iPods that don't use hashing.
    struct.pack_into('<H', header, 0x30, 0)

    # +0x32: unk_0x32[20] - preserve from reference if available (libgpod does this)
    if reference_info and 'unk_0x32' in reference_info:
        raw = reference_info['unk_0x32']
        if isinstance(raw, (bytes, bytearray)) and len(raw) == 20:
            header[0x32:0x46] = raw

    # +0x46: Language ID (2 bytes, e.g. "en")
    if reference_info and 'language' in reference_info:
        lang_bytes = reference_info['language'].encode('utf-8')[:2].ljust(2, b'\x00')
    else:
        lang_bytes = language.encode('utf-8')[:2].ljust(2, b'\x00')
    header[0x46:0x48] = lang_bytes

    # +0x48: Library Persistent ID (64-bit)
    # CRITICAL: This should be DIFFERENT from db_id! Use reference if available.
    if reference_info and 'lib_persistent_id' in reference_info:
        lib_pid = reference_info['lib_persistent_id']
    else:
        lib_pid = db_id  # Fallback to same as db_id
    struct.pack_into('<Q', header, 0x48, lib_pid)

    # +0x50: unk_0x50 - observed value 1 in working databases
    struct.pack_into('<I', header, 0x50, reference_info.get('unk_0x50', 1) if reference_info else 1)

    # +0x54: unk_0x54 - observed value 15 in working databases
    struct.pack_into('<I', header, 0x54, reference_info.get('unk_0x54', 15) if reference_info else 15)

    # +0x58: hash58[20] - will be filled by write_checksum()
    # Leave zeros

    # +0x6C: timezone_offset (signed) - observed -18000 (-5 hours EST)
    # Use reference timezone if available (device-specific setting)
    if reference_info and 'timezone' in reference_info:
        tz_offset = reference_info['timezone']
    else:
        # Get local timezone offset in seconds
        if time.daylight:
            tz_offset = -time.altzone
        else:
            tz_offset = -time.timezone
    struct.pack_into('<i', header, 0x6C, tz_offset)

    # +0x70: unk_0x70 - libgpod sets this based on checksum type:
    #   HASHAB → 4, HASH72 → 2, default → 0.
    if reference_info:
        unk_0x70 = reference_info.get('unk_0x70', 0)
    elif capabilities:
        _ck_to_0x70 = {ChecksumType.HASHAB: 4, ChecksumType.HASH72: 2}
        unk_0x70 = _ck_to_0x70.get(capabilities.checksum, 0)
    else:
        unk_0x70 = 0
    struct.pack_into('<H', header, 0x70, unk_0x70)

    # +0x72: hash72[46] - will be filled by write_checksum()
    # Leave zeros

    # +0xA0: audio_language, subtitle_language, etc.
    # Copy from reference if available - these seem device-specific
    if reference_info:
        struct.pack_into('<H', header, 0xA0, reference_info.get('audio_language', 0))
        struct.pack_into('<H', header, 0xA2, reference_info.get('subtitle_language', 0))
        struct.pack_into('<H', header, 0xA4, reference_info.get('unk_0xa4', 0))
        struct.pack_into('<H', header, 0xA6, reference_info.get('unk_0xa6', 0))
        struct.pack_into('<H', header, 0xA8, reference_info.get('unk_0xa8', 0))

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
        pc_file_paths: Dict mapping track dbid (int) → PC source file path (str)
                       for extracting embedded album art. If provided, ArtworkDB
                       and ithmb files will be written and mhii_link set on tracks.
        playlists: List of PlaylistInfo for user playlists (dataset 2).
                   The master playlist is always generated automatically.
        smart_playlists: List of PlaylistInfo for dataset 5 smart playlists.
        capabilities: Device capabilities from ``ipod_models``.  Auto-detected
                      from the current device if not provided.

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
            # Create a temp file to use extract_db_info or manually extract
            reference_info = {
                'db_id': struct.unpack('<Q', source_itdb[0x18:0x20])[0],
                'version': struct.unpack('<I', source_itdb[0x10:0x14])[0],
                'platform': struct.unpack('<H', source_itdb[0x20:0x22])[0],
                'unk_0x22': struct.unpack('<H', source_itdb[0x22:0x24])[0],
                'id_0x24': struct.unpack('<Q', source_itdb[0x24:0x2C])[0],
                'unk_0x32': bytes(source_itdb[0x32:0x46]),
                'language': source_itdb[0x46:0x48].decode('utf-8', errors='ignore'),
                'lib_persistent_id': struct.unpack('<Q', source_itdb[0x48:0x50])[0],
                'unk_0x50': struct.unpack('<I', source_itdb[0x50:0x54])[0],
                'unk_0x54': struct.unpack('<I', source_itdb[0x54:0x58])[0],
                'timezone': struct.unpack('<i', source_itdb[0x6C:0x70])[0],
                'unk_0x70': struct.unpack('<H', source_itdb[0x70:0x72])[0],
                'audio_language': struct.unpack('<H', source_itdb[0xA0:0xA2])[0],
                'subtitle_language': struct.unpack('<H', source_itdb[0xA2:0xA4])[0],
                'unk_0xa4': struct.unpack('<H', source_itdb[0xA4:0xA6])[0],
                'unk_0xa6': struct.unpack('<H', source_itdb[0xA6:0xA8])[0],
                'unk_0xa8': struct.unpack('<H', source_itdb[0xA8:0xAA])[0],
            }
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
            for _i in range(ref_cc):
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
                break  # only one pass needed

            logger.debug("Using reference database fields: id_0x24=%016X, lib_pid=%016X, "
                         "version=0x%X, mhsd_types=%s, mhit_hdr=%s",
                         reference_info['id_0x24'], reference_info['lib_persistent_id'],
                         reference_info.get('version', 0),
                         sorted(ref_mhsd_types),
                         hex(reference_info.get('mhit_header_size', 0)))
        except Exception as e:
            logger.warning("Could not extract reference info: %s", e)
            reference_info = None

    # --- Generate dbids for all tracks BEFORE artwork ---
    # write_mhit() generates dbids lazily, but we need them now so
    # write_artworkdb can match tracks to PC file paths.
    from .mhit_writer import generate_dbid
    for track in tracks:
        if track.dbid == 0:
            track.dbid = generate_dbid()

    # --- Write ArtworkDB if PC file paths provided ---
    if pc_file_paths:
        logger.debug("ART: pc_file_paths has %d entries, tracks has %d tracks",
                     len(pc_file_paths), len(tracks))

        # Remap pc_file_paths: the sync executor may have used id(track_info) as keys
        # because dbids weren't assigned yet. Now that dbids are assigned, remap.
        remapped_paths: dict[int, str] = {}
        obj_id_to_dbid = {id(t): t.dbid for t in tracks}
        remap_count = 0
        for key, path in pc_file_paths.items():
            if key in obj_id_to_dbid:
                # Key is an object id — remap to dbid
                remapped_paths[obj_id_to_dbid[key]] = path
                remap_count += 1
            elif isinstance(key, int) and key > 0:
                # Key is already a dbid (from matched_pc_paths)
                remapped_paths[key] = path

        logger.debug("ART: remapped %d new-track paths from object-id to dbid, "
                     "%d existing-track paths kept by dbid",
                     remap_count, len(remapped_paths) - remap_count)
        pc_file_paths = remapped_paths

        # Log sample of pc_file_paths
        for i, (dbid, path) in enumerate(list(pc_file_paths.items())[:5]):
            # Find track title for this dbid
            title = "?"
            for t in tracks:
                if t.dbid == dbid:
                    title = t.title
                    break
            logger.debug("ART:   [%d] dbid=%d title='%s' path=%s", i, dbid, title, path)

        # Check how many tracks have matching pc_file_paths
        matched = sum(1 for t in tracks if t.dbid in pc_file_paths)
        logger.debug("ART: %d/%d tracks have a PC source path", matched, len(tracks))

        try:
            from ArtworkDB_Writer import write_artworkdb
            ref_artdb = os.path.join(ipod_path, "iPod_Control", "Artwork", "ArtworkDB")
            ref_artdb_path = ref_artdb if os.path.exists(ref_artdb) else None

            dbid_to_imgid = write_artworkdb(
                ipod_path=ipod_path,
                tracks=tracks,
                pc_file_paths=pc_file_paths,
                reference_artdb_path=ref_artdb_path,
            )

            if dbid_to_imgid:
                # Update mhii_link and artwork_size on tracks
                art_count = 0
                for track in tracks:
                    art_info = dbid_to_imgid.get(track.dbid)
                    if art_info:
                        img_id, src_img_size = art_info
                        track.mhii_link = img_id
                        track.artwork_count = 1
                        track.artwork_size = src_img_size
                        art_count += 1
                    else:
                        # Clear stale art references — ArtworkDB was rewritten
                        # so old imgIds no longer exist
                        track.mhii_link = 0
                        track.artwork_count = 0
                        track.artwork_size = 0
                logger.debug("ART: linked %d/%d tracks to %d unique images",
                             art_count, len(tracks), len(dbid_to_imgid))
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
        playlists=playlists, smart_playlists=smart_playlists,
        preserved_mhsd_blobs=preserved_blobs,
        capabilities=capabilities,
    ))

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
        struct.pack_into('<H', itdb_data, 0x30, 1)

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
                    struct.pack_into('<H', itdb_data, 0x30, 1)
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
            struct.pack_into('<H', itdb_data, 0x30, 1)
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
                struct.pack_into('<H', itdb_data, 0x30, 3)
                logger.info("HASHAB signature computed with FireWire ID: %s",
                            firewire_id.hex())
            except ImportError as e:
                logger.error("HASHAB dependency missing: %s", e)
                return False
            except FileNotFoundError as e:
                logger.error("HASHAB WASM module missing: %s", e)
                return False
        else:
            logger.error(
                "No FireWire ID available — cannot compute HASHAB. "
                "Ensure the iPod is connected so the FireWire GUID can be "
                "read from USB serial number."
            )
            return False

    elif checksum_type == ChecksumType.UNSUPPORTED:
        logger.error("Device requires an unsupported hashing scheme")
        return False
    else:
        # ChecksumType.NONE or UNKNOWN - set hash_scheme to 0
        struct.pack_into('<H', itdb_data, 0x30, 0)

    # Backup existing file(s)
    if backup:
        for _bpath in (itdb_path, existing_itdb_path):
            if _bpath and os.path.exists(_bpath):
                try:
                    shutil.copy2(_bpath, _bpath + ".backup")
                except Exception as e:
                    logger.warning("Could not backup %s: %s", os.path.basename(_bpath), e)

    # ── Compress for iTunesCDB if needed ──────────────────────────────
    #   The on-disk format is: uncompressed mhbd header (244 bytes) +
    #   zlib-compressed payload (all mhsd children).  The total_length
    #   field in the header is patched to reflect the compressed file size.
    #
    #   libgpod uses Z_BEST_SPEED (level 1) and sets unk_0xA8 to 1
    #   to signal that the file is compressed.
    write_data: bytes | bytearray = itdb_data
    if db_filename == "iTunesCDB":
        import zlib
        hdr_len = struct.unpack_from('<I', itdb_data, 4)[0]
        payload = bytes(itdb_data[hdr_len:])
        compressed = zlib.compress(payload, 1)  # Z_BEST_SPEED — matches libgpod/iTunes
        cdb_header = bytearray(itdb_data[:hdr_len])
        # Patch total_length to compressed file size
        struct.pack_into('<I', cdb_header, 8, hdr_len + len(compressed))
        # Set unk_0xA8 = 1 to indicate compressed payload (per libgpod)
        struct.pack_into('<H', cdb_header, 0xA8, 1)
        write_data = bytes(cdb_header) + compressed
        logger.info("Compressed %d -> %d bytes for iTunesCDB (level 1)",
                    len(itdb_data), len(write_data))

    # Write atomically — os.replace is atomic on NTFS and POSIX
    temp_path = itdb_path + ".tmp"
    try:
        with open(temp_path, 'wb') as f:
            f.write(write_data)
            f.flush()
            os.fsync(f.fileno())

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

        logger.info("Wrote %s (%d bytes)", db_filename, len(itdb_data))
        return True

    except Exception as e:
        logger.error("Error writing iTunesDB: %s", e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False
