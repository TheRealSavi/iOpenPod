"""
MHIT (Track Item) parser.

Parses individual track entries from the iTunesDB track list (MHLT).
Each MHIT contains all metadata for a single track: identifiers, codec
info, play statistics, gapless playback data, and references to artwork
and album list entries.

Field layout cross-referenced against:
  - iPodLinux wiki: https://web.archive.org/web/20081006030946/http://ipodlinux.org/wiki/ITunesDB
  - libgpod itdb_itunesdb.c: get_mhit() / mk_mhit()

Header sizes by database version:
  - dbversion <= 0x0b (iTunes 4.7-):  0x9C  (156 bytes)
  - dbversion >= 0x0c (iTunes 4.71+): 0xF4  (244 bytes)
  - dbversion 0x12-0x13 (iTunes 6.0.5-7.0): 0x148 (328 bytes)
  - dbversion >= 0x14 (iTunes 7.1+):  0x184 (388 bytes)
  - dbversion >= 0x1b (iTunes 7.6+):  0x1B4 (436 bytes)
"""

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
    """
    Parse an MHIT (Track Item) chunk.

    Args:
        data: Raw iTunesDB bytes.
        offset: Start of this MHIT chunk (byte 0 = 'mhit' magic).
        header_length: Size of the MHIT header (variable by DB version).
        chunk_length: Total size including header + all child MHODs.

    Returns:
        {"nextOffset": int, "result": dict} where result contains all
        parsed track fields plus string fields from child MHODs.
    """
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    track = {}

    # ============================================================
    # Core identifiers
    # ============================================================
    childCount = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    track["trackID"] = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    # 0x10: Unique ID for this track; referenced by MHIP playlist items.

    track["visible"] = struct.unpack("<I", data[offset + 20:offset + 24])[0]
    # 0x14: 1 = visible on iPod, any other value = hidden.

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
    # Bytes 0x1C-0x1F: type1 (VBR), type2, compilation, rating
    track["vbr"] = data[offset + 28]  # 0x1C: type1 — 0x01=VBR MP3, 0x00=CBR MP3 or AAC
    track["type2"] = data[offset + 29]  # 0x1D: type2 — 0x01=MP3 (CBR/VBR), 0x00=AAC
    track["compilation"] = data[offset + 30]  # 0x1E: 1 = part of compilation
    track["rating"] = data[offset + 31]  # 0x1F: Single byte: stars × 20 (0-100)

    last_modified_mac = struct.unpack("<I", data[offset + 32:offset + 36])[0]
    track["lastModified"] = mac_to_unix_timestamp(last_modified_mac)
    # 0x20: Mac timestamp of last file modification.

    track["size"] = struct.unpack("<I", data[offset + 36:offset + 40])[0]
    # 0x24: File size in bytes

    track["length"] = struct.unpack("<I", data[offset + 40:offset + 44])[0]
    # Duration in milliseconds

    track["trackNumber"] = struct.unpack("<I", data[offset + 44:offset + 48])[0]
    track["totalTracks"] = struct.unpack("<I", data[offset + 48:offset + 52])[0]

    track["year"] = struct.unpack("<I", data[offset + 52:offset + 56])[0]

    track["bitrate"] = struct.unpack("<I", data[offset + 56:offset + 60])[0]
    # 0x38: e.g., 128, 256, 320

    # 0x3C: Sample rate is stored as value × 0x10000 (e.g. 44100 * 0x10000)
    sample_rate_raw = struct.unpack("<I", data[offset + 60:offset + 64])[0]
    track["sampleRate"] = sample_rate_raw >> 16  # Divide by 0x10000

    track["volume"] = struct.unpack("<i", data[offset + 64:offset + 68])[0]
    # Signed: -255 to +255 volume adjustment

    track["startTime"] = struct.unpack("<I", data[offset + 68:offset + 72])[0]
    # Start time in ms (for gapless playback)

    track["stopTime"] = struct.unpack("<I", data[offset + 72:offset + 76])[0]
    # Stop time in ms (for gapless playback)

    track["soundCheck"] = struct.unpack("<I", data[offset + 76:offset + 80])[0]
    # 0x4C: SoundCheck volume normalization value.
    # Equation: X = 1000 * 10^(-0.1 * Y) where Y = adjustment in dB.
    # Value 0 means "no SoundCheck" (treated same as 1000).
    # Works with ReplayGain-derived data as well as iTunes SoundCheck.

    # ============================================================
    # Play statistics
    # ============================================================
    track["playCount"] = struct.unpack("<I", data[offset + 80:offset + 84])[0]
    # 0x50: Note: iPod doesn't update this directly — see Play Counts file.

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
    # 0x7C: Number of artwork pieces.  Must be >= 1 for iPod to display
    #       any artwork from .ithmb files, even if no embedded art.

    track["unk126"] = struct.unpack("<H", data[offset + 126:offset + 128])[0]
    # 0x7E: 0xFFFF for MP3/AAC, 0x0000 for WAV/uncompressed, 0x0001 for Audible.

    track["artworkSize"] = struct.unpack("<I", data[offset + 128:offset + 132])[0]
    # 0x80: Total artwork size in bytes (artwork embedded in file tags).

    # 0x84: unk132 — unknown (4 bytes, skipped)

    track["sampleRate2"] = struct.unpack("<f", data[offset + 136:offset + 140])[0]
    # 0x88: Sample rate as IEEE 754 32-bit float (redundant with sampleRate).

    date_released_mac = struct.unpack("<I", data[offset + 140:offset + 144])[0]
    track["dateReleased"] = mac_to_unix_timestamp(date_released_mac)
    # 0x8C: Release date / date added to Music Store; podcast release date.

    track["unk144"] = struct.unpack("<H", data[offset + 144:offset + 146])[0]
    # 0x90: MPEG type indicator:
    #   0x000C = MPEG-1 Layer-3,  0x0016 = MPEG-2 Layer-3 (low bitrate),
    #   0x0020 = MPEG-2.5 Layer-3, 0x0033 = AAC,
    #   0x0029 = Audible,  0x0000 = WAV.

    track["explicitFlag"] = struct.unpack("<H", data[offset + 146:offset + 148])[0]
    # 0x92: Content advisory: 0=none, 1=explicit, 2=clean.

    # 0x94: unk148 — DRM-related (always 0x01010100 for iTunes Store, else 0).
    # 0x98: unk152 — unknown (4 bytes, skipped).

    # ============================================================
    # Skip statistics (added in dbversion 0x0c)
    # ============================================================
    track["skipCount"] = struct.unpack("<I", data[offset + 156:offset + 160])[0]
    # 0x9C: Number of times skipped.

    last_skipped_mac = struct.unpack("<I", data[offset + 160:offset + 164])[0]
    track["lastSkipped"] = mac_to_unix_timestamp(last_skipped_mac)
    # 0xA0: Mac timestamp of last skip.

    # ============================================================
    # Additional metadata (added in dbversion 0x0d)
    # ============================================================
    track["hasArtwork"] = data[offset + 164]
    # 0xA4: 0x01 = has associated artwork, 0x02 = no artwork (even if
    #       artwork exists, iPod will not display it). Must be 0x01
    #       for artwork from .ithmb files to be shown.

    track["skipWhenShuffling"] = data[offset + 165]
    # 0xA5: 0x01 = skip in shuffle mode.  Note: .m4b and .aa files are
    #       always excluded from shuffle regardless of this flag.

    track["rememberPosition"] = data[offset + 166]
    # 0xA6: 0x01 = remember playback position (bookmark).  Like shuffle,
    #       .m4b and .aa are always bookmarkable regardless of this flag.

    track["podcastFlag"] = data[offset + 167]
    # 0xA7: Podcast display flag.  0x01 or 0x02 = podcast (hides artist on
    #       "Now Playing", adds info sub-page).  0x00 = normal track.
    #       Must match actual podcast/music status or iTunes may remove it.

    track["dbid2"] = struct.unpack("<Q", data[offset + 168:offset + 176])[0]
    # 0xA8: Until dbversion 0x12 this equals dbid; from 0x12+ it differs.

    track["lyricsFlag"] = data[offset + 176]
    # 0xB0: 0x01 = lyrics stored in MP3 USLT tags.

    track["movieFileFlag"] = data[offset + 177]
    # 0xB1: 0x01 = video/movie file, 0x00 = audio file.

    track["playedMark"] = data[offset + 178]
    # 0xB2: For podcasts: 0x02 = bullet "not played" on iPod,
    #       0x01 = no bullet.  For non-podcasts: always 0x01.

    # ============================================================
    # Gapless playback data (added in dbversion 0x0c, values in 0x0d+)
    # ============================================================
    # 0xB4: unk180 — unknown (4 bytes, skipped).

    track["pregap"] = struct.unpack("<I", data[offset + 184:offset + 188])[0]
    # 0xB8: Number of samples of silence before the song starts.

    track["sampleCount"] = struct.unpack("<Q", data[offset + 188:offset + 196])[0]
    # 0xBC: Total number of samples in the song (8 bytes, u64).

    # 0xC4: unk196 — unknown (4 bytes, skipped).

    track["postgap"] = struct.unpack("<I", data[offset + 200:offset + 204])[0]
    # 0xC8: Number of samples of silence at the end of the song.

    track["encoderFlag"] = struct.unpack("<I", data[offset + 204:offset + 208])[0]
    # 0xCC: 0x01 = MP3 encoder, 0x00 = other.  Per iPodLinux wiki.

    # ============================================================
    # Media classification (added in dbversion 0x0c)
    # ============================================================
    track["mediaType"] = struct.unpack("<I", data[offset + 208:offset + 212])[0]
    # 0xD0: Media type bitmask:
    #   0x00000000 = Audio/Video (shows in both menus)
    #   0x00000001 = Audio
    #   0x00000002 = Video (Movie)
    #   0x00000004 = Podcast
    #   0x00000006 = Video Podcast
    #   0x00000008 = Audiobook
    #   0x00000020 = Music Video
    #   0x00000040 = TV Show
    #   0x00000060 = TV Show (alt)
    #   0x00000100 = Ringtone
    #   0x00000200 = Rental (iTunes rental movie)
    #   0x00040000 = iTunes Pass
    #   0x00060000 = Memo/Voice Memo

    track["seasonNumber"] = struct.unpack("<I", data[offset + 212:offset + 216])[0]
    track["episodeNumber"] = struct.unpack("<I", data[offset + 216:offset + 220])[0]

    track["gaplessData"] = struct.unpack("<I", data[offset + 248:offset + 252])[0]
    # 0xF8: Bytes from first Sync Frame (usually XING/LAME frame) to 8th
    #       before last frame.  MP3 gapless playback fails if this is 0.
    #       May be 0 for AAC tracks.  (Added in dbversion 0x13.)

    # 0xFC: unk252 — unknown (4 bytes, skipped).

    track["gaplessTrackFlag"] = struct.unpack("<H", data[offset + 256:offset + 258])[0]
    # 0x100: 1 = this track has gapless playback data (dbversion 0x13+).

    track["gaplessAlbumFlag"] = struct.unpack("<H", data[offset + 258:offset + 260])[0]
    # 0x102: 1 = this track does not use crossfading in iTunes (dbversion 0x13+).

    # 0x104: unk260 — 20 bytes, appears to be a hash, not checked by iPod.
    # 0x118: unk280 — 4 bytes (seen set to 0xBF).
    # 0x11C: unk284 — 4 bytes.

    track["albumID"] = struct.unpack("<I", data[offset + 288:offset + 292])[0]
    # 0x120: Album ID linking to MHIA in the album list.
    # libgpod treats this as u32 at offset 0x120.  The older iPodLinux wiki
    # documented this as a u16 at offset 298 (0x12A), but that predates the
    # Album List feature (iTunes 7.1).  libgpod is authoritative here.

    track["mhiiLink"] = struct.unpack("<I", data[offset + 352:offset + 356])[0]
    # 0x160: Artwork lookup ID.  Setting this != 0 triggers the right-pane
    #        artwork slideshow on late-2007 iPods (Nano 3G).  References
    #        the 'id' field of the corresponding ArtworkDB MHII (offset 16).
    #        When set, dbid-based artwork lookup is bypassed.

    # ============================================================
    # Parse child MHODs (strings: title, artist, album, etc.)
    # ============================================================
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        trackData = response["result"]
        mhod_type = trackData["mhodType"]
        field_name = mhod_type_map.get(mhod_type, f"unknown_mhod_{mhod_type}")
        track[field_name] = trackData["string"]

    return {"nextOffset": offset + chunk_length, "result": track}
