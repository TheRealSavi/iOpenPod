import struct

# Mac HFS+ epoch starts 1904-01-01, Unix epoch 1970-01-01
MAC_EPOCH_OFFSET = 2082844800


def mac_to_unix_timestamp(mac_timestamp: int) -> int:
    """Convert Mac HFS+ timestamp to Unix timestamp."""
    if mac_timestamp == 0:
        return 0
    return mac_timestamp - MAC_EPOCH_OFFSET


def parse_playlist(data, offset, header_length, chunk_length) -> dict:
    """
    Parse an MHYP (Playlist) chunk.

    MHYP defines a single playlist. Every iTunesDB has at least one
    playlist — the Master Playlist (MPL) — which references all tracks.
    User playlists and smart playlists also use MHYP.

    Structure (184-byte header on iPod Classic, 108 bytes in older models):
        +0x00: 'mhyp' magic (4 bytes)
        +0x04: header_length (4 bytes)
        +0x08: total_length (4 bytes) — header + all children
        +0x0C: mhod_count (4 bytes) — number of MHOD children
        +0x10: mhip_count (4 bytes) — number of MHIP (playlist item) children
        +0x14: hidden (4 bytes) — 1 = master playlist (hidden), 0 = visible
        +0x18: timestamp (4 bytes) — Mac timestamp
        +0x1C: playlist_id (8 bytes) — unique 64-bit playlist ID
        +0x24: unk1 (4 bytes)
        +0x28: string_mhod_count (2 bytes)
        +0x2A: podcast_flag (2 bytes) — 1 = podcast playlist
        +0x2C: sort_order (4 bytes) — 0=manual, 1=title, 2=album, etc.

    Extended header (184 bytes, iPod Classic / iTunes 7+):
        +0x30: unk2 (4 bytes)
        +0x34: unk3 (4 bytes)
        +0x38: unk4 (4 bytes)
        +0x3C: id_0x24 (8 bytes) — MHBD database ID reference
        +0x44: playlist_id copy (8 bytes)
        +0x4C: unk5 (12 bytes)
        +0x58: timestamp copy (4 bytes)

    Children:
        - MHOD type 1: playlist title
        - MHOD type 100: playlist display preferences
        - MHOD type 52/53: library playlist indices (master playlist only)
        - MHOD type 50: smart playlist preferences (smart playlists only)
        - MHOD type 51: smart playlist rules (smart playlists only)
        - MHIP: playlist item entries

    Based on libgpod's read_playlist() / mk_mhyp() in itdb_itunesdb.c
    and the iPodLinux wiki MHYP documentation.

    Args:
        data: Raw iTunesDB bytes
        offset: Start of this MHYP chunk
        header_length: Size of MHYP header
        chunk_length: Total size of MHYP including all children

    Returns:
        {"nextOffset": int, "result": dict}
    """
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    playlist = {}

    # ============================================================
    # Core header fields (always present)
    # ============================================================
    mhod_count = struct.unpack("<I", data[offset + 12:offset + 16])[0]
    mhip_count = struct.unpack("<I", data[offset + 16:offset + 20])[0]

    # libgpod treats offset +20 as 4 separate byte fields:
    #   +20: type   (u8) — 1=master (ITDB_PL_TYPE_MPL), 0=normal
    #   +21: flag1  (u8) — usually 0
    #   +22: flag2  (u8) — usually 0
    #   +23: flag3  (u8) — usually 0
    playlist["type"] = data[offset + 20]
    playlist["flag1"] = data[offset + 21]
    playlist["flag2"] = data[offset + 22]
    playlist["flag3"] = data[offset + 23]
    playlist["isMaster"] = playlist["type"] == 1

    timestamp_mac = struct.unpack("<I", data[offset + 24:offset + 28])[0]
    playlist["timestamp"] = mac_to_unix_timestamp(timestamp_mac)

    playlist["playlistID"] = struct.unpack("<Q", data[offset + 28:offset + 36])[0]
    # Unique 64-bit persistent ID for this playlist

    playlist["unk1"] = struct.unpack("<I", data[offset + 36:offset + 40])[0]

    playlist["stringMhodCount"] = struct.unpack("<H", data[offset + 40:offset + 42])[0]
    # Number of string-type MHODs (usually 1 for the title)

    playlist["podcastFlag"] = struct.unpack("<H", data[offset + 42:offset + 44])[0]
    # 1 if this is a podcast playlist

    playlist["sortOrder"] = struct.unpack("<I", data[offset + 44:offset + 48])[0]
    # Sort order: 1=manual, 3=title, 4=album, 5=artist, 6=bitrate...
    # 0=default/unset.  See libgpod's ItdbPlaylistSortOrder enum.

    # ============================================================
    # Extended header fields (184-byte headers, iPod Classic era)
    # ============================================================
    if header_length >= 0x50:
        playlist["dbId_0x24"] = struct.unpack("<Q", data[offset + 0x3C:offset + 0x44])[0]
        playlist["playlistIDCopy"] = struct.unpack("<Q", data[offset + 0x44:offset + 0x4C])[0]

    if header_length >= 0x5C:
        timestamp2_mac = struct.unpack("<I", data[offset + 0x58:offset + 0x5C])[0]
        playlist["timestamp2"] = mac_to_unix_timestamp(timestamp2_mac)

    # mhsd5_type: used for smart playlist list (dataset type 5)
    if header_length >= 0x6C:
        playlist["mhsd5Type"] = struct.unpack("<H", data[offset + 0x50:offset + 0x52])[0]

    # ============================================================
    # Parse child MHODs
    # ============================================================
    next_offset = offset + header_length
    playlist_items = []
    smart_playlist_data = None
    smart_playlist_rules = None
    library_indices = []

    for i in range(mhod_count):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        mhod_result = response["result"]
        mhod_type = mhod_result.get("mhodType")

        if mhod_type == 1:
            # Playlist title
            playlist["Title"] = mhod_result.get("string", "")
        elif mhod_type == 100:
            # Playlist display preferences (binary blob, store raw info)
            prefs_data = mhod_result.get("data", {})
            playlist["playlistPrefs"] = prefs_data
            # Preserve raw body bytes for round-trip fidelity
            if isinstance(prefs_data, dict) and "rawBody" in prefs_data:
                playlist["rawMhod100"] = prefs_data["rawBody"]
        elif mhod_type == 50:
            # Smart playlist preferences
            smart_playlist_data = mhod_result.get("data", {})
        elif mhod_type == 51:
            # Smart playlist rules
            smart_playlist_rules = mhod_result.get("data", {})
        elif mhod_type == 52:
            # Library sorted index
            library_indices.append({
                "type": 52,
                "sortType": mhod_result.get("data", {}).get("sortType"),
                "count": mhod_result.get("data", {}).get("count"),
            })
        elif mhod_type == 53:
            # Library jump table
            library_indices.append({
                "type": 53,
                "sortType": mhod_result.get("data", {}).get("sortType"),
                "count": mhod_result.get("data", {}).get("count"),
            })
        elif mhod_type == 102:
            # Playlist settings (binary blob, post-iTunes 7)
            settings_data = mhod_result.get("data", {})
            playlist["playlistSettings"] = settings_data
            # Preserve raw body bytes for round-trip fidelity
            if isinstance(settings_data, dict) and "rawBody" in settings_data:
                playlist["rawMhod102"] = settings_data["rawBody"]
        else:
            # Other string MHODs
            field_name = mhod_type_map.get(mhod_type, f"unknown_mhod_{mhod_type}")
            playlist[field_name] = mhod_result.get("string", "")

    # ============================================================
    # Parse child MHIPs (playlist track entries)
    # ============================================================
    for i in range(mhip_count):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        playlist_items.append(response["result"])

    playlist["trackCount"] = mhip_count
    playlist["items"] = playlist_items

    # Smart playlist fields
    if smart_playlist_data is not None:
        playlist["isSmartPlaylist"] = True
        playlist["smartPlaylistData"] = smart_playlist_data
    else:
        playlist["isSmartPlaylist"] = False

    if smart_playlist_rules is not None:
        playlist["smartPlaylistRules"] = smart_playlist_rules

    # Library indices (master playlist only, not needed for JSON but useful)
    if library_indices:
        playlist["libraryIndices"] = library_indices

    return {"nextOffset": offset + chunk_length, "result": playlist}
