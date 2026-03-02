"""MHLP Writer — Write playlist list chunks for iTunesDB.

MHLP (playlist list) wraps all MHYP (playlist) chunks and provides
the playlist count in its header. Every iTunesDB needs at least a
"master playlist" referencing all tracks.

Header layout (MHLP_HEADER_SIZE = 92 bytes):
    +0x00: 'mhlp' magic (4B)
    +0x04: header_length (4B)
    +0x08: playlist_count (4B)

Supports:
- Master playlist only (write_mhlp_with_master)
- Master + user playlists (write_mhlp_with_playlists)
- Dataset 3 podcast playlists (podcast clone of dataset 2)
- Dataset 5 smart playlists (write_mhlp_smart)

Cross-referenced against:
  - iTunesDB_Parser/mhlp_parser.py
  - libgpod itdb_itunesdb.c: mk_mhlp()
"""

import struct
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo
    from .mhyp_writer import PlaylistInfo

from .mhyp_writer import write_master_playlist, write_playlist


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


def write_mhlp_with_playlists(
    track_ids: List[int],
    playlists: List["PlaylistInfo"],
    device_name: str = "iPod",
    tracks: Optional[List["TrackInfo"]] = None,
    id_0x24: int = 0,
) -> bytes:
    """
    Write an MHLP chunk with the master playlist + user playlists.

    The master playlist is always first, followed by regular/smart playlists.
    This is used for MHSD type 2 (playlists dataset).

    Args:
        track_ids: List of ALL track IDs in the database (for master playlist)
        playlists: List of PlaylistInfo objects for user playlists
        device_name: Name for the master playlist (default "iPod")
        tracks: List of ALL TrackInfo objects (needed for library indices)
        id_0x24: Database-wide ID from MHBD offset 0x24

    Returns:
        Complete MHLP chunk
    """
    chunks = []

    # Master playlist MUST be first
    master = write_master_playlist(track_ids, name=device_name, tracks=tracks, id_0x24=id_0x24)
    chunks.append(master)

    # User playlists (regular and smart)
    for pl in playlists:
        chunks.append(write_playlist(pl, id_0x24=id_0x24))

    return write_mhlp(chunks)


def write_mhlp_smart(
    playlists: List["PlaylistInfo"],
    id_0x24: int = 0,
) -> bytes:
    """
    Write an MHLP chunk for dataset type 5 (smart playlist list).

    These playlists define iPod built-in browse categories (Music, Movies,
    TV Shows, Audiobooks, Podcasts, Rentals). Each has a mhsd5_type value
    and smart rules that filter by media type.

    Args:
        playlists: List of PlaylistInfo objects (smart playlists only)
        id_0x24: Database-wide ID from MHBD offset 0x24

    Returns:
        Complete MHLP chunk, or empty MHLP if no smart playlists
    """
    if not playlists:
        return write_mhlp_empty()

    chunks = []
    for pl in playlists:
        chunks.append(write_playlist(pl, id_0x24=id_0x24))

    return write_mhlp(chunks)
