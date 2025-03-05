# maps the id used in mhsd to the proper header marker
chunk_type_map = {
    1: "mhli",  # Image List chunk
    2: "mhla",  # Photo ALbum List chunk
    3: "mhlf",  # File List Chunk
}

# maps the chunk header marker to a readable name
# the identifier appears to be backward, I estimate that it should read something like
# DataBaseHeaderMarker(DBHM) and DataStructureHeaderMarker(DSHM) and
# TrackListHeaderMarker(TLHM)...
identifier_readable_map = {
    "mhfd": "Data File",
    "mhsd": "Data Set",
    "mhli": "Image List",
    "mhii": "Image Item",
    "mhni": "Image Name",
    "mhla": "Photo Album List",
    "mhba": "Photo Album",
    "mhia": "Photo Album Item",
    "mhlf": "File List",
    "mhif": "File List Item",
    "mhod": "Data Object",
}

# maps the mhod type to its readable name
# There are 2 groups of types of MHODs in the ArtworkDB:
# container MHODs contain a MHNI as a child,
# while 'normal' string MHODs contain a string.

mhod_type_map = {
    1: {"type": "String", "name": "Album Name"},
    2: {"type": "Container", "name": "Thumbnail Image"},
    3: {"type": "String", "name": "File Name"},
    5: {"type": "Container", "name": "Full Res Image"},
    6: {"type": "Container", "name": "UNK MHOD 6"},
}
