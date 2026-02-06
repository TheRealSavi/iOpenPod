"""
MHOD Writer - Write string/data chunks for iTunesDB.

MHOD chunks store strings (track titles, artist names, paths) and
other metadata in the iTunesDB. Each MHOD has a type that indicates
what kind of data it contains.

Based on libgpod's mk_mhod() in itdb_itunesdb.c
"""

import struct
from typing import Optional


# MHOD type constants (from iTunesDB_Parser/constants.py)
MHOD_TYPE_TITLE = 1
MHOD_TYPE_LOCATION = 2
MHOD_TYPE_ALBUM = 3
MHOD_TYPE_ARTIST = 4
MHOD_TYPE_GENRE = 5
MHOD_TYPE_FILETYPE = 6
MHOD_TYPE_EQ_SETTING = 7
MHOD_TYPE_COMMENT = 8
MHOD_TYPE_COMPOSER = 12
MHOD_TYPE_GROUPING = 13
MHOD_TYPE_DESCRIPTION = 14
MHOD_TYPE_PODCAST_ENCLOSURE_URL = 15
MHOD_TYPE_PODCAST_RSS_URL = 16
MHOD_TYPE_CHAPTER_DATA = 17
MHOD_TYPE_SUBTITLE = 18
MHOD_TYPE_SHOW_NAME = 19
MHOD_TYPE_EPISODE_ID = 20
MHOD_TYPE_NETWORK_NAME = 21
MHOD_TYPE_ALBUM_ARTIST = 22
MHOD_TYPE_SORT_ARTIST = 23
MHOD_TYPE_KEYWORDS = 24
MHOD_TYPE_SORT_NAME = 27
MHOD_TYPE_SORT_ALBUM = 28
MHOD_TYPE_SORT_ALBUM_ARTIST = 29
MHOD_TYPE_SORT_COMPOSER = 30
MHOD_TYPE_SORT_SHOW = 31


def write_mhod_string(mhod_type: int, value: str) -> bytes:
    """
    Write a string MHOD chunk.

    String MHODs have this structure:
    - mhod header (24 bytes minimum)
    - string data type header (16 bytes)
    - UTF-16LE encoded string

    Args:
        mhod_type: MHOD type (1=title, 2=location, etc.)
        value: String value to encode

    Returns:
        Complete MHOD chunk as bytes
    """
    if not value:
        return b''

    # Encode string as UTF-16LE (iPod format)
    # Location paths use colon separators and need special handling
    string_data = value.encode('utf-16-le')
    string_len = len(string_data)

    # MHOD header (24 bytes)
    # Offset 0: 'mhod' magic
    # Offset 4: header length (24)
    # Offset 8: total length (header + type header + string)
    # Offset 12: mhod type
    # Offset 16: unk1 (0)
    # Offset 20: unk2 (0)

    header_len = 24
    type_header_len = 16  # String type header
    total_len = header_len + type_header_len + string_len

    header = struct.pack(
        '<4sIIIII',
        b'mhod',      # magic
        header_len,   # header length
        total_len,    # total length
        mhod_type,    # type
        0,            # unk1
        0,            # unk2
    )

    # String type header (16 bytes)
    # Offset 0: encoding (1 = UTF-16LE, 2 = UTF-8) — per libgpod get_mhod_string()
    # Offset 4: string length in bytes
    # Offset 8: unknown (always 1)
    # Offset 12: unknown (always 0)

    type_header = struct.pack(
        '<IIII',
        1,            # encoding (1 = UTF-16LE)
        string_len,   # string length
        1,            # unknown (always 1)
        0,            # unknown (always 0)
    )

    return header + type_header + string_data


def write_mhod_location(path: str) -> bytes:
    """
    Write a location MHOD (type 2) for file path.

    iPod paths use colons as separators:
    :iPod_Control:Music:F00:ABCD.mp3

    Args:
        path: iPod-relative path with colon separators

    Returns:
        Complete MHOD chunk
    """
    return write_mhod_string(MHOD_TYPE_LOCATION, path)


def write_mhod_title(title: str) -> bytes:
    """Write a title MHOD (type 1)."""
    return write_mhod_string(MHOD_TYPE_TITLE, title)


def write_mhod_artist(artist: str) -> bytes:
    """Write an artist MHOD (type 4)."""
    return write_mhod_string(MHOD_TYPE_ARTIST, artist)


def write_mhod_album(album: str) -> bytes:
    """Write an album MHOD (type 3)."""
    return write_mhod_string(MHOD_TYPE_ALBUM, album)


def write_mhod_genre(genre: str) -> bytes:
    """Write a genre MHOD (type 5)."""
    return write_mhod_string(MHOD_TYPE_GENRE, genre)


def write_mhod_album_artist(album_artist: str) -> bytes:
    """Write an album artist MHOD (type 22)."""
    return write_mhod_string(MHOD_TYPE_ALBUM_ARTIST, album_artist)


def write_mhod_composer(composer: str) -> bytes:
    """Write a composer MHOD (type 12)."""
    return write_mhod_string(MHOD_TYPE_COMPOSER, composer)


def write_mhod_comment(comment: str) -> bytes:
    """Write a comment MHOD (type 8)."""
    return write_mhod_string(MHOD_TYPE_COMMENT, comment)


def write_mhod_filetype(filetype: str) -> bytes:
    """Write a filetype description MHOD (type 6)."""
    return write_mhod_string(MHOD_TYPE_FILETYPE, filetype)


def write_mhod_sort_artist(sort_artist: str) -> bytes:
    """Write a sort artist MHOD (type 23)."""
    return write_mhod_string(MHOD_TYPE_SORT_ARTIST, sort_artist)


def write_mhod_sort_name(sort_name: str) -> bytes:
    """Write a sort name MHOD (type 27)."""
    return write_mhod_string(MHOD_TYPE_SORT_NAME, sort_name)


def write_mhod_sort_album(sort_album: str) -> bytes:
    """Write a sort album MHOD (type 28)."""
    return write_mhod_string(MHOD_TYPE_SORT_ALBUM, sort_album)


def write_track_mhods(
    title: str,
    location: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    genre: Optional[str] = None,
    album_artist: Optional[str] = None,
    composer: Optional[str] = None,
    comment: Optional[str] = None,
    filetype_desc: Optional[str] = None,
    sort_artist: Optional[str] = None,
    sort_name: Optional[str] = None,
    sort_album: Optional[str] = None,
) -> tuple[bytes, int]:
    """
    Write all MHODs for a track.

    Args:
        title: Track title (required)
        location: File path on iPod (required)
        artist: Artist name
        album: Album name
        genre: Genre
        album_artist: Album artist (for compilations)
        composer: Composer
        comment: Comment/notes
        filetype_desc: File type description (e.g., "MPEG audio file")
        sort_artist: Sort artist name
        sort_name: Sort title
        sort_album: Sort album name

    Returns:
        Tuple of (concatenated MHOD bytes, count of MHODs)
    """
    mhods = []

    # Required MHODs
    mhods.append(write_mhod_title(title))
    mhods.append(write_mhod_location(location))

    # Optional MHODs
    if artist:
        mhods.append(write_mhod_artist(artist))
    if album:
        mhods.append(write_mhod_album(album))
    if genre:
        mhods.append(write_mhod_genre(genre))
    if album_artist:
        mhods.append(write_mhod_album_artist(album_artist))
    if composer:
        mhods.append(write_mhod_composer(composer))
    if comment:
        mhods.append(write_mhod_comment(comment))
    if filetype_desc:
        mhods.append(write_mhod_filetype(filetype_desc))
    if sort_artist:
        mhods.append(write_mhod_sort_artist(sort_artist))
    if sort_name:
        mhods.append(write_mhod_sort_name(sort_name))
    if sort_album:
        mhods.append(write_mhod_sort_album(sort_album))

    # Filter out empty MHODs
    mhods = [m for m in mhods if m]

    return b''.join(mhods), len(mhods)
