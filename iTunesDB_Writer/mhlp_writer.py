"""
MHLP Writer - Write playlist list chunks for iTunesDB.

MHLP contains all playlists. At minimum, every iTunesDB needs the
"master playlist" which contains references to all tracks.

Based on libgpod's mk_mhlp() in itdb_itunesdb.c
"""

import struct
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhyp_writer import write_master_playlist


# MHLP header size - libgpod uses 92 bytes
MHLP_HEADER_SIZE = 92


def write_mhlp_empty() -> bytes:
    """
    Write an empty MHLP (playlist list) chunk.

    Note: An empty MHLP means NO playlists, which may cause issues
    on some iPods. Use write_mhlp_with_master() for a valid database.

    Returns:
        MHLP header with 0 playlists
    """
    header = bytearray(MHLP_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhlp'

    # Header length
    struct.pack_into('<I', header, 4, MHLP_HEADER_SIZE)

    # Playlist count = 0
    struct.pack_into('<I', header, 8, 0)

    return bytes(header)


def write_mhlp(playlist_chunks: List[bytes]) -> bytes:
    """
    Write a MHLP chunk with playlists.

    Args:
        playlist_chunks: List of MHYP (playlist) chunks

    Returns:
        Complete MHLP chunk
    """
    # Concatenate all playlist data
    playlists_data = b''.join(playlist_chunks)

    header = bytearray(MHLP_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhlp'

    # Header length
    struct.pack_into('<I', header, 4, MHLP_HEADER_SIZE)

    # Playlist count
    struct.pack_into('<I', header, 8, len(playlist_chunks))

    return bytes(header) + playlists_data


def write_mhlp_with_master(
    track_ids: List[int],
    device_name: str = "iPod",
    tracks: Optional[List["TrackInfo"]] = None,
    id_0x24: int = 0,
) -> bytes:
    """
    Write an MHLP chunk with the required Master Playlist.

    The Master Playlist is REQUIRED for a valid iTunesDB. It must:
    - Be the first playlist
    - Have type = 1 (master)
    - Reference ALL tracks in the database

    Args:
        track_ids: List of ALL track IDs in the database
        device_name: Name for the master playlist (default "iPod")
        tracks: List of ALL TrackInfo objects (needed for library indices)
        id_0x24: Database-wide ID from MHBD offset 0x24

    Returns:
        Complete MHLP chunk with master playlist
    """
    # Create the master playlist
    master = write_master_playlist(track_ids, name=device_name, tracks=tracks, id_0x24=id_0x24)

    # Wrap in MHLP
    return write_mhlp([master])
