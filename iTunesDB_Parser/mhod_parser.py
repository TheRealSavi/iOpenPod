import struct


# String MHOD types (1-31, 200-300) have a string sub-header at offset 24
# Non-string types (50, 51, 52, 53, 100) have completely different binary layouts
# per libgpod's MhodHeaderSmartPlaylistData, etc.
STRING_MHOD_TYPES = set(range(1, 32)) | set(range(200, 301))


def parse_mhod(data, offset, header_length, chunk_length) -> dict:
    mhod_type = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    # Only attempt string parsing for known string MHOD types
    if mhod_type not in STRING_MHOD_TYPES:
        # Non-string MHOD (smart playlist prefs/rules, playlist index, etc.)
        # Return the type but no string data — these require dedicated parsers
        return {"nextOffset": offset + chunk_length, "result": {"mhodType": mhod_type, "string": ""}}

    string_length = struct.unpack("<I", data[offset + 28:offset + 32])[0]
    # Read encoding flag from the string sub-header (0 or 1 = UTF-16LE, 2 = UTF-8)
    encoding_flag = struct.unpack("<I", data[offset + 24:offset + 28])[0]
    string_data = data[offset + 40:offset + 40 + string_length]

    string_decode = ""
    if encoding_flag == 2:
        string_decode = string_data.decode("utf-8", errors="replace")
    else:
        # encoding_flag 0 or 1 = UTF-16LE (most common on iPod)
        string_decode = string_data.decode("utf-16-le", errors="replace")

    return {"nextOffset": offset + chunk_length, "result": {"mhodType": mhod_type, "string": string_decode}}
