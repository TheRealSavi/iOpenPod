import struct


def parse_playlistItem(data, offset, header_length, chunk_length) -> dict:
    """
    Parse an MHIP (Playlist Item) chunk.

    MHIP entries link tracks to playlists by referencing the track's ID
    (the trackID field from MHIT). Each MHIP can have one MHOD child
    (type 100) that stores the track's position within the playlist.

    Structure (header 76 bytes typical, up to 0x34 for newer DBs):
        +0x00 (0):  'mhip' magic (4B)
        +0x04 (4):  header_length (4B) — typically 76
        +0x08 (8):  total_length (4B) — header + children
        +0x0C (12): child_count (4B) — number of MHOD children (0 or 1)
        +0x10 (16): podcast_group_flag (4B read here; wiki says 2B)
                    0 = normal track, 0x100 = podcast group header.
                    Wiki documents offset 16 as 2B flag + 18 as 1B unk4
                    + 19 as 1B unk5 (0x0 or 0x08, iTunes 7.2).
                    We read all 4 as u32 which works because the extra
                    bytes are near-zero flags.
        +0x14 (20): group_id (4B) — unique MHIP identifier
                    (libgpod: "podcastgroupid", used for all playlists)
        +0x18 (24): track_id (4B) — references MHIT trackID
        +0x1C (28): timestamp (4B) — Mac timestamp (usually 0)
        +0x20 (32): podcast_group_ref (4B) — for podcast grouping
        +0x24 (36): unk6 (4B) — dbversion 0x13+ (not parsed)
        +0x28 (40): unk7 (4B) — dbversion 0x13+ (not parsed)
        +0x2C (44): unk8 (8B) — dbversion 0x1C+, possibly a persistent
                    playlist item ID (not parsed)

    Children:
        - MHOD type 100: position/order data (optional)

    Based on libgpod's read_mhip() in itdb_itunesdb.c and the
    iPodLinux wiki MHIP documentation.

    Args:
        data: Raw iTunesDB bytes
        offset: Start of this MHIP chunk
        header_length: Size of MHIP header
        chunk_length: Total size of MHIP including children

    Returns:
        {"nextOffset": int, "result": dict}
    """
    from .chunk_parser import parse_chunk

    item = {}

    child_count = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    item["podcastGroupFlag"] = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    # 0 = normal track, 256 = podcast group header

    item["groupID"] = struct.unpack("<I", data[offset + 20:offset + 24])[0]
    # Unique ID for this playlist item entry

    item["trackID"] = struct.unpack("<I", data[offset + 24:offset + 28])[0]
    # References the MHIT track by its trackID

    timestamp_mac = struct.unpack("<I", data[offset + 28:offset + 32])[0]
    if timestamp_mac > 0:
        item["timestamp"] = timestamp_mac - 2082844800  # Mac to Unix
    else:
        item["timestamp"] = 0

    item["podcastGroupRef"] = struct.unpack("<I", data[offset + 32:offset + 36])[0]
    # For podcast grouping: references another MHIP's group_id

    # ============================================================
    # Parse child MHODs (typically one type 100 for position)
    # ============================================================
    next_offset = offset + header_length
    for i in range(child_count):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        mhod_result = response["result"]
        mhod_type = mhod_result.get("mhodType")

        if mhod_type == 100:
            # Playlist position data
            position_data = mhod_result.get("data", {})
            if isinstance(position_data, dict):
                item["position"] = position_data.get("position", 0)
            else:
                item["position"] = 0

    return {"nextOffset": offset + chunk_length, "result": item}
