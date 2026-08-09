"""
MHYP Writer — Write playlist chunks for iTunesDB.

MHYP chunks define playlists. Every iTunesDB MUST have at least one
playlist — the Master Playlist (MPL) which references all tracks.

Supports three kinds of playlists:
- Master Playlist (master=True): references all tracks, includes library indices
- Regular playlists: user-created playlists with explicit track lists
- Smart playlists: rule-based playlists with MHOD types 50 (prefs) and 51 (rules)

Header layout (MHYP_HEADER_SIZE = 184 bytes):
    +0x00: 'mhyp' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + all children
    +0x0C: mhod_count (4B)
    +0x10: mhip_count (4B)
    +0x14: type (1B) + flag1 (1B) + flag2 (1B) + flag3 (1B) — master playlist flag
    +0x18: timestamp (4B Mac)
    +0x1C: playlist_id (8B)
    +0x24: unk1 (4B)
    +0x28: string_mhod_count (2B)
    +0x2A: playlist_kind_flags (2B) — bit 0=podcast, 0x0100=folder
    +0x2C: sort_order (4B)
    +0x3C: db_id_2 (8B) — MHBD database ID reference (non-master)
    +0x44: playlist_id_copy (8B)
    +0x50: mhsd5_type (2B) — browsing category for dataset 5
    +0x52: phase_game_flag (2B) — observed as 25 in Phase Music
    +0x58: timestamp_copy (4B Mac)

Cross-referenced against:
  - src/iopenpod/itunesdb_parser/mhyp_parser.py parse_playlist()
  - libgpod itdb_itunesdb.c: write_playlist() / mk_mhyp()
  - iPodLinux wiki MHYP documentation
"""

import random
import struct
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from iopenpod.itunesdb_shared.constants import MHOD_TYPE_ALBUM, MHOD_TYPE_TITLE
from iopenpod.itunesdb_shared.field_base import write_fields, write_generic_header
from iopenpod.itunesdb_shared.mhod_defs import (
    MHOD_HEADER_SIZE as _MHOD_HEADER_SIZE,
)
from iopenpod.itunesdb_shared.mhod_defs import (
    write_mhod_header,
)
from iopenpod.itunesdb_shared.mhyp_defs import MHYP_HEADER_SIZE
from iopenpod.itunesdb_shared.playlist_kinds import (
    is_playlist_folder,
    is_podcast_playlist,
)
from iopenpod.itunesdb_shared.playlist_kinds import (
    playlist_kind_flags as normalize_playlist_kind_flags,
)

from .mhip_writer import write_mhip, write_mhip_podcast_group
from .mhod52_writer import write_library_indices
from .mhod_spl_writer import (
    SmartPlaylistPrefs,
    SmartPlaylistRules,
    write_mhod50,
    write_mhod51,
    write_mhod55,
    write_mhod102,
)
from .mhod_writer import write_mhod_string

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo


def _display_text(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text or default


@dataclass
class PlaylistItemMeta:
    """Per-item metadata preserved from parsed MHIP entries for round-trip fidelity.

    These fields map directly to MHIP header offsets:
      +0x10: podcast_group_flag (4B)
      +0x14: group_id (4B) — unique MHIP identifier (libgpod: podcastgroupid)
      +0x20: podcast_group_ref (4B) — references another MHIP's group_id
      +0x2C: track_persistent_id (8B) — track's db_track_id
      +0x3C: mhip_persistent_id (8B) — per-track persistent ID
    """
    podcast_group_flag: int = 0
    group_id: int = 0
    podcast_group_ref: int = 0
    track_persistent_id: int = 0
    mhip_persistent_id: int = 0


@dataclass
class PlaylistInfo:
    """Structured input for writing a playlist to iTunesDB.

    Covers regular playlists, smart playlists, and the master playlist.
    The master playlist is constructed internally by write_master_playlist()
    and does not need a PlaylistInfo.
    """
    name: str
    track_ids: list[int] = field(default_factory=list)

    # Identity
    playlist_id: int | None = None   # 64-bit; generated if None
    master: bool = False                 # Sets type byte at +0x14 to 1.
    #   Dataset 2: True for the master playlist only (exactly one).
    #   Dataset 5: sample-dependent category marker; preserve parsed input.
    #   In both cases this controls: (a) the type byte at +0x14,
    #   (b) whether library indices are generated (only when tracks
    #       are also provided), and (c) whether db_id_2/playlist_id
    #       are written at the extended offsets +0x3C/+0x44 (skipped
    #       when master=True, matching libgpod behaviour).
    sortorder: int = 0                   # 0=default, 1=manual, 3=title ...
    # Compatibility spelling for the complete raw word at +0x2A. Historically
    # callers treated any non-zero value as Podcasts; use is_podcast instead.
    podcast_flag: int = 0
    playlist_kind_flags: int | None = None
    parent_folder_playlist_id: int = 0

    # Smart playlist fields (both must be set for a smart playlist)
    smart_prefs: SmartPlaylistPrefs | None = None
    smart_rules: SmartPlaylistRules | None = None

    # mhsd5Type: browsing category for dataset 5 smart playlists
    # (per libgpod: 0=None, 2=Movies, 3=TV Shows, 4=Music, 5=Audiobooks, 6=Ringtones, 7=MovieRentals)
    mhsd5_type: int = 0

    # Exact raw u16 at MHYP +0x52. Observed as 25 (0x0019) on iTunes-created
    # Phase Music playlists; its precise firmware meaning is not yet proven.
    phase_game_flag: int = 0

    # Opaque blobs preserved from parsed data for round-trip fidelity
    raw_mhod100: bytes | None = None   # Playlist prefs (type 100 body)
    raw_mhod102: bytes | None = None   # Playlist settings (type 102 body)
    raw_mhod55: bytes | None = None    # Playlist property plist (type 55 body)
    playlist_description: str | None = None

    # Per-MHIP metadata preserved from parsed data for round-trip fidelity.
    # When provided, must be the same length as track_ids and in the same order.
    item_metadata: list[PlaylistItemMeta] | None = None

    def __post_init__(self) -> None:
        # Keep legacy callers/readers whole while establishing the accurately
        # named field as the canonical representation for new code.
        raw = normalize_playlist_kind_flags(
            self.podcast_flag
            if self.playlist_kind_flags is None
            else self.playlist_kind_flags
        )
        self.playlist_kind_flags = raw
        self.podcast_flag = raw

    @property
    def kind_flags(self) -> int:
        return normalize_playlist_kind_flags(self.playlist_kind_flags)

    @property
    def is_podcast(self) -> bool:
        return is_podcast_playlist(self.kind_flags)

    @property
    def is_folder(self) -> bool:
        return is_playlist_folder(self.kind_flags)

    @property
    def is_smart(self) -> bool:
        return self.smart_prefs is not None and self.smart_rules is not None


def generate_playlist_id() -> int:
    """Generate a random 64-bit playlist ID."""
    return random.getrandbits(64)


def write_mhyp(
    name: str,
    track_ids: list[int],
    playlist_id: int | None = None,
    master: bool = False,
    timestamp: int | None = None,
    sortorder: int = 0,
    podcast_flag: int = 0,
    tracks: list["TrackInfo"] | None = None,
    db_id_2: int = 0,
    smart_prefs: SmartPlaylistPrefs | None = None,
    smart_rules: SmartPlaylistRules | None = None,
    mhsd5_type: int = 0,
    phase_game_flag: int = 0,
    raw_mhod100: bytes | None = None,
    raw_mhod102: bytes | None = None,
    raw_mhod55: bytes | None = None,
    playlist_description: str | None = None,
    item_metadata: list[PlaylistItemMeta] | None = None,
    capabilities=None,
    podcast_grouping: bool = False,
    track_album_map: dict[int, str] | None = None,
    next_mhip_id_start: int = 1,
    playlist_kind_flags: int | None = None,
    parent_folder_playlist_id: int = 0,
) -> bytes:
    """
    Write a complete MHYP (playlist) chunk with MHODs and MHIPs.

    The structure is:
    - MHYP header (184 bytes)
    - MHOD title (string)
    - [Optional] MHOD type 3 playlist description string (iTunes quirk)
    - MHOD playlist data (type 100 preferences)
    - [Smart only] MHOD type 50 (smart playlist prefs)
    - [Smart only] MHOD type 51 (smart playlist rules / SLst)
    - [Optional] MHOD type 102 (playlist settings, if provided)
    - [Optional] MHOD type 55 playlist property plist, if provided
    - [Master Playlist only] MHOD type 52/53 pairs (library indices)
    - MHIP entries (one per track)

    Args:
        name: Playlist name
        track_ids: List of track IDs to include in this playlist
        playlist_id: Playlist ID (generated if not provided)
        master: Whether the type byte at +0x14 should be set to 1.
                For dataset 2 this means "master playlist" (exactly one).
                For dataset 5 this is a sample-dependent category marker, not
                proof that the row is a library master. The behavioural effects are:
                (a) type byte at +0x14 is written as 1,
                (b) library indices are generated IF *tracks* is also
                    provided (ds5 never passes tracks, so this is safe),
                (c) db_id_2 and playlist_id are NOT written at +0x3C/+0x44
                    (matches libgpod, which zeros these for type=1).
        timestamp: Creation timestamp (now if not provided)
        sortorder: Sort order (0 = manual)
        podcast_flag: Compatibility input for the raw +0x2A kind word.
        playlist_kind_flags: Preferred raw +0x2A kind word. Bit 0 marks a
                     podcast playlist and 0x0100 marks a playlist folder.
        parent_folder_playlist_id: Parent folder's 64-bit playlist ID at +0x30.
        tracks: List of TrackInfo objects (required for Master Playlist to
                generate library index MHODs type 52/53)
        db_id_2: Database-wide ID from MHBD offset 0x24. Written at MHYP offset
                 0x3C for non-master playlists, and used as a validation field.
        smart_prefs: Smart playlist preferences (MHOD 50). Both smart_prefs
                     and smart_rules must be set for a smart playlist.
        smart_rules: Smart playlist rules (MHOD 51).
        mhsd5_type: Browsing category for dataset 5 smart playlists.
        phase_game_flag: Exact u16 stored at MHYP +0x52. Observed value 25
                         (0x0019) identifies iTunes-created Phase Music
                         playlists in the sample; its meaning is unproven.
        raw_mhod100: If provided, use this raw body for MHOD type 100 instead
                     of generating a default one.
        raw_mhod102: If provided, write an MHOD type 102 with this raw body.
        raw_mhod55: If provided, write an MHOD type 55 property plist body.
        playlist_description: If provided, write the playlist-description string
                     observed as MHOD type 3 on iTunes-created playlist rows.
        podcast_grouping: When True and this is a podcast playlist, generate
                     grouped MHIPs (libgpod write_podcast_mhips style) where
                     episodes are nested under their podcast show by album.
        track_album_map: Mapping of track_id → album name.  Required when
                     podcast_grouping is True.
        next_mhip_id_start: Starting ID for generated MHIP group_id values
                     (podcast grouping assigns unique IDs to group headers
                     and child MHIPs).

    Returns:
        Complete MHYP chunk bytes
    """
    if playlist_id is None:
        playlist_id = generate_playlist_id()

    if timestamp is None:
        timestamp = int(time.time())

    # Build MHOD for title
    name = _display_text(name, "Playlist")
    mhod_title = write_mhod_string(MHOD_TYPE_TITLE, name)

    # On MHYP playlist rows, iTunes 7-era samples duplicate playlist
    # description text: once as an MHOD type-3 string and again inside MHOD
    # type 55's binary plist. Type 3 is "Album" for tracks, but in this
    # context it is not an album and not a folder marker.
    mhod_description = b''
    description_count = 0
    if playlist_description is not None:
        mhod_description = write_mhod_string(MHOD_TYPE_ALBUM, playlist_description)
        description_count = 1 if mhod_description else 0

    # Build MHOD for playlist preferences (type 100)
    if raw_mhod100 is not None:
        mhod_playlist = _write_mhod100_raw(raw_mhod100)
    else:
        mhod_playlist = write_mhod_playlist_prefs()

    # Smart playlist MHODs (type 50 + 51)
    mhod_smart = b''
    smart_mhod_count = 0
    if smart_prefs is not None and smart_rules is not None:
        mhod_smart += write_mhod50(smart_prefs)
        mhod_smart += write_mhod51(smart_rules)
        smart_mhod_count = 2

    # Optional MHOD type 102 (playlist settings — opaque iTunes blob)
    mhod_settings = b''
    settings_count = 0
    if raw_mhod102 is not None:
        mhod_settings = write_mhod102(raw_mhod102)
        settings_count = 1

    # Optional MHOD type 55 (playlist property plist — opaque passthrough)
    mhod_property_plist = b''
    property_plist_count = 0
    if raw_mhod55 is not None:
        mhod_property_plist = write_mhod55(raw_mhod55)
        property_plist_count = 1

    # Build library index MHODs for master playlist (type 52/53 pairs)
    # These are REQUIRED for iPod Classic to build its browsing views
    library_indices_data = b''
    library_indices_count = 0
    if master and tracks:
        library_indices_data, library_indices_count = write_library_indices(tracks, capabilities=capabilities)

    # Build MHIP entries for each track
    mhip_count: int
    if podcast_grouping and track_album_map is not None:
        # Podcast grouping: group tracks by album (libgpod write_podcast_mhips)
        mhip_data, mhip_count = _build_podcast_grouped_mhips(
            track_ids, track_album_map, next_mhip_id_start,
        )
    else:
        # Standard flat MHIP list (write_playlist_mhips)
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
                track_persistent_id=meta.track_persistent_id if meta else 0,
                mhip_persistent_id=meta.mhip_persistent_id if meta else 0,
            )
            mhips.append(mhip)
        mhip_data = b''.join(mhips)
        mhip_count = len(track_ids)

    # Count MHODs (title + description + playlist prefs + smart + settings +
    # type-55 property plist + library indices)
    mhod_count = (
        2 + description_count + smart_mhod_count + settings_count
        + property_plist_count + library_indices_count
    )

    # Total chunk length
    total_length = (
        MHYP_HEADER_SIZE + len(mhod_title) + len(mhod_description)
        + len(mhod_playlist) + len(mhod_smart) + len(mhod_settings)
        + len(mhod_property_plist) + len(library_indices_data) + len(mhip_data)
    )

    # Build MHYP header
    header = bytearray(MHYP_HEADER_SIZE)
    write_generic_header(header, 0, b'mhyp', MHYP_HEADER_SIZE, total_length)

    # Build values dict for write_fields.
    # Timestamps are Unix epoch — write_transform (unix_to_mac) handles conversion.
    values: dict[str, int] = {
        'mhod_child_count': mhod_count,
        'mhip_child_count': mhip_count,
        'master_flag': 1 if master else 0,
        'timestamp': timestamp,
        'playlist_id': playlist_id,
        'string_mhod_child_count': 1 + description_count,
        'playlist_kind_flags': (
            podcast_flag if playlist_kind_flags is None else playlist_kind_flags
        ),
        'parent_folder_playlist_id': parent_folder_playlist_id,
        'sort_order': sortorder,
        'timestamp_2': timestamp,
    }

    # Non-master playlists write db_id_2 and playlist_id at extended offsets.
    # For master=True (ds2 master and any ds5 category rows that parsed that
    # way), these stay zeroed — matching libgpod behaviour.
    if not master:
        values['db_id_2'] = db_id_2
        values['playlist_id_2'] = playlist_id

    # mhsd5_type is the browsing category at +0x50. libgpod mirrors that
    # value into +0x52 for its dataset-5 categories, so preserve that legacy
    # behaviour when an explicit phase_game_flag is absent. Separately, +0x52
    # is observed as 25 (0x0019) in iTunes-created Phase Music playlists.
    if mhsd5_type:
        values['mhsd5_type'] = mhsd5_type
        if mhsd5_type in (6, 7):
            values['mhsd5_special_flag'] = 1

    effective_phase_game_flag = phase_game_flag or mhsd5_type
    if effective_phase_game_flag:
        values['phase_game_flag'] = effective_phase_game_flag

    write_fields(header, 0, 'mhyp', values, MHYP_HEADER_SIZE)

    return (
        bytes(header) + mhod_title + mhod_description + mhod_playlist
        + mhod_smart + mhod_settings + mhod_property_plist
        + library_indices_data + mhip_data
    )


def _build_podcast_grouped_mhips(
    track_ids: list[int],
    track_album_map: dict[int, str],
    next_id: int,
) -> tuple[bytes, int]:
    """Build podcast-grouped MHIP entries for the type 3 MHSD dataset.

    Groups tracks by album name.  For each album group, emits:
      1. A group header MHIP (``podcast_group_flag=256``, ``track_id=0``,
         MHOD type 1 with the album name)
      2. One child MHIP per track (``podcast_group_flag=0``,
         ``group_id_ref`` pointing to the parent group header's ``group_id``,
         MHOD type 100 with the child's own unique ``mhip_id`` as position)

    This matches libgpod's ``write_podcast_mhips()`` +
    ``write_one_podcast_group()`` in ``itdb_itunesdb.c``.

    Args:
        track_ids: Sequential track IDs for the podcast playlist
        track_album_map: track_id → album name ('' if unknown)
        next_id: Starting value for unique MHIP group_id / mhip_id

    Returns:
        (mhip_bytes, mhip_count) — concatenated MHIPs and the total
        MHIP count (= number of tracks + number of album groups).
    """
    from collections import OrderedDict

    # Group tracks by album, preserving insertion order
    album_groups: OrderedDict[str, list[int]] = OrderedDict()
    for tid in track_ids:
        album = track_album_map.get(tid, "")
        album_groups.setdefault(album, []).append(tid)

    parts: list[bytes] = []
    cur_id = next_id
    total_mhip_count = 0

    for album, tids in album_groups.items():
        # Group header MHIP
        group_id = cur_id
        cur_id += 1
        parts.append(write_mhip_podcast_group(album or "Unknown", group_id))
        total_mhip_count += 1

        # Child MHIPs — one per track in this album group
        for tid in tids:
            mhip_id = cur_id
            cur_id += 1
            parts.append(write_mhip(
                tid, position=mhip_id,
                mhip_id=mhip_id,
                podcast_group_flag=0,
                podcast_group_ref=group_id,
            ))
            total_mhip_count += 1

    return b''.join(parts), total_mhip_count


def write_mhod_playlist_prefs() -> bytes:
    """
    Write the playlist preferences MHOD (type 100).

    This is a binary blob containing display/sorting preferences.
    Based on libgpod's mk_long_mhod_id_playlist().

    Total size: 0x288 (648) bytes as written by iTunes.
    """
    # libgpod mk_long_mhod_id_playlist() writes exactly 0x288 bytes
    # This is critical for proper playlist recognition

    total_len = 0x288  # 648 bytes - exactly what libgpod writes

    # Build complete MHOD type 100
    data = bytearray(total_len)

    # Header (24 bytes) — use shared helper, then overlay onto data buffer
    hdr = write_mhod_header(100, total_len)
    data[:_MHOD_HEADER_SIZE] = hdr

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
    total_len = _MHOD_HEADER_SIZE + len(raw_body)
    return write_mhod_header(100, total_len) + raw_body


def write_playlist(
    playlist: "PlaylistInfo",
    db_id_2: int = 0,
    podcast_grouping: bool = False,
    track_album_map: dict[int, str] | None = None,
    next_mhip_id_start: int = 1,
) -> bytes:
    """Write a playlist from a PlaylistInfo dataclass.

    Handles regular playlists, smart playlists, AND dataset 5 built-in
    categories.  For dataset 5, PlaylistInfo.master will be True (setting
    the type byte at +0x14 to 1) and track_ids will be empty (the iPod
    firmware evaluates smart rules at runtime).

    The *master playlist* for dataset 2 is NOT written through this
    function — use write_master_playlist() instead.

    Args:
        playlist: A PlaylistInfo instance.
        db_id_2: Database-wide ID from MHBD offset 0x24.
        podcast_grouping: When True and the playlist's podcast bit is set,
                     generate grouped MHIPs for podcast episodes.
        track_album_map: track_id → album name (required when
                     podcast_grouping applies).
        next_mhip_id_start: Starting ID for generated MHIP identifiers
                     during podcast grouping.

    Returns:
        Complete MHYP chunk bytes.
    """
    # Only apply podcast grouping to actual podcast playlists
    use_grouping = podcast_grouping and playlist.is_podcast
    return write_mhyp(
        name=playlist.name,
        track_ids=playlist.track_ids,
        playlist_id=playlist.playlist_id,
        master=playlist.master,
        sortorder=playlist.sortorder,
        podcast_flag=playlist.podcast_flag,
        playlist_kind_flags=playlist.kind_flags,
        parent_folder_playlist_id=playlist.parent_folder_playlist_id,
        db_id_2=db_id_2,
        smart_prefs=playlist.smart_prefs,
        smart_rules=playlist.smart_rules,
        mhsd5_type=playlist.mhsd5_type,
        phase_game_flag=playlist.phase_game_flag,
        raw_mhod100=playlist.raw_mhod100,
        raw_mhod102=playlist.raw_mhod102,
        raw_mhod55=playlist.raw_mhod55,
        playlist_description=playlist.playlist_description,
        item_metadata=playlist.item_metadata,
        podcast_grouping=use_grouping,
        track_album_map=track_album_map,
        next_mhip_id_start=next_mhip_id_start,
    )


def write_master_playlist(
    track_ids: list[int],
    db_id_2: int,
    name: str = "iPod",
    tracks: list["TrackInfo"] | None = None,
    capabilities=None,
    playlist_id: int | None = None,
) -> bytes:
    """
    Write the Master Playlist (MPL).

    The master playlist is required and must be the first playlist.
    It contains references to ALL tracks in the database.

    Args:
        track_ids: List of ALL track IDs in the database
        name: Playlist name (usually "iPod" or device name)
        tracks: List of ALL TrackInfo objects (needed for library indices)
        db_id_2: Database-wide ID from MHBD offset 0x24
        capabilities: Optional DeviceCapabilities for video sort indices.

    Returns:
        Complete MHYP chunk for master playlist
    """
    # Master playlist MUST have master=True (0x14 field = 1)
    # This is how iTunes/iPod identifies the master playlist
    return write_mhyp(
        name=name,
        track_ids=track_ids,
        playlist_id=playlist_id,
        master=True,  # CRITICAL: Master playlist must have type=1
        sortorder=5,  # Match iTunes default sort order
        tracks=tracks,
        db_id_2=db_id_2,
        capabilities=capabilities,
    )
