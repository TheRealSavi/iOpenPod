# maps the id used in mhsd to the proper header marker
chunk_type_map = {
    1: "mhlt",  # track list chunk
    2: "mhlp",  # playlist list chunk
    3: "mhlp",  # podcast list, same identifer as playlist, but has slight differnce
    4: "mhla",  # Album Lists (iTunes 7.1>)
    5: "mhsp",  # Smart playlist list (iTunes 7.3>)
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
# the identifier appears to be backward, I estimate that it should read something like
# DataBaseHeaderMarker(DBHM) and DataStructureHeaderMarker(DSHM) and
# TrackListHeaderMarker(TLHM)...
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
    50: "Smart Playlist Data",
    51: "Smart Playlist Rules",
    52: "Library Playlist Index",
    53: "Unknown similar to MHOD52",
    100: "Column Size or Playlist Order",
    200: "Album (Used by Album Item)",
    201: "Artist (Used by Album Item)",
    202: "Sort Artist (Used by Album Item)",
    203: "Podcast URL (Used by Album Item)",
    204: "Show (Used by Album Item)"
}
