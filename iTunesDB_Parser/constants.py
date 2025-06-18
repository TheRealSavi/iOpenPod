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
    0x09: "iTunes 4.2",
    0x0a: "iTunes 4.5",
    0x0b: "iTunes 4.7",
    0x0c: "iTunes 4.71/4.8",
    0x0d: "iTunes 4.9",
    0x0e: "iTunes 5",
    0x0f: "iTunes 6",
    0x10: "iTunes 6.0.1 (Likely)",
    0x11: "iTunes 6.0.2 to 6.0.4",
    0x12: "iTunes 6.0.5",
    0x13: "iTunes 7.0",
    0x14: "iTunes 7.1",
    0x15: "iTunes 7.2",
    0x16: "Unknown Version",
    0x17: "iTunes 7.3.0",
    0x18: "iTunes 7.3.1 to 7.3.2",
    0x19: "iTunes 7.4"
}

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
