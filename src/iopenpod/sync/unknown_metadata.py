"""Helpers for generating write-time placeholder metadata."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

_PLACEHOLDER_FIELD_NAMES = ("Album Artist", "Artist", "Album")
_VALID_GROUP_RE = re.compile(r"^\d{1,6}$")
_DISC_FOLDER_RE = re.compile(r"^(?:cd|disc|disk|vol(?:ume)?)\s*[-_ ]*\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class _FolderContext:
    key: tuple[str, tuple[str, ...]]
    album: str | None
    artist: str | None


def _clean_text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _placeholder_match(field_name: str, value: object | None) -> re.Match[str] | None:
    text = _clean_text(value)
    if not text:
        return None
    if field_name.casefold() == "album artist":
        # Album Artist placeholders are intentionally written as
        # "Unknown Artist N". Accept the older "Unknown Album Artist N"
        # spelling as well so both forms remain repairable.
        placeholder_name = r"(?:Album\s+)?Artist"
    else:
        placeholder_name = re.escape(field_name)
    pattern = rf"^Unknown\s+{placeholder_name}(?:\s+(.+))?$"
    return re.match(pattern, text, flags=re.IGNORECASE)


def _is_unknown_placeholder(field_name: str, value: object | None) -> bool:
    return _placeholder_match(field_name, value) is not None


def _placeholder_group(field_name: str, value: object | None) -> str | None:
    match = _placeholder_match(field_name, value)
    if match is None:
        return None
    suffix = _clean_text(match.group(1))
    if _VALID_GROUP_RE.match(suffix):
        return suffix
    return None


def _meaningful_text(field_name: str, value: object | None) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if _is_unknown_placeholder(field_name, text):
        return ""
    return text


def _first_placeholder_group(track: dict[str, Any] | Any) -> str | None:
    for field_name in _PLACEHOLDER_FIELD_NAMES:
        if isinstance(track, dict):
            values = (track.get(field_name), track.get(field_name.lower().replace(" ", "_")))
        else:
            values = (
                getattr(track, field_name.lower().replace(" ", "_"), None),
            )
        for value in values:
            group = _placeholder_group(field_name, value)
            if group is not None:
                return group
    return None


def _relative_path_values(track: dict[str, Any] | Any) -> tuple[object | None, ...]:
    if isinstance(track, dict):
        return (
            track.get("source_relative_path"),
            track.get("Source Relative Path"),
            track.get("relative_path"),
            track.get("Relative Path"),
        )
    return (
        getattr(track, "source_relative_path", None),
        getattr(track, "relative_path", None),
    )


def _absolute_path_values(track: dict[str, Any] | Any) -> tuple[object | None, ...]:
    if isinstance(track, dict):
        return (
            track.get("source_path"),
            track.get("Source Path"),
            track.get("path"),
            track.get("Path"),
            track.get("Location"),
            track.get("location"),
        )
    return (
        getattr(track, "source_path", None),
        getattr(track, "path", None),
        getattr(track, "location", None),
    )


def _path_parts(value: object | None) -> tuple[str, ...]:
    text = _clean_text(value)
    if not text:
        return ()

    if text.startswith(":"):
        return tuple(part for part in text.replace(":", "/").split("/") if part)

    has_forward_separator = "/" in text
    is_windows_abs = len(text) >= 3 and text[1] == ":" and text[2] in ("\\", "/")
    is_unc = text.startswith("\\\\")
    if (
        is_windows_abs
        or is_unc
        or (os.sep == "\\" and "\\" in text and not has_forward_separator)
    ):
        text = text.replace("\\", "/")

    return tuple(part for part in text.split("/") if part)


def _folder_context_from_path(value: object | None) -> _FolderContext | None:
    parts = _path_parts(value)
    if len(parts) < 2:
        return None

    lower_parts = tuple(part.lower() for part in parts)
    if "ipod_control" in lower_parts and "music" in lower_parts:
        # iPod storage folders are random buckets, not album context.
        return None

    folder_parts = parts[:-1]
    if folder_parts and _DISC_FOLDER_RE.match(folder_parts[-1]):
        folder_parts = folder_parts[:-1]
    if not folder_parts:
        return None
    album = _clean_text(folder_parts[-1])
    artist = _clean_text(folder_parts[-2]) if len(folder_parts) > 1 else ""
    return _FolderContext(
        key=("folder", tuple(part.casefold() for part in folder_parts)),
        album=album or None,
        artist=artist or None,
    )


def _folder_context(track: dict[str, Any] | Any) -> _FolderContext | None:
    saw_relative_path = False
    for value in _relative_path_values(track):
        if _clean_text(value):
            saw_relative_path = True
        context = _folder_context_from_path(value)
        if context is not None:
            return context
    if saw_relative_path:
        return None

    for value in _absolute_path_values(track):
        context = _folder_context_from_path(value)
        if context is not None:
            return context
    return None


@dataclass
class UnknownMetadataRegistry:
    """Assign stable placeholder numbers per album group."""

    _group_ids: dict[tuple[Any, ...], int] = field(default_factory=dict)
    _next_id: int = 1

    @staticmethod
    def _group_key_from_mapping(track: dict[str, Any]) -> tuple[Any, ...]:
        album = _meaningful_text("Album", track.get("Album") or track.get("album"))
        album_artist = _meaningful_text(
            "Album Artist",
            track.get("Album Artist") or track.get("album_artist"),
        )
        artist = _meaningful_text("Artist", track.get("Artist") or track.get("artist"))
        if album or album_artist or artist:
            return ("album_text", album.lower(), album_artist.lower(), artist.lower())

        context = _folder_context(track)
        if context is not None:
            return context.key

        placeholder_group = _first_placeholder_group(track)
        if placeholder_group is not None:
            return ("unknown_placeholder", placeholder_group)

        # Existing album IDs are often generated from whatever placeholder text
        # was previously written. When all text is unknown, grouping by that ID
        # can preserve a bad per-track split, so keep truly blank albums together.
        return ("blank_album",)

    @staticmethod
    def _group_key_from_object(track: Any) -> tuple[Any, ...]:
        album = _meaningful_text("Album", getattr(track, "album", None))
        album_artist = _meaningful_text("Album Artist", getattr(track, "album_artist", None))
        artist = _meaningful_text("Artist", getattr(track, "artist", None))
        if album or album_artist or artist:
            return ("album_text", album.lower(), album_artist.lower(), artist.lower())

        context = _folder_context(track)
        if context is not None:
            return context.key

        placeholder_group = _first_placeholder_group(track)
        if placeholder_group is not None:
            return ("unknown_placeholder", placeholder_group)

        return ("blank_album",)

    def group_id_for_mapping(self, track: dict[str, Any]) -> int:
        key = self._group_key_from_mapping(track)
        if key[0] == "unknown_placeholder":
            group_id = int(key[1])
            self._group_ids[key] = group_id
            self._next_id = max(self._next_id, group_id + 1)
            return group_id
        group_id = self._group_ids.get(key)
        if group_id is None:
            group_id = self._next_id
            self._group_ids[key] = group_id
            self._next_id += 1
        return group_id

    def group_id_for_object(self, track: Any) -> int:
        key = self._group_key_from_object(track)
        if key[0] == "unknown_placeholder":
            group_id = int(key[1])
            self._group_ids[key] = group_id
            self._next_id = max(self._next_id, group_id + 1)
            return group_id
        group_id = self._group_ids.get(key)
        if group_id is None:
            group_id = self._next_id
            self._group_ids[key] = group_id
            self._next_id += 1
        return group_id

    def values_for_mapping(self, track: dict[str, Any]) -> tuple[str, str, str]:
        """Return artist, album, and album artist placeholders from the original mapping."""
        group_id = self.group_id_for_mapping(track)
        context = _folder_context(track)
        artist = _meaningful_text("Artist", track.get("Artist") or track.get("artist"))
        album = _meaningful_text("Album", track.get("Album") or track.get("album"))
        album_artist = _meaningful_text(
            "Album Artist",
            track.get("Album Artist") or track.get("album_artist"),
        )

        artist = artist or (context.artist if context is not None else None) or f"Unknown Artist {group_id}"
        album = album or (context.album if context is not None else None) or f"Unknown Album {group_id}"
        album_artist = album_artist or artist
        return artist, album, album_artist

    def values_for_object(self, track: Any) -> tuple[str, str, str]:
        """Return artist, album, and album artist placeholders from the original object."""
        group_id = self.group_id_for_object(track)
        context = _folder_context(track)
        artist = _meaningful_text("Artist", getattr(track, "artist", None))
        album = _meaningful_text("Album", getattr(track, "album", None))
        album_artist = _meaningful_text("Album Artist", getattr(track, "album_artist", None))

        artist = artist or (context.artist if context is not None else None) or f"Unknown Artist {group_id}"
        album = album or (context.album if context is not None else None) or f"Unknown Album {group_id}"
        album_artist = album_artist or artist
        return artist, album, album_artist


def unknown_value(field_name: str, value: object | None, *, identifier: object | None = None) -> str:
    """Return a write-time placeholder when *value* is blank."""
    text = _clean_text(value)
    if text and not _is_unknown_placeholder(field_name, text):
        return text
    if field_name.casefold() == "album artist":
        return "Unknown Artist"
    return f"Unknown {field_name}"


def apply_unknown_placeholders(track_infos: list[Any]) -> None:
    """Mutate TrackInfo objects so blank fields get folder-aware placeholders."""
    registry = UnknownMetadataRegistry()
    for track in track_infos:
        artist, album, album_artist = registry.values_for_object(track)
        track.artist = artist
        track.album = album
        track.album_artist = album_artist


def apply_unknown_placeholders_to_mapping(track: dict[str, Any], registry: UnknownMetadataRegistry) -> None:
    """Mutate a track dict in-place using the provided registry."""
    artist, album, album_artist = registry.values_for_mapping(track)
    track["Artist"] = artist
    track["Album"] = album
    track["Album Artist"] = album_artist
