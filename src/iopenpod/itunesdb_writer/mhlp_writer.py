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
- Dataset 3 playlist rows (explicit dataset-3 rows, or a dataset-2 clone only
  when the caller has no dataset-3 rows to preserve)
- Dataset 5 smart playlists (write_mhlp_smart)

Cross-referenced against:
  - src/iopenpod/itunesdb_parser/mhlp_parser.py
  - libgpod itdb_itunesdb.c: mk_mhlp()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo
    from .mhyp_writer import PlaylistInfo

from iopenpod.itunesdb_shared.field_base import (
    MHLP_HEADER_SIZE,
    write_list_chunk,
    write_list_header,
)

from .mhyp_writer import write_master_playlist, write_playlist


def write_mhlp_empty() -> bytes:
    """
    Write an empty MHLP (playlist list) chunk.

    Note: An empty MHLP means NO playlists, which may cause issues
    on some iPods. Use write_mhlp_with_playlists() for a valid database.

    Returns:
        MHLP header with 0 playlists
    """
    return write_list_header(b'mhlp', MHLP_HEADER_SIZE, 0)


def write_mhlp(playlist_chunks: list[bytes]) -> bytes:
    """
    Write a MHLP chunk with playlists.

    Args:
        playlist_chunks: List of MHYP (playlist) chunks

    Returns:
        Complete MHLP chunk
    """
    return write_list_chunk(b'mhlp', MHLP_HEADER_SIZE, playlist_chunks)


def write_mhlp_with_playlists(
    track_ids: list[int],
    playlists: list[PlaylistInfo],
    db_id_2,
    tracks: list[TrackInfo] | None = None,
    capabilities=None,
    master_playlist_name: str = "iPod",
    master_playlist_id: int | None = None,
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
        db_id_2: Database-wide ID from MHBD offset 0x24
        capabilities: Optional DeviceCapabilities for video sort indices.
        master_playlist_name: Display name for the auto-generated master playlist.

    Returns:
        Complete MHLP chunk
    """
    chunks = []

    # Master playlist MUST be first
    master = write_master_playlist(
        track_ids, tracks=tracks, db_id_2=db_id_2,
        capabilities=capabilities, name=master_playlist_name,
        playlist_id=master_playlist_id,
    )
    chunks.append(master)

    # Write all user playlists (regular and smart).
    for pl in playlists:
        chunks.append(write_playlist(pl, db_id_2=db_id_2))

    return write_mhlp(chunks)


def write_mhlp_with_playlists_type3(
    track_ids: list[int],
    playlists: list[PlaylistInfo],
    db_id_2: int,
    track_album_map: dict[int, str],
    tracks: list[TrackInfo] | None = None,
    capabilities=None,
    master_playlist_name: str = "iPod",
    next_mhip_id_start: int = 1,
    master_playlist_id: int | None = None,
) -> bytes:
    """Write an MHLP for MHSD type 3 with podcast-aware grouping.

    Dataset 3 is structurally another MHLP, but firmware treats it as the
    type-3 playlist list. Playlist rows are not reclassified here;
    the only dataset-3-specific write behavior is that entries marked as
    podcast (``podcast_flag == 1``) use the grouped MHIP structure described
    by libgpod's ``write_podcast_mhips()``.

    In the grouped structure, podcast episodes are nested under their
    podcast show (album).  Each show gets a group-header MHIP
    (``podcast_group_flag=256``, MHOD title = album name) followed by
    child episode MHIPs whose ``group_id_ref`` points back to the header.

    Non-podcast playlists are written with the standard flat MHIP layout,
    identical to type 2.

    Args:
        track_ids: ALL track IDs in the database (for the master playlist)
        playlists: Dataset-3 playlist rows (or dataset-2 rows when the caller
                   intentionally uses the libgpod-compatible clone fallback).
                   The master row is auto-generated.
        db_id_2: Database-wide ID from MHBD offset 0x24
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
        track_ids, tracks=tracks, db_id_2=db_id_2,
        capabilities=capabilities, name=master_playlist_name,
        playlist_id=master_playlist_id,
    )
    chunks.append(master)

    for pl in playlists:
        chunks.append(write_playlist(
            pl, db_id_2=db_id_2,
            podcast_grouping=True,
            track_album_map=track_album_map,
            next_mhip_id_start=next_mhip_id_start,
        ))

    return write_mhlp(chunks)


def write_mhlp_smart(
    playlists: list[PlaylistInfo],
    db_id_2: int = 0,
) -> bytes:
    """
    Write an MHLP chunk for dataset type 5 (smart playlist list).

    These playlists define iPod built-in browse categories (Music, Movies,
    TV Shows, Audiobooks, Podcasts, Rentals). Each has a mhsd5_type value
    and smart rules that filter by media type.

    **Master flag semantics for dataset 5:**
    Built-in categories often have ``master=True`` which writes ``type=1`` at
    MHYP offset +0x14.  This is the SAME byte used by the master playlist in
    dataset 2, but the meaning differs:

    - Dataset 2 ``type=1``: "this is the master playlist" (exactly one)
    - Dataset 5 ``type=1``: "this is a built-in system category" (all of them)

    No single-master constraint is enforced here, and this writer does not
    synthesize the flag from ``mhsd5_type``. If a device sample carries a
    surprising value, preserve it so the sample remains useful.

    Args:
        playlists: List of PlaylistInfo objects (smart playlists only)
        db_id_2: Database-wide ID from MHBD offset 0x24

    Returns:
        Complete MHLP chunk, or empty MHLP if no smart playlists
    """
    if not playlists:
        return write_mhlp_empty()

    chunks = []
    for pl in playlists:
        chunks.append(write_playlist(pl, db_id_2=db_id_2))

    return write_mhlp(chunks)
