"""
iTunesDB constants — chunk identifiers, version maps, MHOD type definitions,
media type bitmask, and playlist sort order values.

Cross-referenced against:
  - iPodLinux wiki: https://web.archive.org/web/20081006030946/http://ipodlinux.org/wiki/ITunesDB
  - libgpod itdb_itunesdb.c, itdb.h
"""

# maps the id used in mhsd to the proper header marker
chunk_type_map = {
    1: "mhlt",  # Track list (contains MHIT children)
    2: "mhlp",  # Playlist list (contains MHYP children) — regular playlists
    3: "mhlp_podcast",  # Podcast list (same MHLP format, different dataset)
                        # NOTE: Type 3 MHSD MUST come between type 1 and type 2
                        # for the iPod to list podcasts correctly.
    4: "mhla",  # Album list (iTunes 7.1+; contains MHIA children)
    5: "mhsp",  # Smart playlist list (iTunes 7.3+; contains MHYP children)
    # Types 6–10 were added in iTunes 9+ for Genius and other features.
    # Their child chunk reuses the 'mhli' magic (same as ArtworkDB's image
    # list, but here it is a generic item list — different semantics).
    # We skip their contents but must recognise them to avoid crashing.
    6: "mhsd_type_6",   # Genius suggestions list
    7: "mhsd_type_7",   # (reserved, rarely seen)
    8: "mhsd_type_8",   # (reserved, rarely seen)
    9: "mhsd_type_9",   # Genius Chill list
    10: "mhsd_type_10",  # Genius Mix list
}

# maps the database version to an iTunes version
version_map = {
    0x01: "iTunes 1.0",
    0x02: "iTunes 2.0",
    0x03: "iTunes 3.0",
    0x04: "iTunes 4.0",
    0x05: "iTunes 4.0.1",
    0x06: "iTunes 4.1",
    0x07: "iTunes 4.1.1",
    0x08: "iTunes 4.1.2",
    0x09: "iTunes 4.2",
    0x0a: "iTunes 4.5",
    0x0b: "iTunes 4.7",
    0x0c: "iTunes 4.71/4.8",
    0x0d: "iTunes 4.9",
    0x0e: "iTunes 5",
    0x0f: "iTunes 6",
    0x10: "iTunes 6.0.1",
    0x11: "iTunes 6.0.2-6.0.4",
    0x12: "iTunes 6.0.5",
    0x13: "iTunes 7.0",
    0x14: "iTunes 7.1",
    0x15: "iTunes 7.2",
    0x16: "Unknown (0x16)",
    0x17: "iTunes 7.3.0",
    0x18: "iTunes 7.3.1-7.3.2",
    0x19: "iTunes 7.4",
    0x1a: "iTunes 7.4.1",
    0x1b: "iTunes 7.4.2",
    0x1c: "iTunes 7.5",
    0x1d: "iTunes 7.6",
    0x1e: "iTunes 7.7",
    0x1f: "iTunes 8.0",
    0x20: "iTunes 8.0.1",
    0x21: "iTunes 8.0.2",
    0x22: "iTunes 8.1",
    0x23: "iTunes 8.1.1",
    0x24: "iTunes 8.2",
    0x25: "iTunes 8.2.1",
    0x26: "iTunes 9.0",
    0x27: "iTunes 9.0.1",
    0x28: "iTunes 9.0.2",
    0x29: "iTunes 9.0.3",
    0x2a: "iTunes 9.1",
    0x2b: "iTunes 9.1.1",
    0x2c: "iTunes 9.2",
    0x2d: "iTunes 9.2.1",
    0x30: "iTunes 9.2+",
    # Extended versions for newer databases
    0x40: "iTunes 10.x",
    0x50: "iTunes 11.x",
    0x60: "iTunes 12.x",
    0x70: "iTunes 12.5+",
    0x75: "iTunes 12.9+",
}


def get_version_name(version_hex: int | str) -> str:
    """
    Get iTunes version name from database version number.

    Args:
        version_hex: Version as int (0x19) or hex string ('0x19')

    Returns:
        Human-readable version string
    """
    if isinstance(version_hex, str):
        # Remove '0x' prefix if present and convert
        version_hex = int(version_hex, 16) if version_hex.startswith('0x') else int(version_hex)

    if version_hex in version_map:
        return version_map[version_hex]

    # If not exact match, find closest lower version
    lower_versions = [v for v in version_map.keys() if v <= version_hex]
    if lower_versions:
        closest = max(lower_versions)
        return f"{version_map[closest]} (or newer)"

    return f"Unknown (version {hex(version_hex)})"


# maps the chunk header marker to a readable name
# The identifiers read backwards conceptually — the convention is:
#   mhbd = DataBase Header Marker     mhsd = DataSet Header Marker
#   mhlt = Track List Header Marker   mhit = Track Item Header Marker
#   mhlp = Playlist List Header Marker mhla = Album List Header Marker
#   mhyp = plaYlist Header Marker     mhip = playlist Item Header Marker
#   mhia = album Item Header Marker   mhod = Data Object Header Marker
identifier_readable_map = {
    "mhbd": "Database",
    "mhsd": "Dataset",
    "mhlt": "Track List",
    "mhlp": "Playlist or Podcast List",
    "mhla": "Album List",
    "mhsp": "Smart Playlist List",
    "mhia": "Album Item",
    "mhit": "Track Item",
    "mhyp": "Playlist",
    "mhod": "Data Object",
    "mhip": "Playlist Item",
}

# maps the mhod type to its readable name
#
# Types 1-14:   Track string MHODs (standard sub-header at offset 24)
# Types 15-16:  Podcast URL MHODs (UTF-8 string at offset 24, NO sub-header)
# Type 17:      Chapter data (big-endian atom-based binary blob)
# Types 18-31:  Track string MHODs (standard sub-header)
# Type 32:      Unknown binary data for video tracks (not a string!)
# Types 33-44:  Track string MHODs (standard sub-header)
# Type 50:      Smart playlist preferences (SPLPref binary)
# Type 51:      Smart playlist rules (SLst — BIG-endian binary)
# Type 52:      Library playlist sorted index (binary)
# Type 53:      Library playlist jump table (binary)
# Type 100:     Playlist column prefs (MHYP child) or position (MHIP child)
# Type 102:     Playlist settings (post-iTunes 7, binary blob)
# Types 200-204: Album item string MHODs (standard sub-header)
mhod_type_map = {
    1: "Title",
    2: "Location",
    3: "Album",
    4: "Artist",
    5: "Genre",
    6: "Filetype",
    7: "EQ Setting",
    8: "Comment",
    9: "Category",
    10: "Lyrics",
    12: "Composer",
    13: "Grouping",
    14: "Description Text",
    15: "Podcast Enclosure URL",
    16: "Podcast RSS URL",
    17: "Chapter Data",
    18: "Subtitle",
    19: "Show",
    20: "Episode",
    21: "TV Network",
    22: "Album Artist",
    23: "Sort Artist",
    24: "Track Keywords",
    25: "Show Locale",
    27: "Sort Title",
    28: "Sort Album",
    29: "Sort Album Artist",
    30: "Sort Composer",
    31: "Sort Show",
    32: "Unknown for Video Track",
    33: "Unknown (33)",
    34: "Unknown (34)",
    35: "Unknown (35)",
    36: "Unknown (36)",
    37: "Content Provider",
    38: "Unknown (38)",
    39: "Copyright",
    40: "Unknown (40)",
    41: "Unknown (41)",
    42: "Unknown (42)",
    43: "Purchase Account",
    44: "Purchaser Name",
    50: "Smart Playlist Data",
    51: "Smart Playlist Rules",
    52: "Library Playlist Index",
    53: "Library Playlist Jump Table",
    100: "Column Size or Playlist Order",
    102: "Playlist Settings (binary)",
    200: "Album (Used by Album Item)",
    201: "Artist (Used by Album Item)",
    202: "Sort Artist (Used by Album Item)",
    203: "Podcast URL (Used by Album Item)",
    204: "Show (Used by Album Item)"
}


# ============================================================
# Media Type bitmask values (MHIT offset 208 / 0xD0)
# From libgpod ItdbMediatype enum and iPodLinux wiki.
# ============================================================
MEDIA_TYPE_MAP = {
    0x00000000: "Audio/Video",    # shows in both audio and video menus
    0x00000001: "Audio",
    0x00000002: "Video",          # Movie
    0x00000004: "Podcast",
    0x00000006: "Video Podcast",
    0x00000008: "Audiobook",
    0x00000020: "Music Video",
    0x00000040: "TV Show",
    0x00000060: "TV Show (alt)",
    0x00000100: "Ringtone",        # libgpod ITDB_MEDIATYPE_RINGTONE (1 << 8)
    0x00000200: "Rental",         # iTunes rental movie
    0x00004000: "Ringtone (alt)",  # Alternate ringtone value (some firmware)
    0x00040000: "iTunes Pass",
    0x00060000: "Memo / Voice Memo",
}


# ============================================================
# Playlist Sort Order (MHYP offset 44 / 0x2C)
# From iPodLinux wiki "List Sort Order" and libgpod ItdbPlaylistSortOrder.
# ============================================================
PLAYLIST_SORT_ORDER_MAP = {
    0: "default (unset)",
    1: "playlist order (manual)",
    # 2: unknown
    3: "title",
    4: "album",
    5: "artist",
    6: "bitrate",
    7: "genre",
    8: "kind",
    9: "date modified",
    10: "track number",
    11: "size",
    12: "time",
    13: "year",
    14: "sample rate",
    15: "comment",
    16: "date added",
    17: "equalizer",
    18: "composer",
    # 19: unknown
    20: "play count",
    21: "last played",
    22: "disc number",
    23: "my rating",
    24: "release date",     # used for Podcasts list
    25: "BPM",
    26: "grouping",
    27: "category",
    28: "description",
    29: "show",
    30: "season",
    31: "episode number",
}


# ============================================================
# Explicit / content advisory flag values (MHIT offset 146 / 0x92)
# ============================================================
EXPLICIT_FLAG_MAP = {
    0: "none",
    1: "explicit",
    2: "clean",
}
