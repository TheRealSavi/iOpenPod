"""
MHIT Writer - Write track item chunks for iTunesDB.

MHIT chunks contain all metadata for a single track, plus child MHOD
chunks for strings (title, artist, path, etc.).

Based on libgpod's mk_mhit() in itdb_itunesdb.c
"""

import struct
import time
import random
from dataclasses import dataclass
from typing import Optional

from .mhod_writer import write_track_mhods


# Mac HFS+ epoch starts 1904-01-01, Unix epoch 1970-01-01
# Difference in seconds: 2082844800
MAC_EPOCH_OFFSET = 2082844800


def unix_to_mac_timestamp(unix_timestamp: int) -> int:
    """Convert Unix timestamp to Mac HFS+ timestamp."""
    if unix_timestamp == 0:
        return 0
    return unix_timestamp + MAC_EPOCH_OFFSET


def generate_dbid() -> int:
    """Generate a random 64-bit database ID for a track."""
    return random.getrandbits(64)


# File type codes (stored as big-endian 4-byte ASCII, read as little-endian int)
FILETYPE_CODES = {
    'mp3': 0x4D503320,   # "MP3 "
    'm4a': 0x4D344120,   # "M4A "
    'm4p': 0x4D345020,   # "M4P "
    'm4b': 0x4D344220,   # "M4B "
    'wav': 0x57415620,   # "WAV "
    'aif': 0x41494646,   # "AIFF"
    'aiff': 0x41494646,  # "AIFF"
    'aac': 0x41414320,   # "AAC "
}


# Media type constants
MEDIA_TYPE_AUDIO = 0x01
MEDIA_TYPE_VIDEO = 0x02
MEDIA_TYPE_PODCAST = 0x04
MEDIA_TYPE_VIDEO_PODCAST = 0x08
MEDIA_TYPE_MUSIC_VIDEO = 0x20
MEDIA_TYPE_TV_SHOW = 0x40
MEDIA_TYPE_RINGTONE = 0x100


@dataclass
class TrackInfo:
    """Track metadata for writing to iTunesDB."""

    # Required
    title: str
    location: str  # iPod path like ":iPod_Control:Music:F00:ABCD.mp3"

    # File info
    size: int = 0  # File size in bytes
    length: int = 0  # Duration in milliseconds
    filetype: str = 'mp3'  # mp3, m4a, m4p, etc.
    bitrate: int = 0  # kbps
    sample_rate: int = 44100  # Hz
    vbr: bool = False

    # Metadata
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    comment: Optional[str] = None
    year: int = 0
    track_number: int = 0
    total_tracks: int = 0
    disc_number: int = 1
    total_discs: int = 1
    bpm: int = 0
    compilation: bool = False

    # Playback
    rating: int = 0  # 0-100 (stars × 20)
    play_count: int = 0
    skip_count: int = 0
    volume: int = 0  # -255 to +255
    start_time: int = 0  # ms
    stop_time: int = 0  # ms

    # Timestamps (Unix)
    date_added: int = 0  # Will be set to now if 0
    date_released: int = 0
    last_played: int = 0
    last_skipped: int = 0

    # iPod-specific
    track_id: int = 0  # Will be assigned during write
    dbid: int = 0  # Will be generated if 0
    media_type: int = MEDIA_TYPE_AUDIO
    artwork_count: int = 0
    artwork_size: int = 0
    mhii_link: int = 0  # Link to ArtworkDB
    album_id: int = 0  # Links to MHIA album entry

    # Sorting
    sort_artist: Optional[str] = None
    sort_name: Optional[str] = None
    sort_album: Optional[str] = None

    # Filetype description
    filetype_desc: Optional[str] = None  # e.g., "MPEG audio file"

    # Internal IDs (assigned during database write, NOT user-provided)
    artist_id: int = 0   # Links to artist entry (assigned by writer)
    composer_id: int = 0  # Links to composer entry (assigned by writer)


# MHIT header size - must match what we write
# libgpod uses 0x248 (584 bytes) for modern databases
MHIT_HEADER_SIZE = 0x248  # 584 bytes


def write_mhit(track: TrackInfo, track_id: int, id_0x24: int = 0) -> bytes:
    """
    Write a complete MHIT chunk with all child MHODs.

    Args:
        track: TrackInfo dataclass with all track metadata
        track_id: Unique track ID within this database
        id_0x24: Database-wide ID from MHBD offset 0x24 (written into every track)

    Returns:
        Complete MHIT chunk bytes (header + MHODs)
    """
    # Generate dbid if not provided
    if track.dbid == 0:
        track.dbid = generate_dbid()

    # Set date_added to now if not provided
    if track.date_added == 0:
        track.date_added = int(time.time())

    # Get filetype code
    filetype_code = FILETYPE_CODES.get(track.filetype.lower(), FILETYPE_CODES['mp3'])

    # Build MHODs first so we know the count
    mhod_data, mhod_count = write_track_mhods(
        title=track.title,
        location=track.location,
        artist=track.artist,
        album=track.album,
        genre=track.genre,
        album_artist=track.album_artist,
        composer=track.composer,
        comment=track.comment,
        filetype_desc=track.filetype_desc,
        sort_artist=track.sort_artist,
        sort_name=track.sort_name,
        sort_album=track.sort_album,
    )

    # Total chunk length = header + all MHODs
    total_length = MHIT_HEADER_SIZE + len(mhod_data)

    # Build the header buffer (388 bytes)
    header = bytearray(MHIT_HEADER_SIZE)

    # Magic and lengths
    # Layout based on libgpod mk_mhit() in itdb_itunesdb.c
    header[0:4] = b'mhit'
    struct.pack_into('<I', header, 0x04, MHIT_HEADER_SIZE)  # header length
    struct.pack_into('<I', header, 0x08, total_length)  # total length
    struct.pack_into('<I', header, 0x0C, mhod_count)  # child count (MHODs)

    # +0x10
    struct.pack_into('<I', header, 0x10, track_id)  # Track ID
    struct.pack_into('<I', header, 0x14, 1)  # Visible (1 = visible)
    struct.pack_into('<I', header, 0x18, filetype_code)  # Filetype marker

    # +0x1C: type1 (VBR flag), type2, compilation, rating (single bytes)
    header[0x1C] = 1 if track.vbr else 0  # type1: VBR flag (0x00=CBR, 0x01=VBR)
    header[0x1D] = 1  # type2: track type, always 1 for audio tracks
    header[0x1E] = 1 if track.compilation else 0  # compilation
    header[0x1F] = min(100, max(0, track.rating))  # rating

    # +0x20: time_modified (libgpod field), then size, length, track_number
    struct.pack_into('<I', header, 0x20, unix_to_mac_timestamp(track.date_added))  # time_modified (use date_added as proxy)
    struct.pack_into('<I', header, 0x24, track.size)  # file size
    struct.pack_into('<I', header, 0x28, track.length)  # length in ms
    struct.pack_into('<I', header, 0x2C, track.track_number)  # track number

    # +0x30
    struct.pack_into('<I', header, 0x30, track.total_tracks)  # total tracks
    struct.pack_into('<I', header, 0x34, track.year)  # year
    struct.pack_into('<I', header, 0x38, track.bitrate)  # bitrate
    struct.pack_into('<I', header, 0x3C, track.sample_rate << 16)  # samplerate (stored << 16)

    # +0x40
    struct.pack_into('<i', header, 0x40, track.volume)  # volume (signed)
    struct.pack_into('<I', header, 0x44, track.start_time)  # start time
    struct.pack_into('<I', header, 0x48, track.stop_time)  # stop time
    struct.pack_into('<I', header, 0x4C, 0)  # sound check

    # +0x50
    struct.pack_into('<I', header, 0x50, track.play_count)  # playcount
    struct.pack_into('<I', header, 0x54, 0)  # playcount2 — reset after sync (iPod increments this)
    struct.pack_into('<I', header, 0x58, unix_to_mac_timestamp(track.last_played))  # last played
    struct.pack_into('<I', header, 0x5C, track.disc_number)  # disc number

    # +0x60
    struct.pack_into('<I', header, 0x60, track.total_discs)  # total discs
    struct.pack_into('<I', header, 0x64, 0)  # drm_userid
    struct.pack_into('<I', header, 0x68, unix_to_mac_timestamp(track.date_added))  # date added (again)
    struct.pack_into('<I', header, 0x6C, 0)  # bookmark time

    # +0x70: DBID (64-bit)
    struct.pack_into('<Q', header, 0x70, track.dbid)

    # +0x78: checked(1), app_rating(1), BPM(2), artwork_count(2), unk126(2)
    header[0x78] = 0  # checked (0 = checked)
    header[0x79] = 0  # app_rating
    struct.pack_into('<H', header, 0x7A, track.bpm)  # BPM
    struct.pack_into('<H', header, 0x7C, track.artwork_count)  # artwork count
    struct.pack_into('<H', header, 0x7E, 0xFFFF)  # unk126 (0xFFFF for MP3/AAC)

    # +0x80
    struct.pack_into('<I', header, 0x80, track.artwork_size)  # artwork size
    struct.pack_into('<I', header, 0x84, 0)  # unk132
    struct.pack_into('<f', header, 0x88, float(track.sample_rate))  # samplerate2 (float)
    struct.pack_into('<I', header, 0x8C, unix_to_mac_timestamp(track.date_released))  # date released

    # +0x90: unk144(2), explicit_flag(2), unk148(4), unk152(4)
    struct.pack_into('<H', header, 0x90, 0)  # unk144
    struct.pack_into('<H', header, 0x92, 0)  # explicit_flag
    struct.pack_into('<I', header, 0x94, 0)  # unk148
    struct.pack_into('<I', header, 0x98, 0)  # unk152

    # +0x9C: skip_count(4), last_skipped(4), has_artwork(1), skip_shuffle(1), remember_pos(1), flag4(1)
    # NOTE: recent_skip_count is in-memory only (from Play Counts file), NOT written to disk
    struct.pack_into('<I', header, 0x9C, track.skip_count)  # skip count
    struct.pack_into('<I', header, 0xA0, unix_to_mac_timestamp(track.last_skipped))  # last skipped
    header[0xA4] = 1 if track.artwork_count > 0 else 2  # has_artwork (1=has, 2=no)
    header[0xA5] = 0  # skip_when_shuffling
    header[0xA6] = 0  # remember_playback_position
    header[0xA7] = 0  # flag4

    # +0xA8: dbid2 (64-bit) - backup copy of dbid
    struct.pack_into('<Q', header, 0xA8, track.dbid)

    # +0xB0: lyrics_flag, movie_flag, mark_unplayed, unk179, unk180, etc.
    header[0xB0] = 0  # lyrics_flag
    header[0xB1] = 0  # movie_flag
    header[0xB2] = 0x02  # mark_unplayed (0x02 = unplayed bullet, 0x01 = played)
    header[0xB3] = 0  # unk179

    # +0xB4: unk180(4), pregap(4), samplecount(8), unk196(4), etc.
    struct.pack_into('<I', header, 0xB4, 0)  # unk180
    struct.pack_into('<I', header, 0xB8, 0)  # pregap
    struct.pack_into('<Q', header, 0xBC, 0)  # samplecount (64-bit)
    struct.pack_into('<I', header, 0xC4, 0)  # unk196

    # +0xD0: media_type (offset 0xD0 = 208)
    struct.pack_into('<I', header, 0xD0, track.media_type)

    # +0xF8: gapless_data (libgpod: seek+248)
    # gapless fields default to 0 which is correct for non-gapless tracks

    # +0x120: album_id (u32) - links track to MHIA album entry
    struct.pack_into('<I', header, 0x120, track.album_id)

    # +0x124: id_0x24 from MHBD header (same value as mhbd+0x24)
    # CRITICAL: Must match the MHBD id_0x24 value - iPod uses this to validate tracks
    struct.pack_into('<Q', header, 0x124, id_0x24)

    # +0x12C: filesize again (libgpod writes track->size a second time here)
    struct.pack_into('<I', header, 0x12C, track.size)

    # +0x134: mystery pattern libgpod writes as 0x808080808080LL
    struct.pack_into('<Q', header, 0x134, 0x808080808080)

    # +0x160: mhii_link for artwork (offset 0x160 = 352)
    struct.pack_into('<I', header, 0x160, track.mhii_link)

    # +0x168: unknown field, libgpod always writes 1
    struct.pack_into('<I', header, 0x168, 1)

    # +0x1E0: artist_id - links track to artist entry
    struct.pack_into('<I', header, 0x1E0, track.artist_id)

    # +0x1F4: composer_id - links track to composer entry
    struct.pack_into('<I', header, 0x1F4, track.composer_id)

    return bytes(header) + mhod_data
