"""Meaningful bits in the raw MHYP playlist-kind word at ``+0x2A``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

PLAYLIST_KIND_PODCAST = 0x0001
PLAYLIST_KIND_FOLDER = 0x0100


def playlist_kind_flags(value: object) -> int:
    """Return the raw MHYP kind word from a value or parsed playlist row."""

    if isinstance(value, Mapping):
        raw_value = value.get("playlist_kind_flags", value.get("podcast_flag", 0))
        try:
            flags = int(raw_value or 0) & 0xFFFF
        except (TypeError, ValueError, OverflowError):
            flags = 0
        if value.get("is_podcast") is True:
            flags |= PLAYLIST_KIND_PODCAST
        if value.get("is_folder") is True:
            flags |= PLAYLIST_KIND_FOLDER
        return flags
    try:
        return int(cast(Any, value) or 0) & 0xFFFF
    except (TypeError, ValueError, OverflowError):
        return 0


def is_podcast_playlist(value: object) -> bool:
    """Whether the low podcast bit is set in the raw playlist-kind word."""

    return bool(playlist_kind_flags(value) & PLAYLIST_KIND_PODCAST)


def is_playlist_folder(value: object) -> bool:
    """Whether the playlist-folder bit is set in the raw playlist-kind word."""

    return bool(playlist_kind_flags(value) & PLAYLIST_KIND_FOLDER)
