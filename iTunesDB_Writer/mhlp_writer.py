"""MHLP Writer — Write playlist list chunks for iTunesDB.

MHLP (playlist list) wraps all MHYP (playlist) chunks and provides
the playlist count in its header. Every iTunesDB needs at least a
"master playlist" referencing all tracks.

Header layout (MHLP_HEADER_SIZE = 92 bytes):
    +0x00: 'mhlp' magic (4B)
    +0x04: header_length (4B)
    +0x08: playlist_count (4B)

Supports:
- Master + user playlists (write_mhlp_with_playlists)
- Dataset 3 podcast playlists (podcast clone of dataset 2)
- Dataset 5 smart playlists (write_mhlp_smart)

Cross-referenced against:
  - iTunesDB_Parser/mhlp_parser.py
  - libgpod itdb_itunesdb.c: mk_mhlp()
"""

from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo
    from .mhyp_writer import PlaylistInfo

from iTunesDB_Shared.field_base import MHLP_HEADER_SIZE, write_generic_header
from .mhyp_writer import write_master_playlist, write_playlist

logger = logging.getLogger(__name__)


def write_mhlp_empty() -> bytes:
    """
    Write an empty MHLP (playlist list) chunk.

    Note: An empty MHLP means NO playlists, which may cause issues
    on some iPods. Use write_mhlp_with_playlists() for a valid database.

    Returns:
        MHLP header with 0 playlists
    """
    header = bytearray(MHLP_HEADER_SIZE)
    write_generic_header(header, 0, b'mhlp', MHLP_HEADER_SIZE, 0)

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
    write_generic_header(header, 0, b'mhlp', MHLP_HEADER_SIZE, len(playlist_chunks))

    return bytes(header) + playlists_data


def write_mhlp_with_playlists(
    track_ids: List[int],
    playlists: List[PlaylistInfo],
    id_0x24,
    tracks: Optional[List[TrackInfo]] = None,
    capabilities=None,
    master_playlist_name: str = "iPod",
    master_playlist_id: Optional[int] = None,
) -> bytes:
    """
    Write an MHLP chunk with the master playlist + user playlists.

    The master playlist is always first, followed by regular/smart playlists.
    This is used for MHSD type 2 (playlists dataset).

    The master playlist is auto-generated from the full track list; its
    display name is controlled by *master_playlist_name*.  The *playlists*
    list should contain only user playlists (no master).

    Args:
        track_ids: List of ALL track IDs in the database (for master playlist)
        playlists: List of user PlaylistInfo objects (master is NOT included)
        tracks: List of ALL TrackInfo objects (needed for library indices)
        id_0x24: Database-wide ID from MHBD offset 0x24
        capabilities: Optional DeviceCapabilities for video sort indices.
        master_playlist_name: Display name for the auto-generated master playlist.

    Returns:
        Complete MHLP chunk
    """
    chunks = []

    # Master playlist MUST be first
    master = write_master_playlist(
        track_ids, tracks=tracks, id_0x24=id_0x24,
        capabilities=capabilities, name=master_playlist_name,
        playlist_id=master_playlist_id,
    )
    chunks.append(master)

    # Sanity: strip rogue master flags from dataset-2 user playlists.
    # Only the auto-generated master above should have master=True.
    # Dataset 5 built-in categories (mhsd5_type != 0) legitimately
    # need master=True, so we never touch those — even if they end up
    # here by accident.
    for p in playlists:
        if p.master and not p.mhsd5_type:
            logger.warning(
                "Stripped master flag from user playlist '%s' — "
                "master is auto-generated for dataset 2",
                p.name,
            )
            p.master = False

    # Write all user playlists (regular and smart).
    for pl in playlists:
        chunks.append(write_playlist(pl, id_0x24=id_0x24))

    return write_mhlp(chunks)


def write_mhlp_with_playlists_type3(
    track_ids: List[int],
    playlists: List["PlaylistInfo"],
    id_0x24: int,
    track_album_map: dict[int, str],
    tracks: Optional[List["TrackInfo"]] = None,
    capabilities=None,
    master_playlist_name: str = "iPod",
    next_mhip_id_start: int = 1,
    master_playlist_id: Optional[int] = None,
) -> bytes:
    """Write an MHLP for MHSD type 3 with podcast grouping.

    Identical to :func:`write_mhlp_with_playlists` **except** that playlist
    entries marked as podcast (``podcast_flag == 1``) use the grouped
    MHIP structure described by libgpod's ``write_podcast_mhips()``.

    In the grouped structure, podcast episodes are nested under their
    podcast show (album).  Each show gets a group-header MHIP
    (``podcast_group_flag=256``, MHOD title = album name) followed by
    child episode MHIPs whose ``group_id_ref`` points back to the header.

    Non-podcast playlists are written with the standard flat MHIP layout,
    identical to type 2.

    Args:
        track_ids: ALL track IDs in the database (for the master playlist)
        playlists: User playlist list (same objects as type 2; master is
                   auto-generated)
        id_0x24: Database-wide ID from MHBD offset 0x24
        track_album_map: track_id → album name for podcast grouping
        tracks: TrackInfo list (needed for master playlist library indices)
        capabilities: DeviceCapabilities (for video sort indices etc.)
        master_playlist_name: Display name for the master playlist.
        next_mhip_id_start: Starting ID for generated MHIP identifiers.

    Returns:
        Complete MHLP chunk bytes.
    """
    chunks = []

    # Master playlist — identical to type 2
    master = write_master_playlist(
        track_ids, tracks=tracks, id_0x24=id_0x24,
        capabilities=capabilities, name=master_playlist_name,
        playlist_id=master_playlist_id,
    )
    chunks.append(master)

    for p in playlists:
        if p.master and not p.mhsd5_type:
            logger.warning(
                "Stripped master flag from user playlist '%s' — "
                "master is auto-generated for dataset 3",
                p.name,
            )
            p.master = False

    for pl in playlists:
        chunks.append(write_playlist(
            pl, id_0x24=id_0x24,
            podcast_grouping=True,
            track_album_map=track_album_map,
            next_mhip_id_start=next_mhip_id_start,
        ))

    return write_mhlp(chunks)


def write_mhlp_smart(
    playlists: List[PlaylistInfo],
    id_0x24: int = 0,
) -> bytes:
    """
    Write an MHLP chunk for dataset type 5 (smart playlist list).

    These playlists define iPod built-in browse categories (Music, Movies,
    TV Shows, Audiobooks, Podcasts, Rentals). Each has a mhsd5_type value
    and smart rules that filter by media type.

    **Master flag semantics for dataset 5:**
    All built-in categories legitimately have ``master=True`` which writes
    ``type=1`` at MHYP offset +0x14.  This is the SAME byte used by the
    master playlist in dataset 2, but the meaning differs:

    - Dataset 2 ``type=1``: "this is the master playlist" (exactly one)
    - Dataset 5 ``type=1``: "this is a built-in system category" (all of them)

    No single-master constraint is enforced here — every ds5 category
    needs ``master=True`` for the iPod firmware to recognise it.

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
