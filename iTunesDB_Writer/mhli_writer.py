"""MHLI Writer — Write artist list chunks for iTunesDB.

MHSD type 8 contains an artist list using 'mhli' as the list header and
'mhii' as individual artist items.  Despite sharing the 'mhii' magic with
ArtworkDB image items, these are structurally different chunks.

MHLI header layout (MHLI_HEADER_SIZE = 92 bytes):
    +0x00: 'mhli' magic (4B)
    +0x04: header_length (4B)
    +0x08: artist_count (4B)

MHII header layout (MHII_HEADER_SIZE = 80 bytes, per libgpod mk_mhii):
    +0x00: 'mhii' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + child MHODs
    +0x0C: child_count (4B) — always 1 (the artist-name MHOD)
    +0x10: artist_id (4B) — links to MHIT.artist_id
    +0x14: sql_id (8B) — internal iPod DB id (must be non-zero)
    +0x1C: unk3 (4B) — always 2

    Children: MHOD type 300 (artist name / album-artist name)

Cross-referenced against:
  - libgpod itdb_itunesdb.c: mk_mhii() (artist variant)
  - docs/iTunesCDB-internals.md §Type 8
"""

import struct
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhod_writer import write_mhod_string


# MHLI header size (same as MHLA/MHLT — generic list header)
MHLI_HEADER_SIZE = 92

# MHII header size for artist items (from libgpod: put32lint(cts, 80))
MHII_ARTIST_HEADER_SIZE = 80

# MHOD type for artist name on artist items (from libgpod: MHOD_ID_ALBUM_ARTIST_MHII = 300)
MHOD_TYPE_ARTIST_NAME = 300


def write_mhii_artist(artist_id: int, artist_name: str) -> bytes:
    """
    Write an MHII (artist item) chunk for the artist list.

    Args:
        artist_id: Unique artist ID (used to link tracks to artists)
        artist_name: Artist name string

    Returns:
        Complete MHII chunk with MHOD type 300
    """
    # Build child MHOD (always exactly 1: the artist name)
    children = bytearray()
    child_count = 0

    if artist_name:
        children.extend(write_mhod_string(MHOD_TYPE_ARTIST_NAME, artist_name))
        child_count += 1

    # Total chunk length
    total_length = MHII_ARTIST_HEADER_SIZE + len(children)

    # Build header
    header = bytearray(MHII_ARTIST_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhii'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHII_ARTIST_HEADER_SIZE)

    # +0x08: Total length
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: Child count (number of MHODs — always 1 per libgpod)
    struct.pack_into('<I', header, 0x0C, child_count)

    # +0x10: Artist ID (links to track's artist_id field)
    struct.pack_into('<I', header, 0x10, artist_id)

    # +0x14: SQL ID (64-bit) — used by iPod's internal SQLite database
    # CRITICAL: Must be non-zero! Clean iTunes DBs have random u64 values here.
    sql_id = random.getrandbits(64)
    struct.pack_into('<Q', header, 0x14, sql_id)

    # +0x1C: Unknown (always 2, same as MHIA albums)
    struct.pack_into('<I', header, 0x1C, 2)

    return bytes(header) + bytes(children)


def write_mhli(tracks: list["TrackInfo"]) -> tuple[bytes, dict[str, int]]:
    """
    Write an MHLI (artist list) chunk with artists derived from tracks.

    Deduplicates artists using case-insensitive matching (same as album
    deduplication in mhla_writer.py).

    Args:
        tracks: List of TrackInfo objects

    Returns:
        Tuple of (MHLI chunk bytes, artist_map dict mapping artist_name_lower to artist_id)
    """
    # Collect unique artists: lowercase artist name → display name
    # Use the first occurrence's casing as the canonical display name
    artist_display: dict[str, str] = {}
    for track in tracks:
        artist_name = track.artist or ""
        if not artist_name:
            continue
        key = artist_name.lower()
        if key not in artist_display:
            artist_display[key] = artist_name

    # Build artist items
    artist_items = bytearray()
    artist_map: dict[str, int] = {}  # lowercase artist → artist_id

    artist_id = 1  # Start artist IDs at 1
    for key in sorted(artist_display.keys()):
        display_name = artist_display[key]
        artist_map[key] = artist_id
        artist_items.extend(write_mhii_artist(artist_id, display_name))
        artist_id += 1

    artist_count = len(artist_map)

    # Build header
    header = bytearray(MHLI_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhli'

    # Header length
    struct.pack_into('<I', header, 4, MHLI_HEADER_SIZE)

    # Artist count
    struct.pack_into('<I', header, 8, artist_count)

    return bytes(header) + bytes(artist_items), artist_map


def write_mhli_empty() -> bytes:
    """
    Write an empty MHLI (artist list) chunk.

    Returns:
        MHLI header with 0 artists
    """
    header = bytearray(MHLI_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhli'

    # Header length
    struct.pack_into('<I', header, 4, MHLI_HEADER_SIZE)

    # Artist count = 0
    struct.pack_into('<I', header, 8, 0)

    return bytes(header)
