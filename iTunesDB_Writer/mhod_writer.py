"""
MHOD String Writer — Write string, podcast URL, and chapter data MHOD chunks.

String MHODs (types 1-14, 18-31, 33-44, 200-204, 300) have:
  - Common MHOD header (24 bytes)
  - String sub-header (16 bytes): encoding + string_length + unk0x20 + unk0x24
  - UTF-16LE encoded string data

Podcast URL MHODs (types 15, 16) have:
  - Common MHOD header (24 bytes)
  - UTF-8 encoded string directly (NO sub-header)

Chapter Data MHOD (type 17) has:
  - Common MHOD header (24 bytes)
  - 12-byte preamble (3 × u32 LE)
  - Big-endian atom tree: sean → chap × N → name + hedr

Cross-referenced against:
  - iTunesDB_Shared/mhod_defs.py (field definitions and constants)
  - iTunesDB_Parser/mhod_parser.py _parse_string_mhod(), _parse_chapter_data()
  - libgpod itdb_itunesdb.c: mk_mhod(), itdb_chapterdata_build_chapter_blob_internal()
"""

import struct
from typing import Optional

from iTunesDB_Shared.constants import (
    MHOD_TYPE_ALBUM,
    MHOD_TYPE_ALBUM_ARTIST,
    MHOD_TYPE_ARTIST,
    MHOD_TYPE_CATEGORY,
    MHOD_TYPE_CHAPTER_DATA,
    MHOD_TYPE_COMMENT,
    MHOD_TYPE_COMPOSER,
    MHOD_TYPE_DESCRIPTION,
    MHOD_TYPE_EPISODE_ID,
    MHOD_TYPE_EQ_SETTING,
    MHOD_TYPE_FILETYPE,
    MHOD_TYPE_GENRE,
    MHOD_TYPE_GROUPING,
    MHOD_TYPE_KEYWORDS,
    MHOD_TYPE_LOCATION,
    MHOD_TYPE_LYRICS,
    MHOD_TYPE_NETWORK_NAME,
    MHOD_TYPE_PODCAST_ENCLOSURE_URL,
    MHOD_TYPE_PODCAST_RSS_URL,
    MHOD_TYPE_SHOW_LOCALE,
    MHOD_TYPE_SHOW_NAME,
    MHOD_TYPE_SORT_ALBUM,
    MHOD_TYPE_SORT_ALBUM_ARTIST,
    MHOD_TYPE_SORT_ARTIST,
    MHOD_TYPE_SORT_COMPOSER,
    MHOD_TYPE_SORT_NAME,
    MHOD_TYPE_SORT_SHOW,
    MHOD_TYPE_SUBTITLE,
    MHOD_TYPE_TITLE,
)
from iTunesDB_Shared.mhod_defs import (
    CHAP_ATOM,
    HEDR_ATOM,
    HEDR_SIZE,
    MHOD_HEADER_SIZE,
    MHOD_STRING_SUBHEADER_SIZE,
    NAME_ATOM,
    SEAN_ATOM,
    write_mhod_header,
)


def write_mhod_string(mhod_type: int, value: str,
                      unk_0x20: int = 1, unk_0x24: int = 0) -> bytes:
    """
    Write a string MHOD chunk.

    String MHODs have this structure:
    - mhod header (24 bytes minimum)
    - string data type header (16 bytes)
    - UTF-16LE encoded string

    Args:
        mhod_type: MHOD type (1=title, 2=location, etc.)
        value: String value to encode
        unk_0x20: Sub-header unknown at offset 0x20 (preserved from parser).
        unk_0x24: Sub-header unknown at offset 0x24 (preserved from parser).

    Returns:
        Complete MHOD chunk as bytes
    """
    if not value:
        return b''

    string_data = value.encode('utf-16-le')
    string_len = len(string_data)

    total_len = MHOD_HEADER_SIZE + MHOD_STRING_SUBHEADER_SIZE + string_len

    header = write_mhod_header(mhod_type, total_len)

    # String sub-header: encoding(4) + string_length(4) + unk0x20(4) + unk0x24(4)
    # encoding=1 means UTF-16LE
    type_header = struct.pack('<IIII', 1, string_len, unk_0x20, unk_0x24)

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
    return write_mhod_string(MHOD_TYPE_TITLE, title)


def write_mhod_artist(artist: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_ARTIST, artist)


def write_mhod_album(album: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_ALBUM, album)


def write_mhod_genre(genre: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_GENRE, genre)


def write_mhod_album_artist(album_artist: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_ALBUM_ARTIST, album_artist)


def write_mhod_composer(composer: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_COMPOSER, composer)


def write_mhod_comment(comment: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_COMMENT, comment)


def write_mhod_filetype(filetype: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_FILETYPE, filetype)


def write_mhod_sort_artist(sort_artist: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_SORT_ARTIST, sort_artist)


def write_mhod_sort_name(sort_name: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_SORT_NAME, sort_name)


def write_mhod_sort_album(sort_album: str) -> bytes:
    return write_mhod_string(MHOD_TYPE_SORT_ALBUM, sort_album)


def write_mhod_podcast_url(mhod_type: int, url: str) -> bytes:
    """
    Write a podcast URL MHOD (type 15 or 16).

    Podcast URL MHODs use a DIFFERENT format from standard string MHODs:
    - UTF-8 encoded (NOT UTF-16LE)
    - NO type sub-header (string follows directly after the 24-byte header)
    - Length = total_length − header_length

    Per iPodLinux wiki and parser: types 15 (enclosure URL) and 16 (RSS URL)
    have no mhod::length field and use UTF-8/ASCII encoding.

    Args:
        mhod_type: Must be 15 (enclosure URL) or 16 (RSS URL)
        url: URL string to encode

    Returns:
        Complete MHOD chunk as bytes
    """
    if not url:
        return b''
    if mhod_type not in (MHOD_TYPE_PODCAST_ENCLOSURE_URL, MHOD_TYPE_PODCAST_RSS_URL):
        raise ValueError(f"write_mhod_podcast_url only supports types 15 and 16, got {mhod_type}")

    string_data = url.encode('utf-8')
    total_len = MHOD_HEADER_SIZE + len(string_data)

    header = write_mhod_header(mhod_type, total_len)

    return header + string_data


def write_mhod_chapter_data(
    chapters: list[dict],
    unk024: int = 0,
    unk028: int = 0,
    unk032: int = 0,
) -> bytes:
    """Write a chapter data MHOD (type 17).

    Chapter data uses big-endian atom tree encoding, matching libgpod's
    ``itdb_chapterdata_build_chapter_blob_internal()``.

    Args:
        chapters: List of chapter dicts, each with ``startpos`` (int, ms)
            and ``title`` (str).
        unk024, unk028, unk032: Preamble unknown fields (preserved from
            parser, default 0).

    Returns:
        Complete MHOD type 17 chunk as bytes, or b'' if chapters is empty.
    """
    if not chapters:
        return b''

    # Build the atom tree body (all big-endian).
    atoms = bytearray()

    for ch in chapters:
        title = ch.get("title", "")
        startpos = ch.get("startpos", 0)
        title_utf16 = title.encode("utf-16-be")
        title_units = len(title_utf16) // 2

        # name atom: size(4) + "name"(4) + unk=1(4) + unk=0(4) + unk=0(4) + strlen(2) + string
        name_size = 22 + len(title_utf16)
        name_atom = struct.pack(">I", name_size)
        name_atom += NAME_ATOM
        name_atom += struct.pack(">III", 1, 0, 0)
        name_atom += struct.pack(">H", title_units)
        name_atom += title_utf16

        # chap atom: size(4) + "chap"(4) + startpos(4) + children=1(4) + unk=0(4) + name_atom
        chap_size = 20 + name_size
        chap_atom = struct.pack(">I", chap_size)
        chap_atom += CHAP_ATOM
        chap_atom += struct.pack(">III", startpos, 1, 0)
        chap_atom += name_atom

        atoms.extend(chap_atom)

    # hedr terminator atom (28 bytes)
    hedr_atom = struct.pack(">I", HEDR_SIZE)
    hedr_atom += HEDR_ATOM
    hedr_atom += struct.pack(">IIIII", 1, 0, 0, 0, 1)
    atoms.extend(hedr_atom)

    # sean atom header wraps everything
    num_children = len(chapters) + 1  # chapters + hedr
    sean_size = 20 + len(atoms)
    sean_header = struct.pack(">I", sean_size)
    sean_header += SEAN_ATOM
    sean_header += struct.pack(">III", 1, num_children, 0)

    # Preamble (little-endian, 12 bytes)
    preamble = struct.pack("<III", unk024, unk028, unk032)

    # Complete body = preamble + sean_header + atoms
    body = preamble + sean_header + bytes(atoms)

    # MHOD header + body
    total_length = MHOD_HEADER_SIZE + len(body)
    header = write_mhod_header(MHOD_TYPE_CHAPTER_DATA, total_length)

    return header + body


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
    sort_album_artist: Optional[str] = None,
    sort_composer: Optional[str] = None,
    grouping: Optional[str] = None,
    description: Optional[str] = None,
    podcast_enclosure_url: Optional[str] = None,
    podcast_rss_url: Optional[str] = None,
    subtitle: Optional[str] = None,
    show_name: Optional[str] = None,
    episode_id: Optional[str] = None,
    network_name: Optional[str] = None,
    keywords: Optional[str] = None,
    sort_show: Optional[str] = None,
    category: Optional[str] = None,
    lyrics: Optional[str] = None,
    eq_setting: Optional[str] = None,
    show_locale: Optional[str] = None,
    chapter_data: Optional[dict] = None,
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
        sort_album_artist: Sort album artist name
        sort_composer: Sort composer name
        grouping: Grouping tag
        description: Track description (type 14)
        podcast_enclosure_url: Podcast enclosure URL (type 15, UTF-8, no sub-header)
        podcast_rss_url: Podcast RSS feed URL (type 16, UTF-8, no sub-header)
        subtitle: Subtitle (type 18)
        show_name: TV show name (type 19)
        episode_id: Episode ID string (type 20)
        network_name: TV network name (type 21)
        keywords: Keywords (type 24)
        sort_show: Sort show name (type 31)
        category: Podcast/audiobook category (type 9)
        chapter_data: Chapter data dict with ``chapters`` list (type 17)

    Returns:
        Tuple of (concatenated MHOD bytes, count of MHODs)
    """
    chunks: list[bytes] = []

    # Required MHODs
    chunks.append(write_mhod_title(title))
    chunks.append(write_mhod_location(location))

    # Optional string MHODs
    if artist:
        chunks.append(write_mhod_artist(artist))
    if album:
        chunks.append(write_mhod_album(album))
    if genre:
        chunks.append(write_mhod_genre(genre))
    if album_artist:
        chunks.append(write_mhod_album_artist(album_artist))
    if composer:
        chunks.append(write_mhod_composer(composer))
    if comment:
        chunks.append(write_mhod_comment(comment))
    if filetype_desc:
        chunks.append(write_mhod_filetype(filetype_desc))
    if category:
        chunks.append(write_mhod_string(MHOD_TYPE_CATEGORY, category))
    if description:
        chunks.append(write_mhod_string(MHOD_TYPE_DESCRIPTION, description))
    if subtitle:
        chunks.append(write_mhod_string(MHOD_TYPE_SUBTITLE, subtitle))
    if show_name:
        chunks.append(write_mhod_string(MHOD_TYPE_SHOW_NAME, show_name))
    if episode_id:
        chunks.append(write_mhod_string(MHOD_TYPE_EPISODE_ID, episode_id))
    if network_name:
        chunks.append(write_mhod_string(MHOD_TYPE_NETWORK_NAME, network_name))
    if keywords:
        chunks.append(write_mhod_string(MHOD_TYPE_KEYWORDS, keywords))

    # Sort MHODs
    if sort_artist:
        chunks.append(write_mhod_sort_artist(sort_artist))
    if sort_name:
        chunks.append(write_mhod_sort_name(sort_name))
    if sort_album:
        chunks.append(write_mhod_sort_album(sort_album))
    if sort_album_artist:
        chunks.append(write_mhod_string(MHOD_TYPE_SORT_ALBUM_ARTIST, sort_album_artist))
    if sort_composer:
        chunks.append(write_mhod_string(MHOD_TYPE_SORT_COMPOSER, sort_composer))
    if sort_show:
        chunks.append(write_mhod_string(MHOD_TYPE_SORT_SHOW, sort_show))
    if show_locale:
        chunks.append(write_mhod_string(MHOD_TYPE_SHOW_LOCALE, show_locale))
    if grouping:
        chunks.append(write_mhod_string(MHOD_TYPE_GROUPING, grouping))

    # Podcast URL MHODs (different format: UTF-8, no sub-header)
    if podcast_enclosure_url:
        chunks.append(write_mhod_podcast_url(MHOD_TYPE_PODCAST_ENCLOSURE_URL, podcast_enclosure_url))
    if podcast_rss_url:
        chunks.append(write_mhod_podcast_url(MHOD_TYPE_PODCAST_RSS_URL, podcast_rss_url))

    # EQ and lyrics
    if eq_setting:
        chunks.append(write_mhod_string(MHOD_TYPE_EQ_SETTING, eq_setting))
    if lyrics:
        chunks.append(write_mhod_string(MHOD_TYPE_LYRICS, lyrics))

    # Chapter data (type 17, big-endian atom tree)
    if chapter_data and chapter_data.get("chapters"):
        chunks.append(write_mhod_chapter_data(
            chapters=chapter_data["chapters"],
            unk024=chapter_data.get("unk024", 0),
            unk028=chapter_data.get("unk028", 0),
            unk032=chapter_data.get("unk032", 0),
        ))

    return b''.join(chunks), len(chunks)
