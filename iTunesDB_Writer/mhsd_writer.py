"""
MHSD Writer - Write dataset chunks for iTunesDB.

MHSD (dataset) chunks are containers for different types of data:
- Type 1: Track list (mhlt)
- Type 2: Playlist list (mhlp)
- Type 3: Podcast list (mhlp)
- Type 4: Album list (mhla)
- Type 5: Smart playlist list (mhlp)
"""

import struct


# MHSD header size
MHSD_HEADER_SIZE = 96

# Dataset types
MHSD_TYPE_TRACKS = 1
MHSD_TYPE_PLAYLISTS = 2
MHSD_TYPE_PODCASTS = 3
MHSD_TYPE_ALBUMS = 4
MHSD_TYPE_SMART_PLAYLISTS = 5


def write_mhsd(dataset_type: int, child_data: bytes) -> bytes:
    """
    Write a MHSD (dataset) chunk.

    Args:
        dataset_type: Type of dataset (1=tracks, 2=playlists, etc.)
        child_data: Child chunk data (mhlt, mhlp, or mhla)

    Returns:
        Complete MHSD chunk bytes
    """
    # Total length = header + child
    total_length = MHSD_HEADER_SIZE + len(child_data)

    # Build header
    header = bytearray(MHSD_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhsd'

    # Header length
    struct.pack_into('<I', header, 4, MHSD_HEADER_SIZE)

    # Total length
    struct.pack_into('<I', header, 8, total_length)

    # Dataset type
    struct.pack_into('<I', header, 12, dataset_type)

    # Rest is padding/reserved

    return bytes(header) + child_data


def write_mhsd_tracks(track_list_data: bytes) -> bytes:
    """Write a Type 1 MHSD containing track list."""
    return write_mhsd(MHSD_TYPE_TRACKS, track_list_data)


def write_mhsd_playlists(playlist_list_data: bytes) -> bytes:
    """Write a Type 2 MHSD containing playlist list."""
    return write_mhsd(MHSD_TYPE_PLAYLISTS, playlist_list_data)


def write_mhsd_podcasts(podcast_list_data: bytes) -> bytes:
    """Write a Type 3 MHSD containing podcast list."""
    return write_mhsd(MHSD_TYPE_PODCASTS, podcast_list_data)


def write_mhsd_albums(album_list_data: bytes) -> bytes:
    """Write a Type 4 MHSD containing album list."""
    return write_mhsd(MHSD_TYPE_ALBUMS, album_list_data)


def write_mhsd_smart_playlists(smart_playlist_data: bytes) -> bytes:
    """Write a Type 5 MHSD containing smart playlist list."""
    return write_mhsd(MHSD_TYPE_SMART_PLAYLISTS, smart_playlist_data)
