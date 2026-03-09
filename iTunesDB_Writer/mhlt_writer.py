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

from typing import List

from iTunesDB_Shared.field_base import MHLT_HEADER_SIZE, write_generic_header
from .mhit_writer import write_mhit, TrackInfo


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
    write_generic_header(header, 0, b'mhlt', MHLT_HEADER_SIZE, len(tracks))

    return bytes(header) + all_tracks_data, track_id
