import struct


def parse_playlistItem(data, offset, header_length, chunk_length) -> dict:
    """
    Parse an MHIP (Playlist Item) chunk.

    MHIP entries link tracks to playlists by referencing the track's ID
    (the trackID field from MHIT). Each MHIP can have one MHOD child
    (type 100) that stores the track's position within the playlist.

    Structure (76-byte header):
        +0x00: 'mhip' magic (4 bytes)
        +0x04: header_length (4 bytes) — typically 76
        +0x08: total_length (4 bytes) — header + children
        +0x0C: child_count (4 bytes) — number of MHOD children (0 or 1)
        +0x10: podcast_group_flag (4 bytes) — 256 = podcast group header
        +0x14: group_id (4 bytes) — unique MHIP identifier
               (libgpod calls this "podcastgroupid" but it's used for all)
        +0x18: track_id (4 bytes) — references MHIT trackID
        +0x1C: timestamp (4 bytes) — Mac timestamp (usually 0)
        +0x20: podcast_group_ref (4 bytes) — for podcast grouping

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
