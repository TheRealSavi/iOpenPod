"""
MHSD (DataSet) parser.

MHSD is a container that holds exactly one child list, determined by its
type field at offset 12:

    Type 1  → MHLT (Track List)
    Type 2  → MHLP (Playlist List — regular playlists)
    Type 3  → MHLP (Podcast List — podcast playlists; same format as type 2)
    Type 4  → MHLA (Album List; iTunes 7.1+)
    Type 5  → MHLP (Smart Playlist List; iTunes 7.3+)
    Type 6  → MHLT (Empty stub — 0 children)
    Type 8  → MHLI (Artist List — mhii children with MHOD type 300)
    Type 9  → Genius data (raw string, CUID)
    Type 10 → MHLT (Empty stub — 0 children)

IMPORTANT: For the iPod to list podcasts, the type 3 DataSet MUST appear
between the type 1 and type 2 DataSets in the database.

Field layout:
    +0x00 (0):  'mhsd' magic (4B)
    +0x04 (4):  header_length (4B)
    +0x08 (8):  total_length (4B) — header + all children
    +0x0C (12): type (4B) — 1–5, see above
    Rest of header is zero-padded.

Cross-referenced against:
  - iPodLinux wiki
  - libgpod itdb_itunesdb.c
"""

import struct


def parse_dataset(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    datasetType = struct.unpack("<I", data[offset + 12:offset + 16])[0]
    # In order for the iPod to list podcasts
    # the type 3 Data Set MUST come between the type 1 and type 2 Data Sets.
    #
    # Dataset types:
    #   1 = Track List (mhlt)
    #   2 = Playlist List (mhlp) — regular playlists
    #   3 = Podcast List (mhlp) — podcast playlists
    #   4 = Album List (mhla)
    #   5 = Smart Playlist List (mhlp) — smart playlists

    # Parse Child
    next_offset = offset + header_length
    childResult = parse_chunk(data, next_offset)
    # Extract the actual result from the wrapper
    result = childResult.get("result", childResult)
    return {"datasetType": datasetType, "result": result, "nextOffset": offset + chunk_length}
