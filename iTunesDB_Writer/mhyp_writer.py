"""
MHYP Writer — Write playlist chunks for iTunesDB.

MHYP chunks define playlists. Every iTunesDB MUST have at least one
playlist — the Master Playlist (MPL) which references all tracks.

Supports three kinds of playlists:
- Master Playlist (hidden=True): references all tracks, includes library indices
- Regular playlists: user-created playlists with explicit track lists
- Smart playlists: rule-based playlists with MHOD types 50 (prefs) and 51 (rules)

Header layout (MHYP_HEADER_SIZE = 184 bytes):
    +0x00: 'mhyp' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + all children
    +0x0C: mhod_count (4B)
    +0x10: mhip_count (4B)
    +0x14: type (1B) + flag1 (1B) + flag2 (1B) + flag3 (1B) — hidden/master flag
    +0x18: timestamp (4B Mac)
    +0x1C: playlist_id (8B)
    +0x24: unk1 (4B)
    +0x28: string_mhod_count (2B)
    +0x2A: podcast_flag (1B) — 0=normal, 1=podcast playlist
    +0x2B: group_flag (1B) — 0=normal, 1=grouping playlist
    +0x2C: sort_order (4B)
    +0x3C: id_0x24 (8B) — MHBD database ID reference (non-master)
    +0x44: playlist_id_copy (8B)
    +0x50: mhsd5_type (2B) — browsing category for dataset 5
    +0x58: timestamp_copy (4B Mac)

Cross-referenced against:
  - iTunesDB_Parser/mhyp_parser.py parse_playlist()
  - libgpod itdb_itunesdb.c: write_playlist() / mk_mhyp()
  - iPodLinux wiki MHYP documentation
"""

import struct
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo

from .mhod_writer import write_mhod_string, MHOD_TYPE_TITLE
from .mhip_writer import write_mhip
from .mhod52_writer import write_library_indices
from .mhod_spl_writer import (
    SmartPlaylistPrefs,
    SmartPlaylistRules,
    write_mhod50,
    write_mhod51,
    write_mhod102,
)


# Playlist type constants
PLAYLIST_TYPE_MASTER = 1  # Master playlist (contains all tracks)
PLAYLIST_TYPE_NORMAL = 0  # Regular user playlist


# MHYP header size - iTunes uses 184 bytes (libgpod uses 108, but iPod Classic rejects it)
MHYP_HEADER_SIZE = 184


@dataclass
class PlaylistItemMeta:
    """Per-item metadata preserved from parsed MHIP entries for round-trip fidelity.

    These fields map directly to MHIP header offsets:
      +0x10: podcast_group_flag (4B)
      +0x14: group_id (4B) — unique MHIP identifier (libgpod: podcastgroupid)
      +0x20: podcast_group_ref (4B) — references another MHIP's group_id
    """
    podcast_group_flag: int = 0
    group_id: int = 0
    podcast_group_ref: int = 0


@dataclass
class PlaylistInfo:
    """Structured input for writing a playlist to iTunesDB.

    Covers regular playlists, smart playlists, and the master playlist.
    The master playlist is constructed internally by write_master_playlist()
    and does not need a PlaylistInfo.
    """
    name: str
    track_ids: List[int] = field(default_factory=list)

    # Identity
    playlist_id: Optional[int] = None   # 64-bit; generated if None
    hidden: bool = False                 # True for master playlist only
    sortorder: int = 0                   # 0=default, 1=manual, 3=title ...
    podcast_flag: int = 0                # 0x2A: 0=normal, 1=podcast playlist
    group_flag: int = 0                  # 0x2B: 0=normal, 1=grouping playlist

    # Smart playlist fields (both must be set for a smart playlist)
    smart_prefs: Optional[SmartPlaylistPrefs] = None
    smart_rules: Optional[SmartPlaylistRules] = None

    # mhsd5Type: browsing category for dataset 5 smart playlists
    # (1=Music, 2=Movies, 3=TV Shows, 4=Music Video, 5=Audiobooks, 6=Podcasts, 7=Rentals)
    mhsd5_type: int = 0

    # Opaque blobs preserved from parsed data for round-trip fidelity
    raw_mhod100: Optional[bytes] = None   # Playlist prefs (type 100 body)
    raw_mhod102: Optional[bytes] = None   # Playlist settings (type 102 body)

    # Per-MHIP metadata preserved from parsed data for round-trip fidelity.
    # When provided, must be the same length as track_ids and in the same order.
    item_metadata: Optional[List[PlaylistItemMeta]] = None

    @property
    def is_smart(self) -> bool:
        return self.smart_prefs is not None and self.smart_rules is not None


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
    podcast_flag: int = 0,
    group_flag: int = 0,
    tracks: Optional[List["TrackInfo"]] = None,
    id_0x24: int = 0,
    smart_prefs: Optional[SmartPlaylistPrefs] = None,
    smart_rules: Optional[SmartPlaylistRules] = None,
    mhsd5_type: int = 0,
    raw_mhod100: Optional[bytes] = None,
    raw_mhod102: Optional[bytes] = None,
    item_metadata: Optional[List[PlaylistItemMeta]] = None,
    capabilities=None,
) -> bytes:
    """
    Write a complete MHYP (playlist) chunk with MHODs and MHIPs.

    The structure is:
    - MHYP header (184 bytes)
    - MHOD title (string)
    - MHOD playlist data (type 100 preferences)
    - [Smart only] MHOD type 50 (smart playlist prefs)
    - [Smart only] MHOD type 51 (smart playlist rules / SLst)
    - [Smart only] MHOD type 102 (playlist settings, if provided)
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
        podcast_flag: 0x2A — 0=normal playlist, 1=podcast playlist.
        group_flag: 0x2B — 0=normal playlist, 1=grouping playlist (iTunes 7).
        tracks: List of TrackInfo objects (required for Master Playlist to
                generate library index MHODs type 52/53)
        id_0x24: Database-wide ID from MHBD offset 0x24. Written at MHYP offset
                 0x3C for non-master playlists, and used as a validation field.
        smart_prefs: Smart playlist preferences (MHOD 50). Both smart_prefs
                     and smart_rules must be set for a smart playlist.
        smart_rules: Smart playlist rules (MHOD 51).
        mhsd5_type: Browsing category for dataset 5 smart playlists.
        raw_mhod100: If provided, use this raw body for MHOD type 100 instead
                     of generating a default one.
        raw_mhod102: If provided, write an MHOD type 102 with this raw body.

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
    if raw_mhod100 is not None:
        mhod_playlist = _write_mhod100_raw(raw_mhod100)
    else:
        mhod_playlist = write_mhod_playlist_prefs()

    # Smart playlist MHODs (type 50 + 51)
    mhod_smart = b''
    smart_mhod_count = 0
    is_smart = smart_prefs is not None and smart_rules is not None
    if is_smart:
        assert smart_prefs is not None and smart_rules is not None
        mhod_smart += write_mhod50(smart_prefs)
        mhod_smart += write_mhod51(smart_rules)
        smart_mhod_count = 2

    # Optional MHOD type 102 (playlist settings — opaque iTunes blob)
    mhod_settings = b''
    settings_count = 0
    if raw_mhod102 is not None:
        mhod_settings = write_mhod102(raw_mhod102)
        settings_count = 1

    # Build library index MHODs for master playlist (type 52/53 pairs)
    # These are REQUIRED for iPod Classic to build its browsing views
    library_indices_data = b''
    library_indices_count = 0
    if hidden and tracks:
        library_indices_data, library_indices_count = write_library_indices(tracks, capabilities=capabilities)

    # Build MHIP entries for each track
    # libgpod's write_playlist_mhips() uses:
    # - podcastgroupid = 0 (MHIP offset 0x14)
    # - MHOD type 100 contains the position index (0, 1, 2, ...)
    #
    # When item_metadata is provided (round-trip from parsed data), we
    # preserve per-MHIP fields: podcastGroupFlag, groupID, podcastGroupRef.
    mhips = []
    for i, track_id in enumerate(track_ids):
        meta = item_metadata[i] if item_metadata and i < len(item_metadata) else None
        mhip = write_mhip(
            track_id, position=i,
            mhip_id=meta.group_id if meta else 0,
            podcast_group_flag=meta.podcast_group_flag if meta else 0,
            podcast_group_ref=meta.podcast_group_ref if meta else 0,
        )
        mhips.append(mhip)
    mhip_data = b''.join(mhips)

    # Count MHODs (title + playlist prefs + smart + settings + library indices)
    mhod_count = 2 + smart_mhod_count + settings_count + library_indices_count

    # Total chunk length
    total_length = (
        MHYP_HEADER_SIZE + len(mhod_title) + len(mhod_playlist) + len(mhod_smart) + len(mhod_settings) + len(library_indices_data) + len(mhip_data)
    )

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

    # +0x2A: Podcast flag (1 byte) — 0=normal, 1=podcast playlist
    # +0x2B: Group flag (1 byte) — 0=normal, 1=grouping playlist
    # Parser reads these as two separate bytes; previous writer used <H (2B).
    header[0x2A] = podcast_flag & 0xFF
    header[0x2B] = group_flag & 0xFF

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

    # +0x50: mhsd5_type — browsing category for dataset 5 smart playlists
    # libgpod writes two consecutive put16lint calls (no gap):
    #   +0x50: mhsd5_type (u16)
    #   +0x52: mhsd5_type (u16, duplicate)
    #   +0x54: special flag (u32) — 1 for MOVIE_RENTALS/RINGTONES, 0 otherwise
    if mhsd5_type:
        struct.pack_into('<H', header, 0x50, mhsd5_type)
        struct.pack_into('<H', header, 0x52, mhsd5_type)
        if mhsd5_type in (6, 7):  # RINGTONES=6, MOVIE_RENTALS=7
            struct.pack_into('<I', header, 0x54, 1)

    # Rest is padding (already zero-initialized)

    return (
        bytes(header) + mhod_title + mhod_playlist + mhod_smart + mhod_settings + library_indices_data + mhip_data
    )


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


def _write_mhod100_raw(raw_body: bytes) -> bytes:
    """Write an MHOD type 100 from a raw body blob (round-trip passthrough).

    Args:
        raw_body: Body bytes (everything after the 24-byte MHOD header).

    Returns:
        Complete MHOD type 100 chunk.
    """
    header_len = 24
    total_len = header_len + len(raw_body)

    header = struct.pack(
        '<4sIIIII',
        b'mhod',
        header_len,
        total_len,
        100,  # type
        0,    # unk1
        0,    # unk2
    )

    return header + raw_body


def write_playlist(
    playlist: "PlaylistInfo",
    id_0x24: int = 0,
) -> bytes:
    """Write a regular or smart playlist from a PlaylistInfo dataclass.

    This is the high-level API for writing any non-master playlist.

    Args:
        playlist: A PlaylistInfo instance.
        id_0x24: Database-wide ID from MHBD offset 0x24.

    Returns:
        Complete MHYP chunk bytes.
    """
    return write_mhyp(
        name=playlist.name,
        track_ids=playlist.track_ids,
        playlist_id=playlist.playlist_id,
        hidden=playlist.hidden,
        sortorder=playlist.sortorder,
        podcast_flag=playlist.podcast_flag,
        group_flag=playlist.group_flag,
        id_0x24=id_0x24,
        smart_prefs=playlist.smart_prefs,
        smart_rules=playlist.smart_rules,
        mhsd5_type=playlist.mhsd5_type,
        raw_mhod100=playlist.raw_mhod100,
        raw_mhod102=playlist.raw_mhod102,
        item_metadata=playlist.item_metadata,
    )


def write_master_playlist(
    track_ids: List[int],
    id_0x24: int,
    name: str = "iPod",
    tracks: Optional[List["TrackInfo"]] = None,
    capabilities=None,
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
        capabilities: Optional DeviceCapabilities for video sort indices.

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
        capabilities=capabilities,
    )
