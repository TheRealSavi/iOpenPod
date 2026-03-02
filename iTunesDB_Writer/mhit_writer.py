"""
MHIT Writer — Write track item chunks for iTunesDB.

MHIT chunks contain all metadata for a single track, plus child MHOD
chunks for strings (title, artist, path, etc.).

Header layout (MHIT_HEADER_SIZE = 0x248 / 584 bytes, matching libgpod):
    +0x00: 'mhit' magic (4B)
    +0x04: header_length (4B)
    +0x08: total_length (4B) — header + all child MHODs
    +0x0C: mhod_count (4B)
    +0x10: trackID (4B) — unique within database
    +0x14: visible (4B) — 1=visible
    +0x18: filetype (4B) — big-endian ASCII stored as LE u32 ("MP3 ", "M4A ")
    +0x1C: type1/VBR (1B), type2 (1B), compilation (1B), rating (1B)
    +0x20: time_modified (4B Mac) — file modification time
    +0x24: size (4B) — file size in bytes
    +0x28: length (4B) — duration in ms
    +0x2C: track_number (4B)
    +0x30: total_tracks (4B)
    +0x34: year (4B)
    +0x38: bitrate (4B)
    +0x3C: sample_rate (4B) — value << 16
    +0x40: volume (4B signed) — -255 to +255
    +0x44: start_time (4B ms)
    +0x48: stop_time (4B ms)
    +0x4C: sound_check (4B)
    +0x50: play_count (4B)
    +0x54: play_count2 (4B) — reset after sync
    +0x58: last_played (4B Mac)
    +0x5C: disc_number (4B)
    +0x60: total_discs (4B)
    +0x64: drm_userid (4B) — always 0
    +0x68: date_added (4B Mac)
    +0x6C: bookmark_time (4B ms)
    +0x70: dbid (8B) — unique 64-bit ID
    +0x78: checked (1B), app_rating (1B), bpm (2B)
    +0x7C: artwork_count (2B), unk126 (2B)
    +0x80: artwork_size (4B)
    +0x84: unk132 (4B)
    +0x88: sample_rate2 (4B float)
    +0x8C: date_released (4B Mac)
    +0x90: unk144 (2B), explicit_flag (2B)
    +0x94: unk148 (4B), unk152 (4B)
    +0x9C: skip_count (4B)
    +0xA0: last_skipped (4B Mac)
    +0xA4: has_artwork (1B), skip_shuffle (1B), remember_pos (1B), podcast_flag (1B)
    +0xA8: dbid2 (8B) — copy of dbid
    +0xB0: lyrics_flag (1B), movie_flag (1B), played_mark (1B), unk179 (1B)
    +0xB4: unk180 (4B)
    +0xB8: pregap (4B)
    +0xBC: sample_count (8B)
    +0xC4: unk196 (4B)
    +0xC8: postgap (4B)
    +0xCC: encoder_flag (4B) — 0x01=MP3
    +0xD0: media_type (4B)
    +0xD4: season_number (4B)
    +0xD8: episode_number (4B)
    +0xF8: gapless_data (4B)
    +0x100: gapless_track_flag (2B)
    +0x102: gapless_album_flag (2B)
    +0x120: album_id (4B)
    +0x124: id_0x24 (8B) — from MHBD
    +0x12C: size (4B) — duplicate
    +0x134: mystery_pattern (8B) — 0x808080808080
    +0x160: mhii_link (4B) — ArtworkDB reference
    +0x168: unk (4B) — always 1
    +0x1E0: artist_id (4B)
    +0x1F4: composer_id (4B)

Cross-referenced against:
  - iTunesDB_Parser/mhit_parser.py parse_trackItem()
  - libgpod itdb_itunesdb.c: mk_mhit()
  - iPodLinux wiki MHIT documentation
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
    sound_check: int = 0  # Volume normalization value (from ReplayGain)
    bookmark_time: int = 0  # Resume position in ms (audiobooks/podcasts)
    checked: int = 0  # 0 = checked/enabled, 1 = unchecked/disabled

    # Gapless playback
    gapless_data: int = 0  # Gapless playback encoder delay data
    gapless_track_flag: int = 0  # 1 = track has gapless info
    gapless_album_flag: int = 0  # 1 = album is gapless
    pregap: int = 0  # Encoder pregap samples
    postgap: int = 0  # Encoder postgap/padding samples (0xC8)
    sample_count: int = 0  # Total decoded sample count (64-bit)
    encoder_flag: int = 0  # 0xCC: 0x01=MP3 encoder, 0x00=other

    # Track flags
    skip_when_shuffling: bool = False  # 1 = skip in shuffle mode
    remember_position: bool = False    # 1 = resume from bookmark (audiobooks)
    podcast_flag: int = 0  # 0xA7: 0x00=normal, 0x01/0x02=podcast
    movie_file_flag: int = 0  # 0xB1: 0x01=video/movie file, 0x00=audio
    explicit_flag: int = 0  # 0=none, 1=explicit, 2=clean
    has_lyrics: bool = False  # True if track has embedded lyrics

    # Timestamps (Unix)
    date_added: int = 0  # Will be set to now if 0
    date_released: int = 0
    last_modified: int = 0  # 0x20: file modification time (0 = use date_added)
    last_played: int = 0
    last_skipped: int = 0

    # iPod-specific
    track_id: int = 0  # Will be assigned during write
    dbid: int = 0  # Will be generated if 0
    media_type: int = MEDIA_TYPE_AUDIO
    season_number: int = 0  # 0xD4: TV show season number
    episode_number: int = 0  # 0xD8: TV show episode number
    artwork_count: int = 0
    artwork_size: int = 0
    mhii_link: int = 0  # Link to ArtworkDB
    album_id: int = 0  # Links to MHIA album entry

    # Sorting
    sort_artist: Optional[str] = None
    sort_name: Optional[str] = None
    sort_album: Optional[str] = None
    sort_album_artist: Optional[str] = None
    sort_composer: Optional[str] = None

    # Extra string metadata
    grouping: Optional[str] = None

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
        sort_album_artist=track.sort_album_artist,
        sort_composer=track.sort_composer,
        grouping=track.grouping,
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
    # type2: 0x01=MP3, 0x00=AAC/ALAC/other. Derives from filetype when not explicitly set.
    ft = track.filetype.lower()
    header[0x1D] = 1 if ft == 'mp3' else 0
    header[0x1E] = 1 if track.compilation else 0  # compilation
    header[0x1F] = min(100, max(0, track.rating))  # rating

    # +0x20: time_modified (Mac timestamp). Use last_modified if set, else date_added as fallback.
    time_mod = track.last_modified if track.last_modified else track.date_added
    struct.pack_into('<I', header, 0x20, unix_to_mac_timestamp(time_mod))  # time_modified
    struct.pack_into('<I', header, 0x24, track.size)  # file size
    struct.pack_into('<I', header, 0x28, track.length)  # length in ms
    struct.pack_into('<I', header, 0x2C, track.track_number)  # track number

    # +0x30
    struct.pack_into('<I', header, 0x30, track.total_tracks)  # total tracks
    struct.pack_into('<I', header, 0x34, track.year)  # year
    struct.pack_into('<I', header, 0x38, track.bitrate)  # bitrate
    struct.pack_into('<I', header, 0x3C, (track.sample_rate << 16) & 0xFFFFFFFF)  # samplerate (stored << 16)

    # +0x40
    struct.pack_into('<i', header, 0x40, track.volume)  # volume (signed)
    struct.pack_into('<I', header, 0x44, track.start_time)  # start time
    struct.pack_into('<I', header, 0x48, track.stop_time)  # stop time
    struct.pack_into('<I', header, 0x4C, track.sound_check)  # sound check

    # +0x50
    struct.pack_into('<I', header, 0x50, track.play_count)  # playcount
    struct.pack_into('<I', header, 0x54, 0)  # playcount2 — reset after sync (iPod increments this)
    struct.pack_into('<I', header, 0x58, unix_to_mac_timestamp(track.last_played))  # last played
    struct.pack_into('<I', header, 0x5C, track.disc_number)  # disc number

    # +0x60
    struct.pack_into('<I', header, 0x60, track.total_discs)  # total discs
    struct.pack_into('<I', header, 0x64, 0)  # drm_userid
    struct.pack_into('<I', header, 0x68, unix_to_mac_timestamp(track.date_added))  # date added (again)
    struct.pack_into('<I', header, 0x6C, track.bookmark_time)  # bookmark time

    # +0x70: DBID (64-bit)
    struct.pack_into('<Q', header, 0x70, track.dbid)

    # +0x78: checked(1), app_rating(1), BPM(2), artwork_count(2), unk126(2)
    header[0x78] = track.checked  # checked (0 = checked/enabled, 1 = unchecked)
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
    struct.pack_into('<H', header, 0x92, track.explicit_flag)  # explicit_flag (0=none, 1=explicit, 2=clean)
    struct.pack_into('<I', header, 0x94, 0)  # unk148
    struct.pack_into('<I', header, 0x98, 0)  # unk152

    # +0x9C: skip_count(4), last_skipped(4), has_artwork(1), skip_shuffle(1), remember_pos(1), flag4(1)
    # NOTE: recent_skip_count is in-memory only (from Play Counts file), NOT written to disk
    struct.pack_into('<I', header, 0x9C, track.skip_count)  # skip count
    struct.pack_into('<I', header, 0xA0, unix_to_mac_timestamp(track.last_skipped))  # last skipped
    header[0xA4] = 1 if track.artwork_count > 0 else 2  # has_artwork (1=has, 2=no)
    header[0xA5] = 1 if track.skip_when_shuffling else 0
    header[0xA6] = 1 if track.remember_position else 0
    header[0xA7] = track.podcast_flag  # 0xA7: podcast display flag (0=normal, 1-2=podcast)

    # +0xA8: dbid2 (64-bit) - backup copy of dbid
    struct.pack_into('<Q', header, 0xA8, track.dbid)

    # +0xB0: lyrics_flag, movie_flag, mark_unplayed, unk179, unk180, etc.
    header[0xB0] = 1 if track.has_lyrics else 0  # lyrics_flag
    header[0xB1] = track.movie_file_flag  # 0xB1: 1=video/movie, 0=audio
    # mark_unplayed: 0x02 = unplayed bullet, 0x01 = no bullet (played)
    header[0xB2] = 0x01 if track.play_count > 0 else 0x02
    header[0xB3] = 0  # unk179

    # +0xB4: unk180(4), pregap(4), samplecount(8), unk196(4), etc.
    struct.pack_into('<I', header, 0xB4, 0)  # unk180
    struct.pack_into('<I', header, 0xB8, track.pregap)  # pregap
    struct.pack_into('<Q', header, 0xBC, track.sample_count)  # samplecount (64-bit)
    struct.pack_into('<I', header, 0xC4, 0)  # unk196

    # +0xC8: postgap (encoder padding samples at end of track)
    struct.pack_into('<I', header, 0xC8, track.postgap)

    # +0xCC: encoder_flag (0x01=MP3 encoder, 0x00=other)
    struct.pack_into('<I', header, 0xCC, track.encoder_flag)

    # +0xD0: media_type (offset 0xD0 = 208)
    struct.pack_into('<I', header, 0xD0, track.media_type)

    # +0xD4: season_number, +0xD8: episode_number (TV shows)
    struct.pack_into('<I', header, 0xD4, track.season_number)
    struct.pack_into('<I', header, 0xD8, track.episode_number)

    # +0xF8: gapless_data (libgpod: seek+248)
    struct.pack_into('<I', header, 0xF8, track.gapless_data)
    struct.pack_into('<H', header, 0x100, track.gapless_track_flag)
    struct.pack_into('<H', header, 0x102, track.gapless_album_flag)

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
