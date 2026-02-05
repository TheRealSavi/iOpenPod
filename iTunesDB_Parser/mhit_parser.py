import struct

# Mac HFS+ epoch starts 1904-01-01, Unix epoch 1970-01-01
# Difference in seconds: 2082844800
MAC_EPOCH_OFFSET = 2082844800


def mac_to_unix_timestamp(mac_timestamp: int) -> int:
    """Convert Mac HFS+ timestamp to Unix timestamp."""
    if mac_timestamp == 0:
        return 0
    return mac_timestamp - MAC_EPOCH_OFFSET


def parse_trackItem(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    track = {}

    # ============================================================
    # Core identifiers
    # ============================================================
    childCount = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    track["trackID"] = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    # Used for playlist references

    track["visible"] = struct.unpack("<I", data[offset + 20:offset + 24])[0]
    # 1 = visible, other = hidden

    # Filetype as 4-byte ASCII string stored as little-endian int (e.g., "MP3 ", "M4A ", "M4P ")
    # The bytes are stored reversed, so we read as little-endian int then convert to big-endian bytes
    filetype_int = struct.unpack("<I", data[offset + 24:offset + 28])[0]
    filetype_bytes = filetype_int.to_bytes(4, 'big')
    filetype_raw = filetype_bytes.decode('ascii', errors='ignore').strip()

    # Map raw codes to user-friendly names
    FILETYPE_NAMES = {
        "MP3": "MP3",
        "M4A": "Apple Lossless / AAC",
        "M4P": "Protected AAC",
        "M4B": "Audiobook",
        "WAV": "WAV",
        "AIFF": "AIFF",
        "AAC": "AAC",
    }
    track["filetype"] = FILETYPE_NAMES.get(filetype_raw, filetype_raw)

    # ============================================================
    # Track metadata (integers)
    # ============================================================
    track["rating"] = data[offset + 31]  # Single byte: stars × 20 (0-100)

    # VBR flag is at offset 30 (1 byte)
    track["vbr"] = data[offset + 30]  # 1 = VBR, 0 = CBR

    track["compilation"] = data[offset + 32]  # 1 = part of compilation

    track["size"] = struct.unpack("<I", data[offset + 36:offset + 40])[0]
    # File size in bytes

    track["length"] = struct.unpack("<I", data[offset + 40:offset + 44])[0]
    # Duration in milliseconds

    track["trackNumber"] = struct.unpack("<I", data[offset + 44:offset + 48])[0]
    track["totalTracks"] = struct.unpack("<I", data[offset + 48:offset + 52])[0]

    track["year"] = struct.unpack("<I", data[offset + 52:offset + 56])[0]

    track["bitrate"] = struct.unpack("<I", data[offset + 56:offset + 60])[0]
    # e.g., 128, 256, 320

    # Sample rate is stored as value × 0x10000
    sample_rate_raw = struct.unpack("<I", data[offset + 60:offset + 64])[0]
    track["sampleRate"] = sample_rate_raw >> 16  # Divide by 0x10000

    track["volume"] = struct.unpack("<i", data[offset + 64:offset + 68])[0]
    # Signed: -255 to +255 volume adjustment

    track["startTime"] = struct.unpack("<I", data[offset + 68:offset + 72])[0]
    # Start time in ms (for gapless playback)

    track["stopTime"] = struct.unpack("<I", data[offset + 72:offset + 76])[0]
    # Stop time in ms (for gapless playback)

    track["soundCheck"] = struct.unpack("<I", data[offset + 76:offset + 80])[0]
    # Sound check value for volume normalization

    # ============================================================
    # Play statistics
    # ============================================================
    track["playCount"] = struct.unpack("<I", data[offset + 80:offset + 84])[0]
    # Note: iPod doesn't update this directly - see Play Counts file

    track["playCount2"] = struct.unpack("<I", data[offset + 84:offset + 88])[0]
    # Plays since last sync (redundant copy)

    last_played_mac = struct.unpack("<I", data[offset + 88:offset + 92])[0]
    track["lastPlayed"] = mac_to_unix_timestamp(last_played_mac)
    # Unix timestamp of last play

    track["discNumber"] = struct.unpack("<I", data[offset + 92:offset + 96])[0]
    track["totalDiscs"] = struct.unpack("<I", data[offset + 96:offset + 100])[0]

    track["userID"] = struct.unpack("<I", data[offset + 100:offset + 104])[0]
    # iTunes Store user ID

    date_added_mac = struct.unpack("<I", data[offset + 104:offset + 108])[0]
    track["dateAdded"] = mac_to_unix_timestamp(date_added_mac)
    # Unix timestamp when track was added

    track["bookmarkTime"] = struct.unpack("<I", data[offset + 108:offset + 112])[0]
    # Bookmark position in ms (for audiobooks/podcasts)

    track["dbid"] = struct.unpack("<Q", data[offset + 112:offset + 120])[0]
    # The unique 64-bit identifier

    track["checked"] = data[offset + 120]  # 0 = checked, 1 = unchecked

    track["appRating"] = data[offset + 121]  # Application rating

    track["bpm"] = struct.unpack("<H", data[offset + 122:offset + 124])[0]
    # Beats per minute

    track["artworkCount"] = struct.unpack("<H", data[offset + 124:offset + 126])[0]
    # Number of artwork pieces

    track["artworkSize"] = struct.unpack("<I", data[offset + 128:offset + 132])[0]
    # Total artwork size in bytes

    date_released_mac = struct.unpack("<I", data[offset + 140:offset + 144])[0]
    track["dateReleased"] = mac_to_unix_timestamp(date_released_mac)

    # ============================================================
    # Skip statistics
    # ============================================================
    track["skipCount"] = struct.unpack("<I", data[offset + 156:offset + 160])[0]

    last_skipped_mac = struct.unpack("<I", data[offset + 160:offset + 164])[0]
    track["lastSkipped"] = mac_to_unix_timestamp(last_skipped_mac)

    # ============================================================
    # Additional metadata
    # ============================================================
    track["hasArtwork"] = data[offset + 164]  # 1 = has artwork, 2 = no artwork

    track["skipWhenShuffling"] = data[offset + 165]  # 1 = skip

    track["rememberPosition"] = data[offset + 166]  # 1 = remember playback position

    track["podcast"] = data[offset + 168]  # 1 = podcast

    track["mediaType"] = struct.unpack("<I", data[offset + 208:offset + 212])[0]
    # 0x01 = audio, 0x02 = video, 0x04 = podcast, 0x08 = video podcast
    # 0x20 = music video, 0x40 = TV show, 0x100 = ringtone

    track["seasonNumber"] = struct.unpack("<I", data[offset + 212:offset + 216])[0]
    track["episodeNumber"] = struct.unpack("<I", data[offset + 216:offset + 220])[0]

    track["gaplessData"] = struct.unpack("<I", data[offset + 224:offset + 228])[0]

    track["gaplessTrackFlag"] = struct.unpack("<H", data[offset + 232:offset + 234])[0]

    track["gaplessAlbumFlag"] = struct.unpack("<H", data[offset + 234:offset + 236])[0]

    track["albumID"] = struct.unpack("<H", data[offset + 314:offset + 316])[0]
    # Links to mhia in album list

    track["mhiiLink"] = struct.unpack("<I", data[offset + 352:offset + 356])[0]
    # Link to album art in ArtworkDB

    # ============================================================
    # Parse child MHODs (strings: title, artist, album, etc.)
    # ============================================================
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        trackData = response["result"]
        track[mhod_type_map[trackData["mhodType"]]] = trackData["string"]

    return {"nextOffset": offset + chunk_length, "result": track}
