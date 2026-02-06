"""
MHLT Writer - Write track list chunks for iTunesDB.

MHLT (track list) contains all MHIT (track) chunks.
"""

import struct
from typing import List

from .mhit_writer import write_mhit, TrackInfo


# MHLT header size
MHLT_HEADER_SIZE = 92


def _assign_artist_composer_ids(tracks: List[TrackInfo], start_track_id: int) -> None:
    """
    Assign artist_id and composer_id to each track using a global counter.

    iTunes uses a single incrementing ID counter for ALL entities
    (albums, tracks, artists, composers). We allocate IDs sequentially
    after the track IDs to avoid collisions.

    Args:
        tracks: List of TrackInfo objects (modified in place)
        start_track_id: First track ID (artist/composer IDs start after last track ID)
    """
    # Start assigning after the last track ID
    next_id = start_track_id + len(tracks)

    # Map unique artists and composers to IDs
    artist_ids: dict[str, int] = {}
    composer_ids: dict[str, int] = {}

    for track in tracks:
        # Artist ID
        artist_key = (track.artist or "").lower()
        if artist_key not in artist_ids:
            artist_ids[artist_key] = next_id
            next_id += 1
        track.artist_id = artist_ids[artist_key]

        # Composer ID (each track gets its own in clean DB, even if same composer)
        # Matching observed iTunes behavior: composer_id is per-track, NOT deduped
        track.composer_id = next_id
        next_id += 1


def write_mhlt(tracks: List[TrackInfo], start_track_id: int = 1,
               id_0x24: int = 0) -> tuple[bytes, int]:
    """
    Write a complete MHLT chunk with all tracks.

    Args:
        tracks: List of TrackInfo objects
        start_track_id: Starting track ID (increments for each track)
        id_0x24: Database-wide ID from MHBD (written into every MHIT at offset 0x124)

    Returns:
        Tuple of (complete MHLT chunk bytes, next available track ID)
    """
    # Assign artist_id and composer_id using a global counter
    # iTunes uses a single incrementing counter for ALL IDs (album, track, artist, composer)
    # We allocate artist/composer IDs starting after the album IDs + track IDs range
    # Since we don't control the global counter here, we use a separate sequence
    # that won't conflict with track IDs (start high enough)
    _assign_artist_composer_ids(tracks, start_track_id)

    # Build all track chunks first
    track_chunks = []
    track_id = start_track_id

    for track in tracks:
        mhit_data = write_mhit(track, track_id, id_0x24)
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
