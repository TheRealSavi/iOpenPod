"""MHLT Writer — Write track list chunks for iTunesDB.

MHLT (track list) wraps all MHIT (track) chunks and provides
the track count in its header.

Header layout (MHLT_HEADER_SIZE = 92 bytes):
    +0x00: 'mhlt' magic (4B)
    +0x04: header_length (4B)
    +0x08: track_count (4B)

Cross-referenced against:
  - iTunesDB_Parser/mhlt_parser.py
  - libgpod itdb_itunesdb.c: mk_mhlt()
"""

import struct
from typing import List

from .mhit_writer import write_mhit, TrackInfo


# MHLT header size
MHLT_HEADER_SIZE = 92


def write_mhlt(tracks: List[TrackInfo], start_track_id: int, id_0x24: int, capabilities=None) -> tuple[bytes, int]:
    """
    Write a complete MHLT chunk with all tracks.

    Args:
        tracks: List of TrackInfo objects
        start_track_id: Starting track ID (increments for each track)
        id_0x24: Database-wide ID from MHBD (written into every MHIT at offset 0x124)
        capabilities: Optional DeviceCapabilities for gapless/video filtering

    Returns:
        Tuple of (complete MHLT chunk bytes, next available track ID)
    """

    # Build all track chunks first
    track_chunks = []
    track_id = start_track_id

    for track in tracks:
        mhit_data = write_mhit(track, track_id, id_0x24, capabilities=capabilities)
        track_chunks.append(mhit_data)
        track_id += 1

    # Concatenate all track data
    all_tracks_data = b''.join(track_chunks)

    header = bytearray(MHLT_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhlt'

    # Header length
    struct.pack_into('<I', header, 4, MHLT_HEADER_SIZE)

    # Track count
    struct.pack_into('<I', header, 8, len(tracks))

    # Rest is padding/reserved

    return bytes(header) + all_tracks_data, track_id
