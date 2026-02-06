"""
MHOD Type 52/53 Writer - Library Playlist Index for iTunesDB.

These MHODs are written ONLY for the Master Playlist and provide
pre-sorted track indices that the iPod uses to build its browsing
views (Songs, Artists, Albums, Genres, Composers).

Without these indices, the iPod Classic shows "no songs, no albums"
even if tracks exist in the database.

Based on libgpod's mk_mhod52(), mk_mhod53(), and write_playlist()
in itdb_itunesdb.c.

Type 52 (MHOD_ID_LIBPLAYLISTINDEX):
  Pre-sorted track position arrays for each sort category.
  Format: header(24) + sort_type(4) + count(4) + padding(40) + indices(count*4)
  Total = 4*count + 72

Type 53 (MHOD_ID_LIBPLAYLISTJUMPTABLE):
  Letter-jump table for quick scrolling in each category.
  Format: header(24) + sort_type(4) + count(4) + padding(8) + entries(count*12)
  Total = 12*count + 40
"""

import struct
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mhit_writer import TrackInfo


# Sort type constants (from libgpod enum MHOD52_SORTTYPE)
SORT_TITLE = 0x03
SORT_ALBUM = 0x04
SORT_ARTIST = 0x05
SORT_GENRE = 0x07
SORT_COMPOSER = 0x12

ALL_SORT_TYPES = [SORT_TITLE, SORT_ALBUM, SORT_ARTIST, SORT_GENRE, SORT_COMPOSER]


def _sort_key(s: str) -> str:
    """
    Create a case-insensitive sort key for a string.

    Strips leading "The " for sorting (matching iTunes behavior),
    normalizes unicode, and lowercases.
    """
    if not s:
        return ""
    # Strip leading "The " for English sorting (iTunes convention)
    lower = s.lower()
    if lower.startswith("the "):
        s = s[4:]
    # Normalize unicode for consistent comparison
    return unicodedata.normalize('NFKD', s).casefold()


def _jump_table_letter(s: str) -> int:
    """
    Get the first alphanumeric character for jump table grouping.

    Returns uppercase letter (A-Z) as Unicode codepoint, or ord('0')
    for strings starting with digits.

    Based on libgpod's jump_table_letter().
    """
    if not s:
        return ord('0')

    for ch in s:
        if ch.isalnum():
            if ch.isdigit():
                return ord('0')
            return ord(ch.upper())

    return ord('0')


def _get_sort_fields(track: "TrackInfo", sort_type: int) -> tuple:
    """
    Get sort key fields for a track based on sort type.

    Returns a tuple used for sorting. Multi-field sorts match
    libgpod's mhod52_sort_* comparison functions.
    """
    title = _sort_key(track.title or "")
    album = _sort_key(track.album or "")
    artist = _sort_key(track.sort_artist or track.artist or "")
    genre = _sort_key(track.genre or "")
    composer = _sort_key(getattr(track, 'composer', None) or "")
    track_nr = getattr(track, 'track_number', 0) or 0
    cd_nr = getattr(track, 'disc_number', 0) or 0

    if sort_type == SORT_TITLE:
        return (title,)
    elif sort_type == SORT_ALBUM:
        return (album, cd_nr, track_nr, title)
    elif sort_type == SORT_ARTIST:
        return (artist, album, cd_nr, track_nr, title)
    elif sort_type == SORT_GENRE:
        return (genre, artist, album, cd_nr, track_nr, title)
    elif sort_type == SORT_COMPOSER:
        return (composer, album, cd_nr, track_nr, title)
    else:
        return (title,)


def _get_jump_letter(track: "TrackInfo", sort_type: int) -> int:
    """Get the letter for jump table grouping based on sort type."""
    if sort_type == SORT_TITLE:
        return _jump_table_letter(track.title or "")
    elif sort_type == SORT_ALBUM:
        return _jump_table_letter(track.album or "")
    elif sort_type == SORT_ARTIST:
        s = track.sort_artist or track.artist or ""
        return _jump_table_letter(s)
    elif sort_type == SORT_GENRE:
        return _jump_table_letter(track.genre or "")
    elif sort_type == SORT_COMPOSER:
        return _jump_table_letter(getattr(track, 'composer', None) or "")
    else:
        return _jump_table_letter(track.title or "")


def write_mhod_type52(tracks: list["TrackInfo"], sort_type: int) -> tuple[bytes, list[tuple[int, int, int]]]:
    """
    Write a Type 52 MHOD (library playlist index) for one sort category.

    Args:
        tracks: List of all TrackInfo objects (in original order)
        sort_type: Sort category (SORT_TITLE, SORT_ALBUM, etc.)

    Returns:
        Tuple of (MHOD bytes, jump_table_entries) where jump_table_entries
        is a list of (letter, start, count) tuples for the corresponding
        Type 53 MHOD.
    """
    num_tracks = len(tracks)

    # Create indexed list: (sort_key, original_index, track)
    indexed = []
    for i, track in enumerate(tracks):
        sort_key = _get_sort_fields(track, sort_type)
        indexed.append((sort_key, i, track))

    # Sort by the sort key
    indexed.sort(key=lambda x: x[0])

    # Build sorted track indices (original position in track list)
    sorted_indices = [idx for _, idx, _ in indexed]

    # Build jump table entries: group by first letter
    jump_entries: list[tuple[int, int, int]] = []
    last_letter = -1
    current_entry = None

    for pos, (_, _, track) in enumerate(indexed):
        letter = _get_jump_letter(track, sort_type)
        if letter != last_letter:
            current_entry = (letter, pos, 0)
            jump_entries.append(current_entry)
            last_letter = letter
        # Increment count for current entry
        letter_val, start, count = jump_entries[-1]
        jump_entries[-1] = (letter_val, start, count + 1)

    # Build MHOD type 52 binary data
    # Header: 24 bytes
    # Body: sort_type(4) + count(4) + padding(40) + indices(count*4)
    total_len = 4 * num_tracks + 72  # matches libgpod formula

    header = bytearray(24)
    header[0:4] = b'mhod'
    struct.pack_into('<I', header, 4, 24)         # header length
    struct.pack_into('<I', header, 8, total_len)  # total length
    struct.pack_into('<I', header, 12, 52)        # type
    struct.pack_into('<I', header, 16, 0)         # unk1
    struct.pack_into('<I', header, 20, 0)         # unk2

    # Body header
    body_header = bytearray(48)  # 4 + 4 + 40 padding
    struct.pack_into('<I', body_header, 0, sort_type)    # sort type
    struct.pack_into('<I', body_header, 4, num_tracks)   # number of entries
    # Remaining 40 bytes are zero padding

    # Track indices
    indices_data = bytearray(4 * num_tracks)
    for i, idx in enumerate(sorted_indices):
        struct.pack_into('<I', indices_data, i * 4, idx)

    return bytes(header) + bytes(body_header) + bytes(indices_data), jump_entries


def write_mhod_type53(sort_type: int, jump_entries: list[tuple[int, int, int]]) -> bytes:
    """
    Write a Type 53 MHOD (library playlist jump table) for one sort category.

    Args:
        sort_type: Sort category (must match corresponding type 52)
        jump_entries: List of (letter, start, count) tuples from write_mhod_type52()

    Returns:
        Complete MHOD type 53 bytes
    """
    num_entries = len(jump_entries)

    # Header: 24 bytes
    # Body: sort_type(4) + count(4) + padding(8) + entries(count*12)
    total_len = 12 * num_entries + 40  # matches libgpod formula

    header = bytearray(24)
    header[0:4] = b'mhod'
    struct.pack_into('<I', header, 4, 24)         # header length
    struct.pack_into('<I', header, 8, total_len)  # total length
    struct.pack_into('<I', header, 12, 53)        # type
    struct.pack_into('<I', header, 16, 0)         # unk1
    struct.pack_into('<I', header, 20, 0)         # unk2

    # Body header
    body_header = bytearray(16)  # 4 + 4 + 8 padding
    struct.pack_into('<I', body_header, 0, sort_type)     # sort type
    struct.pack_into('<I', body_header, 4, num_entries)    # number of entries
    # 8 bytes zero padding

    # Jump table entries: each is letter(u16) + pad(u16) + start(u32) + count(u32)
    entries_data = bytearray(12 * num_entries)
    for i, (letter, start, count) in enumerate(jump_entries):
        offset = i * 12
        struct.pack_into('<H', entries_data, offset, letter)       # letter (UTF-16)
        struct.pack_into('<H', entries_data, offset + 2, 0)        # padding
        struct.pack_into('<I', entries_data, offset + 4, start)    # start index
        struct.pack_into('<I', entries_data, offset + 8, count)    # count

    return bytes(header) + bytes(body_header) + bytes(entries_data)


def write_library_indices(tracks: list["TrackInfo"]) -> tuple[bytes, int]:
    """
    Write all library index MHODs (type 52 + type 53 pairs) for the
    master playlist.

    Generates 5 sort categories × 2 MHODs = 10 MHODs total:
    - Title (0x03)
    - Album (0x04)
    - Artist (0x05)
    - Genre (0x07)
    - Composer (0x12)

    Args:
        tracks: List of all TrackInfo objects

    Returns:
        Tuple of (concatenated MHOD bytes, count of MHODs written)
    """
    if not tracks:
        return b'', 0

    result = bytearray()
    mhod_count = 0

    for sort_type in ALL_SORT_TYPES:
        # Write type 52 (sorted index)
        mhod52_data, jump_entries = write_mhod_type52(tracks, sort_type)
        result.extend(mhod52_data)
        mhod_count += 1

        # Write type 53 (jump table)
        mhod53_data = write_mhod_type53(sort_type, jump_entries)
        result.extend(mhod53_data)
        mhod_count += 1

    return bytes(result), mhod_count
