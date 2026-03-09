"""MHIP Writer — Write playlist item chunks for iTunesDB.

MHIP chunks are playlist entries that reference tracks by their ID.
Each playlist (MHYP) contains MHIP entries for each track in the playlist.

The binary layout of the header is defined declaratively in
``iTunesDB_Shared.field_defs.MHIP_FIELDS``.

Cross-referenced against:
  - iTunesDB_Shared/field_defs.py (single source of truth for offsets)
  - iTunesDB_Parser/mhip_parser.py parse_playlistItem()
  - libgpod itdb_itunesdb.c: mk_mhip(), write_podcast_mhips()
"""

import struct

from iTunesDB_Shared.field_base import write_fields, write_generic_header
from iTunesDB_Shared.mhip_defs import MHIP_HEADER_SIZE
from iTunesDB_Shared.mhod_defs import (
    MHOD_HEADER_SIZE as _MHOD_HEADER_SIZE,
    MHOD100_POSITION_BODY_SIZE,
    write_mhod_header,
)
from iTunesDB_Shared.constants import MHOD_TYPE_TITLE


def write_mhip(
    track_id: int,
    position: int = 0,
    mhip_id: int = 0,
    timestamp: int = 0,
    podcast_group_flag: int = 0,
    podcast_group_ref: int = 0,
    track_persistent_id: int = 0,
    mhip_persistent_id: int = 0,
) -> bytes:
    """
    Write an MHIP (playlist item) chunk.

    MHIP entries link tracks to playlists by referencing the track ID.
    Each entry also includes an MHOD type 100 with the position.

    Args:
        track_id: The track's ID (from MHIT)
        position: Position in playlist (0-based)
        mhip_id: Unique ID for this MHIP entry (written at offset 0x14)
                 In libgpod this is called "podcastgroupid" but it's used
                 for ALL playlists as a unique entry identifier.
        timestamp: Mac timestamp (usually 0)
        podcast_group_flag: For podcast grouping (usually 0)
        podcast_group_ref: For podcast grouping (usually 0)
        track_persistent_id: The track's db_id (persistent identifier)
        mhip_persistent_id: Per-track persistent ID for this playlist item

    Returns:
        Complete MHIP chunk bytes
    """
    mhod_position = write_mhod_position(position)
    total_length = MHIP_HEADER_SIZE + len(mhod_position)

    header = bytearray(MHIP_HEADER_SIZE)
    write_generic_header(header, 0, b'mhip', MHIP_HEADER_SIZE, total_length)
    write_fields(header, 0, 'mhip', {
        'child_count': 1,
        'podcast_group_flag': podcast_group_flag,
        'group_id': mhip_id,
        'track_id': track_id,
        'timestamp': timestamp,
        'group_id_ref': podcast_group_ref,
        'track_persistent_id': track_persistent_id,
        'mhip_persistent_id': mhip_persistent_id,
    }, MHIP_HEADER_SIZE)

    return bytes(header) + mhod_position


def write_mhod_position(position: int) -> bytes:
    """
    Write an MHOD type 100 (playlist position).

    This MHOD is attached to each MHIP and indicates the track's
    position within the playlist.

    Args:
        position: Track position in playlist (0-based)

    Returns:
        MHOD chunk bytes
    """
    total_len = _MHOD_HEADER_SIZE + MHOD100_POSITION_BODY_SIZE
    header = write_mhod_header(100, total_len)

    # Data section: position(4) + padding(16)
    data = struct.pack('<I', position) + (b'\x00' * 16)

    return header + data


def write_mhip_podcast_group(album_name: str, group_id: int) -> bytes:
    """Write a podcast group header MHIP.

    In the type 3 (podcast) MHSD dataset, episodes are grouped under
    their podcast show.  Each show gets a "group header" MHIP that
    serves as a parent node.  Child episode MHIPs reference it via
    ``group_id_ref``.

    Group header MHIPs differ from regular MHIPs:
      - ``podcast_group_flag`` = 256 (0x100)
      - ``track_id`` = 0 (no track reference)
      - Contains an MHOD type 1 (title) with the album/show name
        instead of an MHOD type 100 (position)

    This matches libgpod's ``write_one_podcast_group()`` in
    ``itdb_itunesdb.c``.

    Args:
        album_name: Podcast show / album name for the group header
        group_id:   Unique identifier for this group (child MHIPs
                    reference this value in their ``group_id_ref`` field)

    Returns:
        Complete MHIP chunk bytes (header + MHOD title)
    """
    from .mhod_writer import write_mhod_string

    mhod_title = write_mhod_string(MHOD_TYPE_TITLE, album_name)
    total_length = MHIP_HEADER_SIZE + len(mhod_title)

    header = bytearray(MHIP_HEADER_SIZE)
    write_generic_header(header, 0, b'mhip', MHIP_HEADER_SIZE, total_length)
    write_fields(header, 0, 'mhip', {
        'child_count': 1,
        'podcast_group_flag': 256,  # 0x100 = podcast group header
        'group_id': group_id,
        'track_id': 0,             # group headers don't reference a track
    }, MHIP_HEADER_SIZE)

    return bytes(header) + mhod_title
