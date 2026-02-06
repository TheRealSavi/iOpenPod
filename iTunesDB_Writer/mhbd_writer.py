"""
MHBD Writer - Write complete iTunesDB database files.

This is the top-level writer that assembles all components into
a valid iTunesDB file.

Database structure (based on libgpod order):
  mhbd (database header)
    mhsd type 1 (tracks dataset)
      mhlt (track list)
        mhit (track) × N
          mhod (string) × M
    mhsd type 3 (podcasts dataset)
      mhlp (podcast playlist list)
    mhsd type 2 (playlists dataset)
      mhlp (playlist list)
        mhyp (master playlist) - REQUIRED
          mhip (track ref) × N
        mhyp (user playlist) × M
    mhsd type 4 (albums dataset)
      mhla (album list)
    mhsd type 5 (smart playlists dataset)
      mhlp (smart playlist list)
"""

import struct
import random
import os
import shutil
import time
from typing import List, Optional

from .mhlt_writer import write_mhlt
from .mhsd_writer import write_mhsd_tracks, write_mhsd_playlists, write_mhsd_albums, write_mhsd_podcasts, write_mhsd_smart_playlists
from .mhlp_writer import write_mhlp_empty, write_mhlp_with_master
from .mhla_writer import write_mhla
from .mhit_writer import TrackInfo
from .device import detect_checksum_type, ChecksumType
from .hash58 import write_hash58
from .hash72 import write_hash72


# MHBD header size (version 0x4F+)
MHBD_HEADER_SIZE = 244

# Database version - using 0x4F (79) which is widely compatible
DATABASE_VERSION = 0x4F


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


def generate_database_id() -> int:
    """Generate a random 64-bit database ID."""
    return random.getrandbits(64)


def write_mhbd(
    tracks: List[TrackInfo],
    db_id: Optional[int] = None,
    language: str = "en",
    reference_info: Optional[dict] = None,
) -> bytes:
    """
    Write a complete iTunesDB database.

    Args:
        tracks: List of TrackInfo objects to include
        db_id: Database ID (generated if not provided)
        language: 2-letter language code
        reference_info: Dict from extract_db_info() to copy device-specific fields

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

    # Assign album_id to each track based on album_map
    for track in tracks:
        album_name = track.album or ""
        album_artist = track.album_artist or track.artist or ""
        key = (album_name, album_artist)
        track.album_id = album_map.get(key, 0)

    # Build track list (Type 1 dataset)
    # This also returns next_track_id which tells us track IDs used
    mhlt_data, next_track_id = write_mhlt(tracks, id_0x24=id_0x24)
    mhsd_tracks = write_mhsd_tracks(mhlt_data)

    # Collect all track IDs for the master playlist
    # Track IDs are sequential starting from 1
    track_ids = list(range(1, next_track_id))

    # Build playlist list WITH master playlist (Type 2 dataset)
    # The master playlist is REQUIRED and must reference ALL tracks
    # Pass tracks so master playlist can generate library index MHODs (type 52/53)
    mhlp_data = write_mhlp_with_master(track_ids, device_name="iPod", tracks=tracks, id_0x24=id_0x24)
    mhsd_playlists = write_mhsd_playlists(mhlp_data)

    # Build podcast list (Type 3 dataset)
    # libgpod writes type 3 with the SAME playlist data as type 2,
    # just with the MHSD type byte set to 3. An empty podcast section
    # causes the iPod Classic to reject the database.
    mhsd_podcasts = write_mhsd_podcasts(mhlp_data)

    # Build empty smart playlist list (Type 5 dataset)
    mhlp_smart = write_mhlp_empty()
    mhsd_smart = write_mhsd_smart_playlists(mhlp_smart)

    # Concatenate all datasets
    # Order observed in iTunes-generated clean database: Type 4, 1, 3, 2, 5
    # (albums, tracks, podcasts, playlists, smart playlists)
    all_datasets = mhsd_albums + mhsd_tracks + mhsd_podcasts + mhsd_playlists + mhsd_smart

    # Total file length
    total_length = MHBD_HEADER_SIZE + len(all_datasets)

    # Number of child datasets
    child_count = 5  # albums, tracks, podcasts, playlists, smart playlists

    # Build MHBD header
    # Layout based on libgpod mk_mhbd() and MhbdHeader struct
    header = bytearray(MHBD_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhbd'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHBD_HEADER_SIZE)

    # +0x08: Total length (entire file)
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: Unknown (always 1)
    struct.pack_into('<I', header, 0x0C, 1)

    # +0x10: Version
    struct.pack_into('<I', header, 0x10, DATABASE_VERSION)

    # +0x14: Child count (number of MHSDs)
    struct.pack_into('<I', header, 0x14, child_count)

    # +0x18: Database ID (64-bit)
    struct.pack_into('<Q', header, 0x18, db_id)

    # +0x20: Platform (1 = Mac, 2 = Windows)
    struct.pack_into('<H', header, 0x20, 2)  # Windows

    # +0x22: unk_0x22 - iTunes version indicator
    # Value 611 observed in working databases
    struct.pack_into('<H', header, 0x22, reference_info.get('unk_0x22', 611) if reference_info else 611)

    # +0x24: id_0x24 (8 bytes) - secondary 64-bit ID
    # Already generated above and written into every MHIT at offset 0x124
    struct.pack_into('<Q', header, 0x24, id_0x24)

    # +0x2C: unk_0x2c
    struct.pack_into('<I', header, 0x2C, 0)

    # +0x30: hashing_scheme (0=none, 1=hash58, 2=hash72, 4=hashAB)
    # Default to hash58 (1) - will be updated by write_checksum() if needed
    struct.pack_into('<H', header, 0x30, 1)

    # +0x32: unk_0x32[20] - padding, leave zeros

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
    struct.pack_into('<I', header, 0x50, 1)

    # +0x54: unk_0x54 - observed value 15 in working databases
    struct.pack_into('<I', header, 0x54, 15)

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

    # +0x70: unk_0x70 - observed value 3 in working databases
    struct.pack_into('<H', header, 0x70, reference_info.get('unk_0x70', 3) if reference_info else 3)

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

    Returns:
        True if successful
    """
    itdb_path = os.path.join(ipod_path, "iPod_Control", "iTunes", "iTunesDB")

    # Read existing database for reference (for db_id and hash info extraction)
    existing_itdb = None
    if os.path.exists(itdb_path):
        try:
            with open(itdb_path, 'rb') as f:
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
        try:
            # Create a temp file to use extract_db_info or manually extract
            reference_info = {
                'db_id': struct.unpack('<Q', source_itdb[0x18:0x20])[0],
                'platform': struct.unpack('<H', source_itdb[0x20:0x22])[0],
                'unk_0x22': struct.unpack('<H', source_itdb[0x22:0x24])[0],
                'id_0x24': struct.unpack('<Q', source_itdb[0x24:0x2C])[0],
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
            print(f"Using reference database fields: id_0x24={reference_info['id_0x24']:016X}, lib_pid={reference_info['lib_persistent_id']:016X}")
        except Exception as e:
            print(f"Warning: Could not extract reference info: {e}")
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
        print(f"ART: pc_file_paths has {len(pc_file_paths)} entries, tracks has {len(tracks)} tracks")

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

        print(f"ART: remapped {remap_count} new-track paths from object-id to dbid, "
              f"{len(remapped_paths) - remap_count} existing-track paths kept by dbid")
        pc_file_paths = remapped_paths

        # Log sample of pc_file_paths
        for i, (dbid, path) in enumerate(list(pc_file_paths.items())[:5]):
            # Find track title for this dbid
            title = "?"
            for t in tracks:
                if t.dbid == dbid:
                    title = t.title
                    break
            print(f"ART:   [{i}] dbid={dbid} title='{title}' path={path}")

        # Check how many tracks have matching pc_file_paths
        matched = sum(1 for t in tracks if t.dbid in pc_file_paths)
        print(f"ART: {matched}/{len(tracks)} tracks have a PC source path")

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
                print(f"ART: linked {art_count}/{len(tracks)} tracks to {len(dbid_to_imgid)} unique images")
                # Log sample of linked tracks
                for t in tracks[:5]:
                    print(f"ART:   '{t.title}' mhii_link={t.mhii_link} artwork_count={t.artwork_count} artwork_size={t.artwork_size}")
            else:
                print("ART: write_artworkdb returned EMPTY dict — no artwork was generated")
        except Exception as e:
            print(f"ART ERROR: ArtworkDB write failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"ART: pc_file_paths is {'None' if pc_file_paths is None else 'empty dict'} — skipping ArtworkDB")

    # Build database with reference info
    itdb_data = bytearray(write_mhbd(tracks, db_id, reference_info=reference_info))

    # Detect checksum type (or use forced type)
    # Use reference or existing database as the source for hash extraction
    source_itdb = reference_itdb or existing_itdb

    if force_checksum is not None:
        checksum_type = force_checksum
        print(f"Using forced checksum type: {checksum_type.name}")
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
                # iPod Classic pattern: hash_scheme=1 with BOTH hashes
                # This requires copying hash58 (we can't compute it without FireWire ID)
                # and regenerating hash72 (we can extract IV/rndpart)
                checksum_type = ChecksumType.HASH58
                print("Detected iPod Classic pattern (hash_scheme=1 with both hashes)")
            elif has_valid_hash72:
                checksum_type = ChecksumType.HASH72
                print("Detected valid HASH72 signature in existing database")
            elif existing_scheme == 1:
                checksum_type = ChecksumType.HASH58
                print("Detected HASH58 from existing database")
            elif existing_scheme == 2:
                checksum_type = ChecksumType.HASH72
                print("Detected HASH72 from existing database")

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
                print(f"HASH72 signature written first (hash58 depends on it)")

        # Step 2: Write HASH58 (HMAC-SHA1 using key derived from device FireWire GUID)
        # Try to get FireWire ID from parameter, SysInfo, SysInfoExtended, or Windows registry
        if firewire_id is None:
            try:
                from .device import get_firewire_id
                firewire_id = get_firewire_id(ipod_path)
            except Exception as e:
                print(f"Warning: Could not get FireWire ID: {e}")

        if firewire_id:
            write_hash58(itdb_data, firewire_id)
            print(f"HASH58 signature computed with FireWire ID: {firewire_id.hex()}")
        elif source_itdb and len(source_itdb) >= 0x6C and source_itdb[0x58:0x6C] != bytes(20):
            # Last resort: copy hash58 from reference database
            # NOTE: This is WRONG if the database content changed! hash58 is content-dependent.
            # This fallback only works if the database is byte-identical to the reference.
            itdb_data[0x58:0x6C] = source_itdb[0x58:0x6C]
            print(f"WARNING: HASH58 copied from reference (content-dependent — may be invalid!)")
            print(f"  To fix: connect iPod so FireWire GUID can be read from USB serial")
        else:
            print("ERROR: No FireWire ID and no reference hash58 — database will be rejected!")

        # hash_scheme is already set to 1 in write_mhbd

    elif checksum_type == ChecksumType.HASH72:
        # Try to extract hash info from reference or existing database
        from .hash72 import extract_hash_info_to_dict, read_hash_info, _compute_itunesdb_sha1, _hash_generate

        hash_info = read_hash_info(ipod_path)

        if hash_info is None:
            # Try to extract from reference database
            source_itdb = reference_itdb or existing_itdb
            if source_itdb:
                print("Attempting to extract hash info from reference database...")
                hash_dict = extract_hash_info_to_dict(source_itdb)
                if hash_dict:
                    print(f"  IV: {hash_dict['iv'].hex()}")
                    print(f"  rndpart: {hash_dict['rndpart'].hex()}")

                    # Compute SHA1 of new database
                    sha1 = _compute_itunesdb_sha1(itdb_data)

                    # Generate new signature
                    signature = _hash_generate(sha1, hash_dict['iv'], hash_dict['rndpart'])

                    # Write to database
                    itdb_data[0x72:0x72 + 46] = signature
                    # Keep hash_scheme = 1 (already set in write_mhbd) to match iTunes behavior
                    # iTunes writes both hash58 and hash72, with hash_scheme=1
                    print("HASH72 signature written successfully!")
                else:
                    print("Warning: Could not extract hash info from reference database")
            else:
                print("Warning: No HashInfo file and no reference database available")
        else:
            # Use existing HashInfo file
            sha1 = _compute_itunesdb_sha1(itdb_data)
            signature = _hash_generate(sha1, hash_info.iv, hash_info.rndpart)
            itdb_data[0x72:0x72 + 46] = signature
            # Keep hash_scheme = 1 (already set in write_mhbd) to match iTunes behavior
            print("HASH72 signature written from HashInfo file")

    elif checksum_type == ChecksumType.UNSUPPORTED:
        print("Error: Device requires HASHAB which is not supported")
        return False
    else:
        # ChecksumType.NONE or UNKNOWN - set hash_scheme to 0
        struct.pack_into('<H', itdb_data, 0x30, 0)

    # Backup existing file
    if backup and os.path.exists(itdb_path):
        backup_path = itdb_path + ".backup"
        try:
            shutil.copy2(itdb_path, backup_path)
        except Exception as e:
            print(f"Warning: Could not backup iTunesDB: {e}")

    # Write atomically
    temp_path = itdb_path + ".tmp"
    try:
        with open(temp_path, 'wb') as f:
            f.write(itdb_data)

        # Replace original
        if os.path.exists(itdb_path):
            os.remove(itdb_path)
        os.rename(temp_path, itdb_path)

        return True

    except Exception as e:
        print(f"Error writing iTunesDB: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def add_tracks_to_itunesdb(
    ipod_path: str,
    new_tracks: List[TrackInfo],
    backup: bool = True,
) -> bool:
    """
    Add tracks to an existing iTunesDB.

    This reads the existing database, parses the tracks, adds new ones,
    and writes back.

    Args:
        ipod_path: Mount point of iPod
        new_tracks: Tracks to add
        backup: Whether to backup existing iTunesDB

    Returns:
        True if successful
    """
    from iTunesDB_Parser import parse_itunesdb

    itdb_path = os.path.join(ipod_path, "iPod_Control", "iTunes", "iTunesDB")

    # Parse existing database
    if os.path.exists(itdb_path):
        existing = parse_itunesdb(itdb_path)
        existing_tracks = existing.get('mhlt', [])
        db_id = existing.get('DatabaseID')
    else:
        existing_tracks = []
        db_id = None

    # Convert existing tracks to TrackInfo objects
    converted_tracks = []
    for t in existing_tracks:
        track_info = TrackInfo(
            title=t.get('Title', 'Unknown'),
            location=t.get('Location', ''),
            size=t.get('size', 0),
            length=t.get('length', 0),
            filetype=t.get('filetype', 'mp3').lower().replace(' ', ''),
            bitrate=t.get('bitrate', 0),
            sample_rate=t.get('sampleRate', 44100),
            artist=t.get('Artist'),
            album=t.get('Album'),
            album_artist=t.get('Album Artist'),
            genre=t.get('Genre'),
            year=t.get('year', 0),
            track_number=t.get('trackNumber', 0),
            total_tracks=t.get('totalTracks', 0),
            disc_number=t.get('discNumber', 1),
            total_discs=t.get('totalDiscs', 1),
            rating=t.get('rating', 0),
            play_count=t.get('playCount', 0),
            skip_count=t.get('skipCount', 0),
            dbid=t.get('dbid', 0),
            date_added=t.get('dateAdded', 0),
            mhii_link=t.get('mhiiLink', 0),
        )
        converted_tracks.append(track_info)

    # Add new tracks
    all_tracks = converted_tracks + new_tracks

    # Write updated database
    return write_itunesdb(ipod_path, all_tracks, db_id, backup)
