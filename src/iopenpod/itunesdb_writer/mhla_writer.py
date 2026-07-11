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
    +0x1C: platform_flag (2B, always 2) + album_compilation_flag (2B, 0=normal, 1=compilation)

    Children: MHOD types 200 (album name), 201 (artist), 202 (sort artist)

Cross-referenced against:
  - src/iopenpod/itunesdb_parser/mhia_parser.py parse_albumItem()
  - libgpod itdb_itunesdb.c: mk_mhia()
"""

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from iopenpod.itunesdb_shared.album_identity import (
    album_identity_from_track,
    group_tracks_by_album_identity,
)
from iopenpod.itunesdb_shared.constants import (
    MHOD_TYPE_ALBUM_ALBUM,
    MHOD_TYPE_ALBUM_ARTIST_ITEM,
    MHOD_TYPE_ALBUM_PODCAST_URL,
    MHOD_TYPE_ALBUM_SHOW,
    MHOD_TYPE_ALBUM_SORT_ARTIST,
)
from iopenpod.itunesdb_shared.field_base import (
    MHLA_HEADER_SIZE,
    write_fields,
    write_generic_header,
    write_list_header,
)
from iopenpod.itunesdb_shared.mhia_defs import MHIA_HEADER_SIZE

from .mhod_writer import write_mhod_string


def _extend_child(children: bytearray, chunk: bytes) -> int:
    if not chunk:
        return 0
    children.extend(chunk)
    return 1


def write_mhia(album_id: int, album_name: str, album_artist: str,
               sort_album_artist: str = "",
               podcast_url: str = "", show_name: str = "",
               is_compilation: bool = False,
               album_track_db_id: int = 0) -> bytes:
    """
    Write an MHIA (album item) chunk.

    Args:
        album_id: Unique album ID (used to link tracks to albums)
        album_name: Album name
        album_artist: Album artist
        sort_album_artist: Sort album artist (for proper alphabetical sorting)
        podcast_url: Podcast RSS URL (MHOD type 203)
        show_name: Show/series name (MHOD type 204)
        is_compilation: True for Various Artists / compilation albums
        album_track_db_id: db_track_id of a representative track in this album

    Returns:
        Complete MHIA chunk with MHODs
    """
    # Build child MHODs
    children = bytearray()
    child_count = 0

    if album_name:
        child_count += _extend_child(
            children,
            write_mhod_string(MHOD_TYPE_ALBUM_ALBUM, album_name),
        )

    if album_artist:
        child_count += _extend_child(
            children,
            write_mhod_string(MHOD_TYPE_ALBUM_ARTIST_ITEM, album_artist),
        )

    if sort_album_artist:
        child_count += _extend_child(
            children,
            write_mhod_string(MHOD_TYPE_ALBUM_SORT_ARTIST, sort_album_artist),
        )

    if podcast_url:
        child_count += _extend_child(
            children,
            write_mhod_string(MHOD_TYPE_ALBUM_PODCAST_URL, podcast_url),
        )

    if show_name:
        child_count += _extend_child(
            children,
            write_mhod_string(MHOD_TYPE_ALBUM_SHOW, show_name),
        )

    # Total chunk length
    total_length = MHIA_HEADER_SIZE + len(children)

    # Build header
    header = bytearray(MHIA_HEADER_SIZE)
    write_generic_header(header, 0, b'mhia', MHIA_HEADER_SIZE, total_length)

    # CRITICAL: sql_id must be non-zero! Clean iTunes DBs have random u64 values here.
    sql_id = random.getrandbits(64)
    write_fields(header, 0, 'mhia', {
        'child_count': child_count,
        'album_id': album_id,
        'sql_id': sql_id,
        'platform_flag': 2,
        'album_compilation_flag': 1 if is_compilation else 0,
        'album_track_db_id': album_track_db_id,
    }, MHIA_HEADER_SIZE)

    return bytes(header) + bytes(children)


def _pick_first(tracks: list["TrackInfo"], attr: str) -> str:
    for track in tracks:
        value = getattr(track, attr, None) or ""
        if value:
            return value
    return ""


def write_mhla(
    tracks: list["TrackInfo"],
    starting_index_for_album_id,
) -> tuple[bytes, dict[tuple[str, str], int], int]:
    """
    Write an MHLA (album list) chunk with albums derived from tracks.

    Args:
        tracks: List of TrackInfo objects

    Returns:
        Tuple of (MHLA chunk bytes, album_map dict mapping (album, artist) to album_id)
    """
    groups = group_tracks_by_album_identity(tracks, album_identity_from_track)

    # Build album items
    album_items = bytearray()
    album_map: dict[tuple[str, str], int] = {}  # (album, artist) -> album_id

    def _album_sort_key(group):
        identity = group.identity
        album_name = identity.album or ""
        album_artist = identity.album_artist or identity.artist or ""
        show_name = identity.show_name or ""
        return (album_name, album_artist, show_name)

    album_id = starting_index_for_album_id
    for group in sorted(groups, key=_album_sort_key):
        identity = group.identity
        album_name = identity.album or ""
        album_artist = identity.album_artist or identity.artist or ""
        album_map[(album_name, album_artist)] = album_id
        # Use sort_albumartist from track first, fall back to sort_artist (per libgpod mk_mhia)
        sort_artist = _pick_first(group.tracks, "sort_album_artist")
        if not sort_artist:
            sort_artist = _pick_first(group.tracks, "sort_artist")
        podcast_url = _pick_first(group.tracks, "podcast_rss_url")
        show_name = identity.show_name or _pick_first(group.tracks, "show_name")
        # Album is a compilation if any track in it has compilation_flag=True
        is_compilation = any(t.compilation_flag for t in group.tracks)
        # Use first track's db_track_id as the representative track for this album
        rep_db_track_id = group.tracks[0].db_track_id if group.tracks else 0
        for track in group.tracks:
            track.album_id = album_id
        album_items.extend(write_mhia(
            album_id, album_name, album_artist, sort_artist,
            podcast_url=podcast_url, show_name=show_name,
            is_compilation=is_compilation,
            album_track_db_id=rep_db_track_id,
        ))
        album_id += 1

    album_count = len(album_map)

    mhla = write_list_header(b'mhla', MHLA_HEADER_SIZE, album_count) + bytes(album_items)
    return mhla, album_map, album_id


def write_mhla_empty() -> bytes:
    """
    Write an empty MHLA (album list) chunk.

    Returns:
        MHLA header with 0 albums
    """
    return write_list_header(b'mhla', MHLA_HEADER_SIZE, 0)
