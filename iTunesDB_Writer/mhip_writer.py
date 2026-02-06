"""
MHIP Writer - Write playlist item chunks for iTunesDB.

MHIP chunks are playlist entries that reference tracks by their ID.
Each playlist (MHYP) contains MHIP entries for each track in the playlist.

Based on libgpod's mk_mhip() in itdb_itunesdb.c
"""

import struct
from typing import Optional


# MHIP header size - libgpod uses 76 bytes
MHIP_HEADER_SIZE = 76


def write_mhip(
    track_id: int,
    position: int = 0,
    mhip_id: int = 0,
    timestamp: int = 0,
    podcast_group_flag: int = 0,
    podcast_group_ref: int = 0,
) -> bytes:
    """
    Write an MHIP (playlist item) chunk.

    MHIP entries link tracks to playlists by referencing the track ID.
    Each entry also includes an MHOD type 100 with the position.

    Args:
        track_id: The track's ID (from MHIT)
        position: Position in playlist (0-based)
        mhip_id: Unique ID for this MHIP entry (written at offset 0x14)
                 In libgpod this is called "podcastgroupid" but it's used
                 for ALL playlists as a unique entry identifier.
        timestamp: Mac timestamp (usually 0)
        podcast_group_flag: For podcast grouping (usually 0)
        podcast_group_ref: For podcast grouping (usually 0)

    Returns:
        Complete MHIP chunk bytes
    """
    # MHIP has one MHOD child (type 100 with position)
    mhod_position = write_mhod_position(position)

    total_length = MHIP_HEADER_SIZE + len(mhod_position)

    # Build MHIP header
    header = bytearray(MHIP_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhip'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHIP_HEADER_SIZE)

    # +0x08: Total length
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: Number of MHOD children (always 1)
    struct.pack_into('<I', header, 0x0C, 1)

    # +0x10: Podcast group flag
    struct.pack_into('<I', header, 0x10, podcast_group_flag)

    # +0x14: MHIP unique ID (libgpod calls this podcastgroupid but it's
    #        actually a unique playlist item identifier used for all playlists)
    struct.pack_into('<I', header, 0x14, mhip_id)

    # +0x18: Track ID - references the MHIT
    struct.pack_into('<I', header, 0x18, track_id)

    # +0x1C: Timestamp
    struct.pack_into('<I', header, 0x1C, timestamp)

    # +0x20: Podcast group reference
    struct.pack_into('<I', header, 0x20, podcast_group_ref)

    # Rest is padding (zeros)

    return bytes(header) + mhod_position


def write_mhod_position(position: int) -> bytes:
    """
    Write an MHOD type 100 (playlist position).

    This MHOD is attached to each MHIP and indicates the track's
    position within the playlist.

    Args:
        position: Track position in playlist (0-based)

    Returns:
        MHOD chunk bytes
    """
    # MHOD type 100 structure:
    # Header (24 bytes) + data (20 bytes)
    header_len = 24
    total_len = 44  # header + data

    # Build header
    header = struct.pack(
        '<4sIIIII',
        b'mhod',
        header_len,
        total_len,
        100,  # MHOD type = playlist position
        0,    # unk1
        0,    # unk2
    )

    # Data section (20 bytes)
    # +0x00: Position (track_pos in libgpod)
    # +0x04-0x13: Padding (zeros)
    data = struct.pack('<I', position) + (b'\x00' * 16)

    return header + data
