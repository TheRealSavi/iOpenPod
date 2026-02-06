"""
MHYP Writer - Write playlist chunks for iTunesDB.

MHYP chunks define playlists. Every iTunesDB MUST have at least one
playlist - the Master Playlist (MPL) which references all tracks.

Based on libgpod's write_playlist() and mk_mhyp in itdb_itunesdb.c
"""

import struct
import random
import time
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhod_writer import write_mhod_string, MHOD_TYPE_TITLE
from .mhip_writer import write_mhip
from .mhod52_writer import write_library_indices


# Playlist type constants
PLAYLIST_TYPE_MASTER = 1  # Master playlist (contains all tracks)
PLAYLIST_TYPE_NORMAL = 0  # Regular user playlist


# MHYP header size - iTunes uses 184 bytes (libgpod uses 108, but iPod Classic rejects it)
MHYP_HEADER_SIZE = 184


def generate_playlist_id() -> int:
    """Generate a random 64-bit playlist ID."""
    return random.getrandbits(64)


# Mac HFS+ epoch starts 1904-01-01, Unix epoch 1970-01-01
MAC_EPOCH_OFFSET = 2082844800


def unix_to_mac_timestamp(unix_timestamp: int) -> int:
    """Convert Unix timestamp to Mac HFS+ timestamp."""
    if unix_timestamp == 0:
        return 0
    return unix_timestamp + MAC_EPOCH_OFFSET


def write_mhyp(
    name: str,
    track_ids: List[int],
    playlist_type: int = PLAYLIST_TYPE_NORMAL,  # DEPRECATED: use hidden param instead
    playlist_id: Optional[int] = None,
    hidden: bool = False,
    timestamp: Optional[int] = None,
    sortorder: int = 0,
    tracks: Optional[List["TrackInfo"]] = None,
    id_0x24: int = 0,
) -> bytes:
    """
    Write a complete MHYP (playlist) chunk with MHODs and MHIPs.

    The structure is:
    - MHYP header (184 bytes)
    - MHOD title (string)
    - MHOD playlist data (type 100 preferences)
    - [Master Playlist only] MHOD type 52/53 pairs (library indices)
    - MHIP entries (one per track)

    Args:
        name: Playlist name
        track_ids: List of track IDs to include in this playlist
        playlist_type: DEPRECATED - playlist type is determined by 'hidden' param.
                       For Master Playlist, use hidden=True.
        playlist_id: Playlist ID (generated if not provided)
        hidden: Whether playlist is hidden (True for Master Playlist, False for normal)
                The 'type' byte at offset 0x14 is set to 1 if hidden=True (MPL).
        timestamp: Creation timestamp (now if not provided)
        sortorder: Sort order (0 = manual)
        tracks: List of TrackInfo objects (required for Master Playlist to
                generate library index MHODs type 52/53)
        id_0x24: Database-wide ID from MHBD offset 0x24. Written at MHYP offset
                 0x3C for non-master playlists, and used as a validation field.

    Returns:
        Complete MHYP chunk bytes
    """
    if playlist_id is None:
        playlist_id = generate_playlist_id()

    if timestamp is None:
        timestamp = int(time.time())

    # Build MHOD for title
    mhod_title = write_mhod_string(MHOD_TYPE_TITLE, name)

    # Build MHOD for playlist preferences (type 100)
    # This is a binary blob that iTunes uses for display settings
    mhod_playlist = write_mhod_playlist_prefs()

    # Build library index MHODs for master playlist (type 52/53 pairs)
    # These are REQUIRED for iPod Classic to build its browsing views
    library_indices_data = b''
    library_indices_count = 0
    if hidden and tracks:
        library_indices_data, library_indices_count = write_library_indices(tracks)

    # Build MHIP entries for each track
    # libgpod's write_playlist_mhips() uses:
    # - podcastgroupid = 0 (MHIP offset 0x14)
    # - MHOD type 100 contains the position index (0, 1, 2, ...)
    #
    # Note: iTunes uses a unique ID at offset 0x14 and stores it in MHOD too,
    # but libgpod's approach (using 0) works fine with all iPods.
    mhips = []
    for i, track_id in enumerate(track_ids):
        # mhip_id=0 matches libgpod behavior for regular (non-podcast) playlists
        mhip = write_mhip(track_id, position=i, mhip_id=0)
        mhips.append(mhip)
    mhip_data = b''.join(mhips)

    # Count MHODs (title + playlist prefs + library indices)
    mhod_count = 2 + library_indices_count

    # Total chunk length
    total_length = MHYP_HEADER_SIZE + len(mhod_title) + len(mhod_playlist) + len(library_indices_data) + len(mhip_data)

    # Build MHYP header (108 bytes)
    header = bytearray(MHYP_HEADER_SIZE)

    # +0x00: Magic
    header[0:4] = b'mhyp'

    # +0x04: Header length
    struct.pack_into('<I', header, 0x04, MHYP_HEADER_SIZE)

    # +0x08: Total length
    struct.pack_into('<I', header, 0x08, total_length)

    # +0x0C: Number of MHODs
    struct.pack_into('<I', header, 0x0C, mhod_count)

    # +0x10: Number of MHIPs (tracks in playlist)
    struct.pack_into('<I', header, 0x10, len(track_ids))

    # +0x14: Hidden flag (0 = visible, 1 = hidden)
    struct.pack_into('<I', header, 0x14, 1 if hidden else 0)

    # +0x18: Timestamp (Mac format)
    struct.pack_into('<I', header, 0x18, unix_to_mac_timestamp(timestamp))

    # +0x1C: Playlist ID (64-bit)
    struct.pack_into('<Q', header, 0x1C, playlist_id)

    # +0x24: Unknown (always 0?)
    struct.pack_into('<I', header, 0x24, 0)

    # +0x28: String MHOD count (usually 1 for title)
    struct.pack_into('<H', header, 0x28, 1)

    # +0x2A: Podcast flag
    struct.pack_into('<H', header, 0x2A, 0)

    # +0x2C: Sort order
    struct.pack_into('<I', header, 0x2C, sortorder)

    # +0x30-0xB7: Extended header fields (184-byte iTunes format)
    #
    # For NON-MASTER playlists, iTunes writes:
    #   0x3C: id_0x24 from MHBD (u64) - database identity validation
    #   0x44: playlist_id again (u64) - redundant copy
    #
    # For the MASTER playlist:
    #   0x58: Mac timestamp (u32) - creation/modification time
    #
    # These are NOT written by libgpod (which uses 108-byte headers), but since
    # we use 184-byte headers to match iTunes, the iPod firmware may parse them.
    if not hidden:
        # Non-master playlist: write id_0x24 and playlist_id in extended area
        struct.pack_into('<Q', header, 0x3C, id_0x24)
        struct.pack_into('<Q', header, 0x44, playlist_id)

    # Both master and non-master get a timestamp at 0x58
    struct.pack_into('<I', header, 0x58, unix_to_mac_timestamp(timestamp))

    # Rest is padding (already zero-initialized)

    return bytes(header) + mhod_title + mhod_playlist + library_indices_data + mhip_data


def write_mhod_playlist_prefs() -> bytes:
    """
    Write the playlist preferences MHOD (type 100).

    This is a binary blob containing display/sorting preferences.
    Based on libgpod's mk_long_mhod_id_playlist().

    Total size: 0x288 (648) bytes as written by iTunes.
    """
    # libgpod mk_long_mhod_id_playlist() writes exactly 0x288 bytes
    # This is critical for proper playlist recognition

    header_len = 0x18  # 24 bytes
    total_len = 0x288  # 648 bytes - exactly what libgpod writes

    # Build complete MHOD type 100
    data = bytearray(total_len)

    # Header
    data[0:4] = b'mhod'
    struct.pack_into('<I', data, 4, header_len)  # header length
    struct.pack_into('<I', data, 8, total_len)   # total length
    struct.pack_into('<I', data, 12, 100)        # type = 100 (MHOD_ID_PLAYLIST)
    struct.pack_into('<I', data, 16, 0)          # unknown1
    struct.pack_into('<I', data, 20, 0)          # unknown2

    # Body data - based on libgpod mk_long_mhod_id_playlist()
    # Offset 0x18 (after header):
    struct.pack_into('<I', data, 0x18, 0)        # 6 x 0s
    struct.pack_into('<I', data, 0x1C, 0)
    struct.pack_into('<I', data, 0x20, 0)
    struct.pack_into('<I', data, 0x24, 0)
    struct.pack_into('<I', data, 0x28, 0)
    struct.pack_into('<I', data, 0x2C, 0)

    struct.pack_into('<I', data, 0x30, 0x010084)  # magic value from libgpod
    struct.pack_into('<I', data, 0x34, 0x05)      # ?
    struct.pack_into('<I', data, 0x38, 0x09)      # ?
    struct.pack_into('<I', data, 0x3C, 0x03)      # ?
    struct.pack_into('<I', data, 0x40, 0x120001)  # ?
    struct.pack_into('<I', data, 0x44, 0)         # ?
    struct.pack_into('<I', data, 0x48, 0)         # ?
    struct.pack_into('<I', data, 0x4C, 0x640014)  # ?
    struct.pack_into('<I', data, 0x50, 0x01)      # bool? (visible?)
    struct.pack_into('<I', data, 0x54, 0)         # 2x0
    struct.pack_into('<I', data, 0x58, 0)
    struct.pack_into('<I', data, 0x5C, 0x320014)  # ?
    struct.pack_into('<I', data, 0x60, 0x01)      # bool? (visible?)
    struct.pack_into('<I', data, 0x64, 0)         # 2x0
    struct.pack_into('<I', data, 0x68, 0)
    struct.pack_into('<I', data, 0x6C, 0x5a0014)  # ?
    struct.pack_into('<I', data, 0x70, 0x01)      # bool? (visible?)
    struct.pack_into('<I', data, 0x74, 0)         # 2x0
    struct.pack_into('<I', data, 0x78, 0)
    struct.pack_into('<I', data, 0x7C, 0x500014)  # ?
    struct.pack_into('<I', data, 0x80, 0x01)      # bool? (visible?)
    struct.pack_into('<I', data, 0x84, 0)         # 2x0
    struct.pack_into('<I', data, 0x88, 0)
    struct.pack_into('<I', data, 0x8C, 0x7d0015)  # ?
    struct.pack_into('<I', data, 0x90, 0x01)      # bool? (visible?)
    # Rest is zeros (padding to 0x288)

    return bytes(data)


def write_master_playlist(
    track_ids: List[int],
    name: str = "iPod",
    tracks: Optional[List["TrackInfo"]] = None,
    id_0x24: int = 0,
) -> bytes:
    """
    Write the Master Playlist (MPL).

    The master playlist is required and must be the first playlist.
    It contains references to ALL tracks in the database.

    Args:
        track_ids: List of ALL track IDs in the database
        name: Playlist name (usually "iPod" or device name)
        tracks: List of ALL TrackInfo objects (needed for library indices)
        id_0x24: Database-wide ID from MHBD offset 0x24

    Returns:
        Complete MHYP chunk for master playlist
    """
    # Master playlist MUST have hidden=True (0x14 field = 1)
    # This is how iTunes/iPod identifies the master playlist
    return write_mhyp(
        name=name,
        track_ids=track_ids,
        playlist_type=PLAYLIST_TYPE_MASTER,
        hidden=True,  # CRITICAL: Master playlist must have hidden=1
        sortorder=5,  # Match iTunes default sort order
        tracks=tracks,
        id_0x24=id_0x24,
    )
