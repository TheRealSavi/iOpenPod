from .exceptions import (
    CorruptHeaderError,
    InsufficientDataError,
    ITunesDBParseError,
    UnknownChunkTypeError,
)
from .parser import decompress_itunescdb, parse_itunesdb
from .playcounts import PlayCountEntry, merge_playcounts, parse_playcounts

__all__ = [
    # Public parsing API
    "parse_itunesdb",
    "decompress_itunescdb",
    "parse_playcounts",
    "merge_playcounts",
    "PlayCountEntry",
    # Exceptions
    "ITunesDBParseError",
    "CorruptHeaderError",
    "UnknownChunkTypeError",
    "InsufficientDataError",
]
