"""MHLA Writer — Write album list chunks for iTunesDB.

MHLA (album list) contains MHIA (album item) entries that group tracks.
Introduced in iTunes 7.1 (dbversion >= 0x14).

MHLA header layout (MHLA_HEADER_SIZE = 92 bytes):
    +0x00: 'mhla' magic (4B)
    +0x04: header_length (4B)
    +0x08: album_count (4B)

MHIA header layout (MHIA_HEADER_SIZE = 88 bytes):
    +0x00: 'mhia' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + child MHODs
    +0x0C: child_count (4B)
    +0x10: album_id (4B) — links to MHIT.albumID
    +0x14: sql_id (8B) — internal iPod DB id (must be non-zero)
    +0x1C: unk3 (4B) — always 2

    Children: MHOD types 200 (album name), 201 (artist), 202 (sort artist)

Cross-referenced against:
  - iTunesDB_Parser/mhia_parser.py parse_albumItem()
  - libgpod itdb_itunesdb.c: mk_mhia()
"""

import struct
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhod_writer import write_mhod_string


def _album_key(track: "TrackInfo") -> tuple[str, str]:
    """Compute the album grouping key for a track.

    Compilation albums (``track.compilation == True``) are grouped by album
    name alone — the artist dimension is always ``""`` so that all tracks
    on a Various-Artists / compilation album share a single album ID.

    Non-compilation albums fall back through ``album_artist`` then ``artist``
    so that two artists who each have a "Greatest Hits" album remain separate.
    """
    album_name = track.album or ""
    if getattr(track, "compilation", False):
        return (album_name, "")
    album_artist = track.album_artist or track.artist or ""
    return (album_name, album_artist)


# MHLA header size
MHLA_HEADER_SIZE = 92

# MHIA header size (from libgpod)
MHIA_HEADER_SIZE = 88


def write_mhia(album_id: int, album_name: str, album_artist: str,
               sort_album_artist: str = "",
               podcast_url: str = "", show_name: str = "") -> bytes:
    """
    Write an MHIA (album item) chunk.

    Args:
        album_id: Unique album ID (used to link tracks to albums)
        album_name: Album name
        album_artist: Album artist
        sort_album_artist: Sort album artist (for proper alphabetical sorting)
        podcast_url: Podcast RSS URL (MHOD type 203)
        show_name: Show/series name (MHOD type 204)

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

    # MHOD type 203 = podcast RSS URL (album-level, mirrors track MHOD type 16)
    if podcast_url:
        children.extend(write_mhod_string(203, podcast_url))
        child_count += 1

    # MHOD type 204 = show name (album-level, mirrors track MHOD type 19)
    if show_name:
        children.extend(write_mhod_string(204, show_name))
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


def write_mhla(tracks: list["TrackInfo"], starting_index_for_album_id) -> tuple[bytes, dict[tuple[str, str], int], int]:
    """
    Write an MHLA (album list) chunk with albums derived from tracks.

    Args:
        tracks: List of TrackInfo objects

    Returns:
        Tuple of (MHLA chunk bytes, album_map dict mapping (album, artist) to album_id)
    """
    # Collect unique albums: (album_name, album_artist) -> list of tracks
    # Compilation albums use ("", "") for the artist dimension so that
    # Various-Artists compilations stay grouped under a single album ID.
    album_tracks: dict[tuple[str, str], list] = {}
    for track in tracks:
        key = _album_key(track)
        if key not in album_tracks:
            album_tracks[key] = []
        album_tracks[key].append(track)

    # Build album items
    album_items = bytearray()
    album_map: dict[tuple[str, str], int] = {}  # (album, artist) -> album_id

    # Collect sort artist, podcast URL, and show name per album key
    album_sort_artists: dict[tuple[str, str], str] = {}
    album_podcast_urls: dict[tuple[str, str], str] = {}
    album_show_names: dict[tuple[str, str], str] = {}
    for track in tracks:
        key = _album_key(track)
        if key not in album_sort_artists:
            # Use sort_albumartist from track first, fall back to sort_artist (per libgpod mk_mhia)
            sort_artist = getattr(track, 'sort_album_artist', None) or getattr(track, 'sort_artist', None) or ""
            if sort_artist:
                album_sort_artists[key] = sort_artist
        if key not in album_podcast_urls:
            podcast_url = getattr(track, 'podcast_rss_url', None) or ""
            if podcast_url:
                album_podcast_urls[key] = podcast_url
        if key not in album_show_names:
            show_name = getattr(track, 'show_name', None) or ""
            if show_name:
                album_show_names[key] = show_name

    album_id = starting_index_for_album_id
    for (album_name, album_artist) in sorted(album_tracks.keys()):
        album_map[(album_name, album_artist)] = album_id
        sort_artist = album_sort_artists.get((album_name, album_artist), "")
        podcast_url = album_podcast_urls.get((album_name, album_artist), "")
        show_name = album_show_names.get((album_name, album_artist), "")
        album_items.extend(write_mhia(
            album_id, album_name, album_artist, sort_artist,
            podcast_url=podcast_url, show_name=show_name,
        ))
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

    return bytes(header) + bytes(album_items), album_map, album_id


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
