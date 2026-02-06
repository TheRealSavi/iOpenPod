"""
ArtworkDB Writer for iPod Classic.

Writes the ArtworkDB binary file and associated .ithmb image files.

ArtworkDB structure:
    mhfd (file header)
      mhsd type=1 → mhli → mhii[] (image entries, one per unique album art)
        Each mhii has MHOD type=2 children containing MHNI (one per image format)
        Each MHNI has an MHOD type=3 child with the ithmb filename
      mhsd type=2 → mhla (empty, not used for music artwork)
      mhsd type=3 → mhlf → mhif[] (one per image format, describes ithmb file sizes)
"""

import struct
import os
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from .rgb565 import IPOD_CLASSIC_FORMATS, convert_art_for_ipod
from .art_extractor import extract_art, art_hash

logger = logging.getLogger(__name__)

# Header sizes (from real iPod Classic ArtworkDB)
MHFD_HEADER_SIZE = 132
MHSD_HEADER_SIZE = 96
MHLI_HEADER_SIZE = 92
MHLA_HEADER_SIZE = 92
MHLF_HEADER_SIZE = 92
MHII_HEADER_SIZE = 152
MHOD_HEADER_SIZE = 24
MHNI_HEADER_SIZE = 76
MHIF_HEADER_SIZE = 124

# MHOD type 6 (unknown but present in real ArtworkDB)
# Contains an mhaf child: 96 bytes in-file (MHOD total=120 − header=24 = 96).
# The mhaf headerSize field = 96, but its totalSize field = 60 (meaning unclear).
MHAF_DATA_SIZE = 96


@dataclass
class ArtworkEntry:
    """Represents a unique album art image for the ArtworkDB."""
    img_id: int
    song_id: int          # dbid of one associated track
    art_hash: str         # MD5 hash for deduplication
    src_img_size: int     # Size of original source image
    # Per-format converted data: {format_id: {data, width, height, size, ...}}
    formats: dict = field(default_factory=dict)
    # Track dbids that use this artwork
    track_dbids: list = field(default_factory=list)


def _write_mhod_string(mhod_type: int, string: str) -> bytes:
    """Write an ArtworkDB MHOD string (type 1 or 3).

    Type 3 (ithmb filename) uses UTF-16LE encoding (encoding byte = 2),
    matching real iPod Classic databases.
    """
    # Type 3 (filename) uses UTF-16LE; others use UTF-8
    if mhod_type == 3:
        encoded = string.encode('utf-16-le')
        encoding_byte = 2
    else:
        encoded = string.encode('utf-8')
        encoding_byte = 1

    str_len = len(encoded)

    # Pad to 4-byte boundary
    padding = (4 - (str_len % 4)) % 4

    # String body: str_len(4) + encoding(1) + unk(3) + unk2(4) + string + padding
    body = struct.pack('<I', str_len)       # string byte length
    body += struct.pack('<B', encoding_byte)
    body += b'\x00' * 3                    # unknown
    body += b'\x00' * 4                    # unknown
    body += encoded
    body += b'\x00' * padding

    total_len = MHOD_HEADER_SIZE + len(body)

    # MHOD header
    header = bytearray(MHOD_HEADER_SIZE)
    header[0:4] = b'mhod'
    struct.pack_into('<I', header, 4, MHOD_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<H', header, 12, mhod_type)

    return bytes(header) + body


def _write_mhni(format_id: int, ithmb_offset: int, img_info: dict) -> bytes:
    """
    Write an MHNI (image name/location) chunk.

    Args:
        format_id: Correlation ID (1055, 1060, 1061)
        ithmb_offset: Byte offset within the ithmb file
        img_info: Dict with width, height, size from rgb565 conversion
    """
    # Write the filename MHOD (type 3) first to know total size
    filename = f":F{format_id}_1.ithmb"
    mhod3 = _write_mhod_string(3, filename)

    total_len = MHNI_HEADER_SIZE + len(mhod3)

    header = bytearray(MHNI_HEADER_SIZE)
    header[0:4] = b'mhni'
    struct.pack_into('<I', header, 4, MHNI_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<I', header, 12, 1)               # child count (1 = the filename MHOD)
    struct.pack_into('<I', header, 16, format_id)        # correlationID
    struct.pack_into('<I', header, 20, ithmb_offset)     # offset in ithmb file
    struct.pack_into('<I', header, 24, img_info['size'])  # image data size in bytes
    struct.pack_into('<h', header, 28, 0)                # vertical padding
    struct.pack_into('<h', header, 30, 0)                # horizontal padding
    struct.pack_into('<H', header, 32, img_info['height'])
    struct.pack_into('<H', header, 34, img_info['width'])
    # offset 36: unk1 = 0
    struct.pack_into('<I', header, 40, img_info['size'])  # imgSize2 (same as imgSize)

    return bytes(header) + mhod3


def _write_mhod_container(mhod_type: int, mhni_data: bytes) -> bytes:
    """Write a container MHOD (type 2 or 5) wrapping an MHNI."""
    total_len = MHOD_HEADER_SIZE + len(mhni_data)

    header = bytearray(MHOD_HEADER_SIZE)
    header[0:4] = b'mhod'
    struct.pack_into('<I', header, 4, MHOD_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<H', header, 12, mhod_type)

    return bytes(header) + mhni_data


def _write_mhod6() -> bytes:
    """
    Write MHOD type 6 (unknown purpose, present in real ArtworkDB).

    Contains an mhaf child.  In real iPod databases:
    - MHOD total = 120 (24 header + 96 data)
    - mhaf headerSize field = 96
    - mhaf totalSize field = 60
    - 96 bytes of mhaf data are actually present in the file
    """
    # mhaf child — 96 bytes in-file matching real iPod
    mhaf = bytearray(MHAF_DATA_SIZE)
    mhaf[0:4] = b'mhaf'
    struct.pack_into('<I', mhaf, 4, MHAF_DATA_SIZE)  # headerSize = 96
    struct.pack_into('<I', mhaf, 8, 60)               # totalSize = 60 (as in real iPod)
    # Rest is zeros

    total_len = MHOD_HEADER_SIZE + len(mhaf)  # 24 + 96 = 120

    header = bytearray(MHOD_HEADER_SIZE)
    header[0:4] = b'mhod'
    struct.pack_into('<I', header, 4, MHOD_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<H', header, 12, 6)  # type 6

    return bytes(header) + bytes(mhaf)


def _write_mhii(entry: ArtworkEntry, format_offsets: dict) -> bytes:
    """
    Write an MHII (image item) chunk.

    Args:
        entry: ArtworkEntry with converted format data
        format_offsets: {format_id: current_offset} for ithmb file positions
    """
    # Build MHOD children (one per format + MHOD type 6)
    children = []
    for fmt_id in sorted(entry.formats.keys()):
        img_info = entry.formats[fmt_id]
        offset = format_offsets.get(fmt_id, 0)
        mhni = _write_mhni(fmt_id, offset, img_info)
        mhod = _write_mhod_container(2, mhni)
        children.append(mhod)

    # Add MHOD type 6
    children.append(_write_mhod6())

    children_data = b''.join(children)
    total_len = MHII_HEADER_SIZE + len(children_data)

    header = bytearray(MHII_HEADER_SIZE)
    header[0:4] = b'mhii'
    struct.pack_into('<I', header, 4, MHII_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<I', header, 12, len(children))   # child count
    struct.pack_into('<I', header, 16, entry.img_id)     # imgId
    struct.pack_into('<Q', header, 20, entry.song_id)    # songId (dbid of first track)
    # offset 28: unk1 = 0
    # offset 32: rating = 0
    # offset 36: unk2 = 0
    # offset 40: originalDate = 0
    # offset 44: exifTakenDate = 0
    struct.pack_into('<I', header, 48, entry.src_img_size)  # source image size
    # offset 56: unk (real iPod had 9 here — unknown purpose)
    struct.pack_into('<I', header, 56, 9)
    # offset 60: unk (real iPod had 1 here — unknown purpose)
    struct.pack_into('<I', header, 60, 1)

    return bytes(header) + children_data


def _write_mhli(entries: list[ArtworkEntry], format_offsets_map: dict) -> bytes:
    """Write MHLI (image list) containing all MHII entries."""
    mhii_data = []
    for entry in entries:
        mhii = _write_mhii(entry, format_offsets_map[entry.img_id])
        mhii_data.append(mhii)

    children_data = b''.join(mhii_data)

    header = bytearray(MHLI_HEADER_SIZE)
    header[0:4] = b'mhli'
    struct.pack_into('<I', header, 4, MHLI_HEADER_SIZE)
    struct.pack_into('<I', header, 8, len(entries))  # count (NOT total_length for mhli)
    # Rest of header is zeros/padding

    return bytes(header) + children_data


def _write_mhla() -> bytes:
    """Write empty MHLA (album list, not used for music artwork)."""
    header = bytearray(MHLA_HEADER_SIZE)
    header[0:4] = b'mhla'
    struct.pack_into('<I', header, 4, MHLA_HEADER_SIZE)
    struct.pack_into('<I', header, 8, 0)  # count = 0
    return bytes(header)


def _write_mhif(format_id: int, image_size: int) -> bytes:
    """
    Write MHIF (file info) entry.

    Args:
        format_id: Correlation ID
        image_size: Size in bytes of ONE image in this format
    """
    header = bytearray(MHIF_HEADER_SIZE)
    header[0:4] = b'mhif'
    struct.pack_into('<I', header, 4, MHIF_HEADER_SIZE)
    struct.pack_into('<I', header, 8, MHIF_HEADER_SIZE)
    # offset 12: unk = 0
    struct.pack_into('<I', header, 16, format_id)    # correlationID
    struct.pack_into('<I', header, 20, image_size)   # image size per entry
    return bytes(header)


def _write_mhlf(format_ids: list[int], image_sizes: dict) -> bytes:
    """Write MHLF (file list) containing MHIF entries."""
    mhif_data = []
    for fmt_id in format_ids:
        mhif = _write_mhif(fmt_id, image_sizes[fmt_id])
        mhif_data.append(mhif)

    children_data = b''.join(mhif_data)

    header = bytearray(MHLF_HEADER_SIZE)
    header[0:4] = b'mhlf'
    struct.pack_into('<I', header, 4, MHLF_HEADER_SIZE)
    struct.pack_into('<I', header, 8, len(format_ids))  # count
    return bytes(header) + children_data


def _write_mhsd(ds_type: int, child_data: bytes) -> bytes:
    """Write MHSD (dataset) wrapping a child list."""
    total_len = MHSD_HEADER_SIZE + len(child_data)

    header = bytearray(MHSD_HEADER_SIZE)
    header[0:4] = b'mhsd'
    struct.pack_into('<I', header, 4, MHSD_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    struct.pack_into('<H', header, 12, ds_type)
    return bytes(header) + child_data


def _write_mhfd(datasets: list[bytes], next_mhii_id: int,
                reference_mhfd: Optional[bytes] = None) -> bytes:
    """
    Write MHFD (file header) for ArtworkDB.

    Args:
        datasets: List of serialized MHSD chunks
        next_mhii_id: Next available image ID
        reference_mhfd: Reference ArtworkDB to copy unk fields from
    """
    all_data = b''.join(datasets)
    total_len = MHFD_HEADER_SIZE + len(all_data)

    header = bytearray(MHFD_HEADER_SIZE)
    header[0:4] = b'mhfd'
    struct.pack_into('<I', header, 4, MHFD_HEADER_SIZE)
    struct.pack_into('<I', header, 8, total_len)
    # offset 12: unk1 = 0
    struct.pack_into('<I', header, 16, 6)                # unk2 = 6 (from real iPod Classic ArtworkDB)
    struct.pack_into('<I', header, 20, len(datasets))    # childCount
    # offset 24: unk3 = 0
    struct.pack_into('<I', header, 28, next_mhii_id)     # next_mhii_id

    # Copy unk4/unk5 from reference if available (unknown purpose but present)
    if reference_mhfd and len(reference_mhfd) >= 48:
        header[32:48] = reference_mhfd[32:48]

    struct.pack_into('<I', header, 48, 2)  # unk6 = 2 (always 2)

    # Copy unk9/unk10 from reference if available
    if reference_mhfd and len(reference_mhfd) >= 68:
        header[60:68] = reference_mhfd[60:68]

    return bytes(header) + all_data


def _read_existing_artwork(artworkdb_path: str, artwork_dir: str) -> dict:
    """
    Read existing artwork entries from ArtworkDB and ithmb files.

    Parses the binary ArtworkDB directly (not via the parser, which is lossy
    for multi-format MHII entries), then reads raw pixel data from existing
    ithmb files.

    Returns:
        Dict mapping imgId → {
            'song_id': int,
            'src_img_size': int,
            'formats': {format_id: bytes},  # raw RGB565 pixel data
        }
    """
    if not os.path.exists(artworkdb_path):
        return {}

    try:
        with open(artworkdb_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.warning(f"ART: failed to read existing ArtworkDB: {e}")
        return {}

    if len(data) < 32 or data[:4] != b'mhfd':
        return {}

    entries = {}

    # Walk mhfd → mhsd datasets → find type 1 (image list) → mhli → mhii[]
    mhfd_header_size = struct.unpack('<I', data[4:8])[0]
    child_count = struct.unpack('<I', data[20:24])[0]

    offset = mhfd_header_size
    for _ in range(child_count):
        if offset + 14 > len(data) or data[offset:offset + 4] != b'mhsd':
            break
        mhsd_header = struct.unpack('<I', data[offset + 4:offset + 8])[0]
        mhsd_total = struct.unpack('<I', data[offset + 8:offset + 12])[0]
        ds_type = struct.unpack('<H', data[offset + 12:offset + 14])[0]

        if ds_type == 1:
            # Image list dataset — walk mhli → mhii entries
            mhli_offset = offset + mhsd_header
            if mhli_offset + 12 <= len(data) and data[mhli_offset:mhli_offset + 4] == b'mhli':
                mhli_header = struct.unpack('<I', data[mhli_offset + 4:mhli_offset + 8])[0]
                mhii_count = struct.unpack('<I', data[mhli_offset + 8:mhli_offset + 12])[0]

                mhii_offset = mhli_offset + mhli_header
                for _ in range(mhii_count):
                    if mhii_offset + 52 > len(data) or data[mhii_offset:mhii_offset + 4] != b'mhii':
                        break
                    mhii_total = struct.unpack('<I', data[mhii_offset + 8:mhii_offset + 12])[0]
                    entry = _parse_mhii_existing(data, mhii_offset, artwork_dir)
                    if entry:
                        entries[entry['img_id']] = entry
                    mhii_offset += mhii_total

        offset += mhsd_total

    return entries


def _parse_mhii_existing(data: bytes, offset: int, artwork_dir: str) -> Optional[dict]:
    """
    Parse a single MHII entry from existing ArtworkDB and read its ithmb pixel data.

    Returns dict with img_id, song_id, src_img_size, formats (raw pixel data).
    """
    header_size = struct.unpack('<I', data[offset + 4:offset + 8])[0]
    child_count = struct.unpack('<I', data[offset + 12:offset + 16])[0]
    img_id = struct.unpack('<I', data[offset + 16:offset + 20])[0]
    song_id = struct.unpack('<Q', data[offset + 20:offset + 28])[0]
    src_img_size = struct.unpack('<I', data[offset + 48:offset + 52])[0]

    # Walk children to find MHOD type 2 containers wrapping MHNI entries
    formats = {}
    child_offset = offset + header_size
    for _ in range(child_count):
        if child_offset + 14 > len(data) or data[child_offset:child_offset + 4] != b'mhod':
            break
        mhod_header = struct.unpack('<I', data[child_offset + 4:child_offset + 8])[0]
        mhod_total = struct.unpack('<I', data[child_offset + 8:child_offset + 12])[0]
        mhod_type = struct.unpack('<H', data[child_offset + 12:child_offset + 14])[0]

        if mhod_type == 2:
            # Container MHOD with MHNI child
            mhni_offset = child_offset + mhod_header
            if (mhni_offset + 28 <= len(data) and data[mhni_offset:mhni_offset + 4] == b'mhni'):
                format_id = struct.unpack('<I', data[mhni_offset + 16:mhni_offset + 20])[0]
                ithmb_offset = struct.unpack('<I', data[mhni_offset + 20:mhni_offset + 24])[0]
                img_size = struct.unpack('<I', data[mhni_offset + 24:mhni_offset + 28])[0]

                # Read pixel data from ithmb file
                ithmb_path = os.path.join(artwork_dir, f"F{format_id}_1.ithmb")
                if os.path.exists(ithmb_path) and img_size > 0:
                    try:
                        with open(ithmb_path, 'rb') as f:
                            f.seek(ithmb_offset)
                            pixel_data = f.read(img_size)
                        if len(pixel_data) == img_size:
                            formats[format_id] = pixel_data
                    except Exception as e:
                        logger.debug(f"ART: failed to read ithmb data for imgId={img_id} "
                                     f"format={format_id}: {e}")

        child_offset += mhod_total

    if not formats:
        return None

    return {
        'img_id': img_id,
        'song_id': song_id,
        'src_img_size': src_img_size,
        'formats': formats,
    }


def write_artworkdb(
    ipod_path: str,
    tracks: list,
    pc_file_paths: Optional[dict] = None,
    start_img_id: int = 100,
    reference_artdb_path: Optional[str] = None,
) -> dict:
    """
    Write ArtworkDB and ithmb files for an iPod.

    This function:
    1. Extracts album art from PC source files
    2. Preserves existing art for tracks without PC source files
    3. Converts art to RGB565 at multiple sizes
    4. Writes ithmb files (pixel data)
    5. Writes ArtworkDB binary (metadata)
    6. Returns a mapping of track dbid → imgId for iTunesDB mhiiLink

    Args:
        ipod_path: iPod mount point (e.g., "E:" or "/media/ipod")
        tracks: List of track dicts or TrackInfo objects with at least 'dbid' and 'album'
        pc_file_paths: Dict mapping track dbid → PC source file path
                       (if None, tries to extract art from iPod copies)
        start_img_id: Starting image ID (default 100, matching iTunes behavior)
        reference_artdb_path: Path to existing ArtworkDB for copying header fields

    Returns:
        Dict mapping track dbid (int) → (imgId, src_img_size) tuple for
        setting mhiiLink and artworkSize on MHIT, or empty dict if no
        artwork found
    """
    artwork_dir = os.path.join(ipod_path, "iPod_Control", "Artwork")
    os.makedirs(artwork_dir, exist_ok=True)

    # Read reference ArtworkDB for header fields
    ref_mhfd = None
    if reference_artdb_path and os.path.exists(reference_artdb_path):
        with open(reference_artdb_path, 'rb') as f:
            ref_mhfd = f.read()

    # --- Step 0: Read existing artwork BEFORE we overwrite ithmb files ---
    artworkdb_path = os.path.join(artwork_dir, "ArtworkDB")
    existing_art = _read_existing_artwork(artworkdb_path, artwork_dir)
    if existing_art:
        logger.info(f"ART: read {len(existing_art)} existing image entries from ArtworkDB")

    # --- Step 1: Extract and deduplicate album art from PC files ---
    # Group tracks by art hash to create one MHII per unique image
    art_map = {}      # art_hash → art_bytes
    track_art = {}    # dbid → art_hash (or preserve_key)

    total_tracks = len(tracks)
    tracks_with_dbid = 0
    tracks_with_pc_path = 0
    tracks_pc_path_exists = 0
    tracks_art_extracted = 0
    tracks_no_art = 0

    for track in tracks:
        dbid = _get_track_field(track, 'dbid')
        if not dbid:
            title = _get_track_field(track, 'title') or '?'
            logger.warning(f"ART: track '{title}' has no dbid, skipping")
            continue
        tracks_with_dbid += 1

        # Try to get art from PC source file
        art_bytes = None
        if pc_file_paths and dbid in pc_file_paths:
            tracks_with_pc_path += 1
            pc_path = pc_file_paths[dbid]
            if os.path.exists(pc_path):
                tracks_pc_path_exists += 1
                art_bytes = extract_art(pc_path)
                if art_bytes:
                    tracks_art_extracted += 1
                else:
                    tracks_no_art += 1
                    title = _get_track_field(track, 'title') or '?'
                    logger.debug(f"ART: no embedded art in '{title}' ({pc_path})")
            else:
                title = _get_track_field(track, 'title') or '?'
                logger.warning(f"ART: PC file not found for '{title}': {pc_path}")

        if art_bytes is not None:
            h = art_hash(art_bytes)
            art_map[h] = art_bytes
            track_art[dbid] = h

    logger.info(f"ART STATS: {total_tracks} total tracks, "
                f"{tracks_with_dbid} with dbid, "
                f"{tracks_with_pc_path} with PC path, "
                f"{tracks_pc_path_exists} PC files exist, "
                f"{tracks_art_extracted} have art, "
                f"{tracks_no_art} have no art")

    # --- Step 1b: Preserve existing art for tracks without PC paths ---
    preserved_art = {}  # preserve_key → {formats: {fmt_id: bytes}, src_img_size, song_id}
    tracks_preserved = 0

    if existing_art:
        for track in tracks:
            dbid = _get_track_field(track, 'dbid')
            if not dbid or dbid in track_art:
                continue  # Already has new art from PC extraction

            # Check if this track had existing art via mhii_link
            mhii_link = _get_track_field(track, 'mhii_link')
            if not mhii_link:
                mhii_link = _get_track_field(track, 'mhiiLink')
            if not mhii_link or mhii_link not in existing_art:
                continue

            # Preserve this existing art entry
            preserve_key = f"__preserved_{mhii_link}"
            if preserve_key not in preserved_art:
                preserved_art[preserve_key] = existing_art[mhii_link]
            track_art[dbid] = preserve_key
            tracks_preserved += 1

    logger.info(f"ART STATS: {len(art_map)} new unique images, "
                f"{len(preserved_art)} preserved existing images, "
                f"{len(track_art)} total tracks with art "
                f"({tracks_art_extracted} new, {tracks_preserved} preserved)")

    if not art_map and not preserved_art:
        logger.info("No album art found (new or existing)")
        return {}

    logger.info(f"Found {len(art_map)} new + {len(preserved_art)} preserved = "
                f"{len(art_map) + len(preserved_art)} unique album art images "
                f"for {len(track_art)} tracks")

    # --- Step 2: Create ArtworkEntry objects ---
    entries = []
    img_id = start_img_id
    hash_to_imgid = {}  # art_hash/preserve_key → img_id

    # New art entries (converted from source JPEG/PNG)
    for h, art_bytes in art_map.items():
        # Find the first track dbid with this art (for songId)
        song_id = 0
        associated_dbids = []
        for dbid, th in track_art.items():
            if th == h:
                if song_id == 0:
                    song_id = dbid
                associated_dbids.append(dbid)

        entry = ArtworkEntry(
            img_id=img_id,
            song_id=song_id,
            art_hash=h,
            src_img_size=len(art_bytes),
            track_dbids=associated_dbids,
        )

        # Convert to each iPod format
        for fmt_id in sorted(IPOD_CLASSIC_FORMATS.keys()):
            result = convert_art_for_ipod(art_bytes, fmt_id)
            if result:
                entry.formats[fmt_id] = result

        if entry.formats:
            entries.append(entry)
            hash_to_imgid[h] = img_id
            img_id += 1

    # Preserved art entries (already in RGB565 format from existing ithmb files)
    for preserve_key, existing_entry in preserved_art.items():
        song_id = 0
        associated_dbids = []
        for dbid, th in track_art.items():
            if th == preserve_key:
                if song_id == 0:
                    song_id = dbid
                associated_dbids.append(dbid)

        entry = ArtworkEntry(
            img_id=img_id,
            song_id=song_id,
            art_hash=preserve_key,
            src_img_size=existing_entry['src_img_size'],
            track_dbids=associated_dbids,
        )

        # Use existing pixel data directly (already RGB565)
        for fmt_id, pixel_data in existing_entry['formats'].items():
            dims = IPOD_CLASSIC_FORMATS.get(fmt_id)
            if dims:
                w, h = dims
                entry.formats[fmt_id] = {
                    'data': pixel_data,
                    'width': w,
                    'height': h,
                    'size': len(pixel_data),
                }

        if entry.formats:
            entries.append(entry)
            hash_to_imgid[preserve_key] = img_id
            img_id += 1

    if not entries:
        logger.warning("Failed to convert any album art to iPod format")
        return {}

    # --- Step 3: Write ithmb files ---
    format_ids = sorted(IPOD_CLASSIC_FORMATS.keys())
    # Track current offset per format (for ithmb file append position)
    ithmb_offsets = {fmt_id: 0 for fmt_id in format_ids}
    # Map entry img_id → {format_id: offset} for MHNI
    format_offsets_map = {}
    # Track image sizes for MHIF — use stride × h × 2 to match ithmb entry size
    from .rgb565 import IPOD_STRIDE_OVERRIDE
    image_sizes = {}
    for fmt_id in format_ids:
        w, h = IPOD_CLASSIC_FORMATS[fmt_id]
        stride = IPOD_STRIDE_OVERRIDE.get(fmt_id, w)
        image_sizes[fmt_id] = stride * h * 2

    # Open ithmb files for writing
    ithmb_files = {}
    for fmt_id in format_ids:
        ithmb_path = os.path.join(artwork_dir, f"F{fmt_id}_1.ithmb")
        ithmb_files[fmt_id] = open(ithmb_path, 'wb')

    try:
        for entry in entries:
            offsets = {}
            for fmt_id in format_ids:
                if fmt_id in entry.formats:
                    img_data = entry.formats[fmt_id]['data']
                    offsets[fmt_id] = ithmb_offsets[fmt_id]
                    ithmb_files[fmt_id].write(img_data)
                    ithmb_offsets[fmt_id] += len(img_data)
            format_offsets_map[entry.img_id] = offsets
    finally:
        for f in ithmb_files.values():
            f.close()

    logger.info(f"Wrote ithmb files for {len(entries)} images")
    for fmt_id in format_ids:
        ithmb_path = os.path.join(artwork_dir, f"F{fmt_id}_1.ithmb")
        size = os.path.getsize(ithmb_path)
        logger.info(f"  F{fmt_id}_1.ithmb: {size} bytes")

    # --- Step 4: Build ArtworkDB binary ---

    # Dataset 1: Image list
    mhli = _write_mhli(entries, format_offsets_map)
    ds1 = _write_mhsd(1, mhli)

    # Dataset 2: Album list (empty)
    mhla = _write_mhla()
    ds2 = _write_mhsd(2, mhla)

    # Dataset 3: File list
    mhlf = _write_mhlf(format_ids, image_sizes)
    ds3 = _write_mhsd(3, mhlf)

    # MHFD root
    next_id = start_img_id + len(entries)
    artdb_data = _write_mhfd([ds1, ds2, ds3], next_id, ref_mhfd)

    # Write ArtworkDB
    artdb_path = os.path.join(artwork_dir, "ArtworkDB")
    with open(artdb_path, 'wb') as f:
        f.write(artdb_data)

    logger.info(f"Wrote ArtworkDB: {len(artdb_data)} bytes")

    # --- Step 5: Build dbid → (imgId, src_img_size) mapping ---
    dbid_to_art_info: dict[int, tuple[int, int]] = {}
    # Build hash → (imgId, src_img_size) lookup
    hash_to_art_info: dict[str, tuple[int, int]] = {}
    for entry in entries:
        hash_to_art_info[entry.art_hash] = (entry.img_id, entry.src_img_size)

    for dbid, h in track_art.items():
        if h in hash_to_art_info:
            dbid_to_art_info[dbid] = hash_to_art_info[h]

    return dbid_to_art_info


def _get_track_field(track, field: str):
    """Get a field from a track dict or dataclass."""
    if isinstance(track, dict):
        return track.get(field)
    return getattr(track, field, None)
