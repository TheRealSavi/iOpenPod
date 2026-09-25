from collections.abc import Mapping
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Literal


class MhodType(IntEnum):
    """Stable identities for known iTunesDB MHOD payload meanings."""

    TITLE = 1
    LOCATION = 2
    ALBUM = 3
    ARTIST = 4
    GENRE = 5
    FILETYPE = 6
    EQ_SETTING = 7
    COMMENT = 8
    CATEGORY = 9
    LYRICS = 10
    UNKNOWN_11 = 11
    COMPOSER = 12
    GROUPING = 13
    DESCRIPTION = 14
    PODCAST_ENCLOSURE_URL = 15
    PODCAST_RSS_URL = 16
    CHAPTER_DATA = 17
    SUBTITLE = 18
    SHOW = 19
    EPISODE = 20
    TV_NETWORK = 21
    ALBUM_ARTIST = 22
    SORT_ARTIST = 23
    TRACK_KEYWORDS = 24
    SHOW_LOCALE = 25
    ITUNES_STORE_ASSET_INFO = 26
    SORT_TITLE = 27
    SORT_ALBUM = 28
    SORT_ALBUM_ARTIST = 29
    SORT_COMPOSER = 30
    SORT_SHOW = 31
    VIDEO_TRACK_DATA = 32
    UNKNOWN_33 = 33
    UNKNOWN_34 = 34
    UNKNOWN_35 = 35
    UNKNOWN_36 = 36
    CONTENT_PROVIDER = 37
    UNKNOWN_38 = 38
    COPYRIGHT = 39
    UNKNOWN_40 = 40
    UNKNOWN_41 = 41
    ENCODING_QUALITY_DESCRIPTOR = 42
    PURCHASE_ACCOUNT = 43
    PURCHASER_NAME = 44
    SMART_PLAYLIST_PREFERENCES = 50
    SMART_PLAYLIST_RULES = 51
    LIBRARY_PLAYLIST_INDEX = 52
    LIBRARY_PLAYLIST_JUMP_TABLE = 53
    PLAYLIST_PROPERTY_PLIST = 55
    COLUMN_SIZE_OR_PLAYLIST_ORDER = 100
    UNKNOWN_101 = 101
    PLAYLIST_SETTINGS_BINARY = 102
    ALBUM_ITEM_ALBUM = 200
    ALBUM_ITEM_ARTIST = 201
    ALBUM_ITEM_SORT_ARTIST = 202
    ALBUM_ITEM_PODCAST_URL = 203
    ALBUM_ITEM_SHOW = 204
    ARTIST_ITEM_ARTIST = 300


class MhodPayloadKind(StrEnum):
    """Binary payload layout selected by an MHOD type."""

    OPAQUE = "opaque"
    STRING = "string"
    URL = "url"
    CHAPTER_DATA = "chapter_data"
    VIDEO_DETAILS = "video_details"
    SMART_PREFS = "smart_prefs"
    SMART_RULES = "smart_rules"
    LIBRARY_INDEX = "library_index"
    LIBRARY_JUMP_TABLE = "library_jump_table"
    PLIST = "plist"
    CONTEXTUAL_100 = "contextual_100"
    PLAYLIST_POSITION = "playlist_position"
    SETTINGS = "settings"


MediaType = Literal[
    "Audio/Video",
    "Audio",
    "Video",
    "Podcast",
    "Video Podcast",
    "Audiobook",
    "Music Video",
    "TV Show",
    "TV Show (alt)",
    "Ringtone",
    "Rental",
    "iTunes Extra",
    "Memo",
    "iTunes U",
    "EPUB Book",
    "PDF Book",
]

MEDIA_TYPE_AUDIO_VIDEO = 0x00000000
MEDIA_TYPE_AUDIO = 0x00000001
MEDIA_TYPE_VIDEO = 0x00000002
MEDIA_TYPE_PODCAST = 0x00000004
MEDIA_TYPE_VIDEO_PODCAST = 0x00000006
MEDIA_TYPE_AUDIOBOOK = 0x00000008
MEDIA_TYPE_MUSIC_VIDEO = 0x00000020
MEDIA_TYPE_TV_SHOW = 0x00000040
MEDIA_TYPE_TV_SHOW_ALT = 0x00000060
MEDIA_TYPE_RINGTONE = 0x00004000
MEDIA_TYPE_RENTAL = 0x00008000
MEDIA_TYPE_ITUNES_EXTRA = 0x00010000
MEDIA_TYPE_MEMO = 0x00100000
MEDIA_TYPE_ITUNES_U = 0x00200000
MEDIA_TYPE_EPUB_BOOK = 0x00400000
MEDIA_TYPE_PDF_BOOK = 0x00800000
MEDIA_TYPE_VIDEO_MASK = MEDIA_TYPE_VIDEO | MEDIA_TYPE_MUSIC_VIDEO | MEDIA_TYPE_TV_SHOW

MEDIA_TYPE: dict[int, MediaType] = {
    MEDIA_TYPE_AUDIO_VIDEO: "Audio/Video",
    MEDIA_TYPE_AUDIO: "Audio",
    MEDIA_TYPE_VIDEO: "Video",
    MEDIA_TYPE_PODCAST: "Podcast",
    MEDIA_TYPE_VIDEO_PODCAST: "Video Podcast",
    MEDIA_TYPE_AUDIOBOOK: "Audiobook",
    MEDIA_TYPE_MUSIC_VIDEO: "Music Video",
    MEDIA_TYPE_TV_SHOW: "TV Show",
    MEDIA_TYPE_TV_SHOW_ALT: "TV Show (alt)",
    MEDIA_TYPE_RINGTONE: "Ringtone",
    MEDIA_TYPE_RENTAL: "Rental",
    MEDIA_TYPE_ITUNES_EXTRA: "iTunes Extra",
    MEDIA_TYPE_MEMO: "Memo",
    MEDIA_TYPE_ITUNES_U: "iTunes U",
    MEDIA_TYPE_EPUB_BOOK: "EPUB Book",
    MEDIA_TYPE_PDF_BOOK: "PDF Book",
}

PLAYLIST_SORT_ORDER: Mapping[int, str] = MappingProxyType(
    {
        0: "Default (Unset)",
        1: "Playlist Order (Manual)",
        2: "Uknown Sort Order (2)",
        3: "Title",
        4: "Album",
        5: "Artist",
        6: "Bitrate",
        7: "Genre",
        8: "Media Kind",
        9: "Date Modified",
        10: "Track Number",
        11: "Size",
        12: "Time",
        13: "Year",
        14: "Sample Rate",
        15: "Comment",
        16: "Date Added",
        17: "Equalizer",
        18: "Composer",
        19: "Unknown Sort Order (19)",
        20: "Play Count",
        21: "Last Played",
        22: "Disc Number",
        23: "My Rating",
        24: "Release Date",
        25: "BPM",
        26: "Grouping",
        27: "Category",
        28: "Description",
        # FROM MHOD 52/53, Likely correct.
        29: "Show",
        30: "Season",
        31: "Episode",
        35: "Album Artist",
        36: "Artist Without Sort Field",
    }
)

# File Format Codes (big-endian ASCII stored as LE u32)
FILE_EXTENSION_INT: dict[str, int] = {
    "mp3": 0x4D503320,  # "MP3 "
    "m4a": 0x4D344120,  # "M4A "
    "m4p": 0x4D345020,  # "M4P "
    "m4b": 0x4D344220,  # "M4B "
    "m4v": 0x4D345620,  # "M4V "
    "mp4": 0x4D503420,  # "MP4 "
    "wav": 0x57415620,  # "WAV "
    "aif": 0x41494646,  # "AIFF"
    "aiff": 0x41494646,  # "AIFF"
    "aac": 0x41414320,  # "AAC "
}

# Audio Format Flag map (MHIT offset 0x7E)
AUDIO_FORMAT_FLAG_MAP: dict[str, int] = {
    "wav": 0x0000,
    "aif": 0x0000,
    "aiff": 0x0000,
    "m4b": 0x0001,
    "DEFAULT": 0xFFFF,
}
