"""MHSD Writer — Write dataset chunks for iTunesDB.

MHSD (dataset) chunks are containers for different types of data.
Each MHSD wraps exactly one child list chunk (mhlt, mhlp, mhla, or mhli).

Header layout (MHSD_HEADER_SIZE = 96 bytes):
    +0x00: 'mhsd' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + child data
    +0x0C: dataset_type (4B):
           1 = Track list (mhlt)
           2 = Playlist list (mhlp)
           3 = Podcast list (mhlp) — same content as type 2
           4 = Album list (mhla)
           5 = Smart playlist list (mhlp)
           6 = Empty stub (mhlt with 0 children)
           8 = Artist list (mhli with mhii children)
           10 = Empty stub (mhlt with 0 children)

Cross-referenced against:
  - iTunesDB_Parser/mhsd_parser.py
  - libgpod itdb_itunesdb.c: mk_mhsd()
"""

import struct


# MHSD header size
MHSD_HEADER_SIZE = 96


def write_mhsd(dataset_type: int, child_data: bytes) -> bytes:
    """
    Write a MHSD (dataset) chunk.

    Args:
        dataset_type: Type of dataset
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


def write_mhsd_type1(track_list_data: bytes) -> bytes:
    """Write a Type 1 MHSD containing track list."""
    return write_mhsd(1, track_list_data)


def write_mhsd_type2(playlist_list_data: bytes) -> bytes:
    """Write a Type 2 MHSD containing playlist list."""
    return write_mhsd(2, playlist_list_data)


def write_mhsd_type3(podcast_list_data: bytes) -> bytes:
    """Write a Type 3 MHSD containing podcast list."""
    return write_mhsd(3, podcast_list_data)


def write_mhsd_type4(album_list_data: bytes) -> bytes:
    """Write a Type 4 MHSD containing album list."""
    return write_mhsd(4, album_list_data)


def write_mhsd_smart_type5(smart_playlist_data: bytes) -> bytes:
    """Write a Type 5 MHSD containing smart playlist list."""
    return write_mhsd(5, smart_playlist_data)


def write_mhsd_type8(artist_list_data: bytes) -> bytes:
    """Write a Type 8 MHSD containing artist list (mhli)."""
    return write_mhsd(8, artist_list_data)


def write_mhsd_empty_stub(dataset_type: int) -> bytes:
    """Write a stub MHSD containing an empty MHLT (0 children).

    Used for types 6 and 10 which libgpod writes as empty track-list
    stubs.  The child is a minimal MHLT header with count = 0.

    Args:
        dataset_type: The MHSD type (6 or 10).

    Returns:
        Complete MHSD + empty MHLT bytes.
    """
    # Build an empty MHLT child (92-byte header, 0 tracks)
    MHLT_HEADER_SIZE = 92
    mhlt = bytearray(MHLT_HEADER_SIZE)
    mhlt[0:4] = b'mhlt'
    struct.pack_into('<I', mhlt, 4, MHLT_HEADER_SIZE)
    struct.pack_into('<I', mhlt, 8, 0)  # track_count = 0

    return write_mhsd(dataset_type, bytes(mhlt))
