"""
MHLA Writer - Write album list chunks for iTunesDB.

MHLA (album list) contains album entries that group tracks.
Each album entry (MHIA) contains MHODs for album name and artist.
"""

import struct
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhod_writer import write_mhod_string


# MHLA header size
MHLA_HEADER_SIZE = 92

# MHIA header size (from libgpod)
MHIA_HEADER_SIZE = 88


def write_mhia(album_id: int, album_name: str, album_artist: str,
               sort_album_artist: str = "") -> bytes:
    """
    Write an MHIA (album item) chunk.

    Args:
        album_id: Unique album ID (used to link tracks to albums)
        album_name: Album name
        album_artist: Album artist
        sort_album_artist: Sort album artist (for proper alphabetical sorting)

    Returns:
        Complete MHIA chunk with MHODs
    """
    # Build child MHODs
    children = bytearray()
    child_count = 0

    # MHOD type 200 = album name (for album items, not type 3 which is for tracks)
    if album_name:
        children.extend(write_mhod_string(200, album_name))
        child_count += 1

    # MHOD type 201 = artist (for album items, not type 22 which is for tracks)
    if album_artist:
        children.extend(write_mhod_string(201, album_artist))
        child_count += 1

    # MHOD type 202 = sort artist (per libgpod mk_mhia, uses sort_albumartist or sort_artist)
    if sort_album_artist:
        children.extend(write_mhod_string(202, sort_album_artist))
        child_count += 1

    # Total chunk length
    total_length = MHIA_HEADER_SIZE + len(children)

    # Build header
    header = bytearray(MHIA_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhia'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHIA_HEADER_SIZE)

    # +0x08: Total length
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: Child count (number of MHODs)
    struct.pack_into('<I', header, 0x0C, child_count)

    # +0x10: Album ID (links to track's album_id field)
    struct.pack_into('<I', header, 0x10, album_id)

    # +0x14: SQL ID (64-bit) - used by iPod's internal SQLite database
    # CRITICAL: Must be non-zero! Clean iTunes DBs have random u64 values here.
    sql_id = random.getrandbits(64)
    struct.pack_into('<Q', header, 0x14, sql_id)

    # +0x1C: Unknown (always 2 according to parser)
    struct.pack_into('<I', header, 0x1C, 2)

    return bytes(header) + bytes(children)


def write_mhla(tracks: list["TrackInfo"]) -> tuple[bytes, dict[tuple[str, str], int]]:
    """
    Write an MHLA (album list) chunk with albums derived from tracks.

    Args:
        tracks: List of TrackInfo objects

    Returns:
        Tuple of (MHLA chunk bytes, album_map dict mapping (album, artist) to album_id)
    """
    # Collect unique albums: (album_name, album_artist) -> list of tracks
    album_tracks: dict[tuple[str, str], list] = {}
    for track in tracks:
        album_name = track.album or ""
        album_artist = track.album_artist or track.artist or ""
        key = (album_name, album_artist)
        if key not in album_tracks:
            album_tracks[key] = []
        album_tracks[key].append(track)

    # Build album items
    album_items = bytearray()
    album_map: dict[tuple[str, str], int] = {}  # (album, artist) -> album_id

    # Collect sort artist info per album key
    album_sort_artists: dict[tuple[str, str], str] = {}
    for track in tracks:
        album_name = track.album or ""
        album_artist = track.album_artist or track.artist or ""
        key = (album_name, album_artist)
        if key not in album_sort_artists:
            # Use sort_artist from track (per libgpod: sort_albumartist > sort_artist)
            sort_artist = getattr(track, 'sort_artist', None) or ""
            if sort_artist:
                album_sort_artists[key] = sort_artist

    album_id = 1  # Start album IDs at 1
    for (album_name, album_artist) in sorted(album_tracks.keys()):
        album_map[(album_name, album_artist)] = album_id
        sort_artist = album_sort_artists.get((album_name, album_artist), "")
        album_items.extend(write_mhia(album_id, album_name, album_artist, sort_artist))
        album_id += 1

    album_count = len(album_map)

    # Build header
    header = bytearray(MHLA_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhla'

    # Header length
    struct.pack_into('<I', header, 4, MHLA_HEADER_SIZE)

    # Album count
    struct.pack_into('<I', header, 8, album_count)

    return bytes(header) + bytes(album_items), album_map


def write_mhla_empty() -> bytes:
    """
    Write an empty MHLA (album list) chunk.

    Returns:
        MHLA header with 0 albums
    """
    header = bytearray(MHLA_HEADER_SIZE)

    # Magic
    header[0:4] = b'mhla'

    # Header length
    struct.pack_into('<I', header, 4, MHLA_HEADER_SIZE)

    # Album count = 0
    struct.pack_into('<I', header, 8, 0)

    return bytes(header)
