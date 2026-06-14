"""Helpers for persisted PC media folder scan settings."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

MEDIA_TYPE_MUSIC = "music"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_PHOTO = "photo"
MEDIA_TYPE_PLAYLISTS = "playlists"

MEDIA_TYPE_ORDER: tuple[str, ...] = (
    MEDIA_TYPE_MUSIC,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_PHOTO,
    MEDIA_TYPE_PLAYLISTS,
)
DEFAULT_MEDIA_TYPES: tuple[str, ...] = MEDIA_TYPE_ORDER

_MISSING = object()
_MEDIA_ALIASES = {
    "audio": MEDIA_TYPE_MUSIC,
    "track": MEDIA_TYPE_MUSIC,
    "tracks": MEDIA_TYPE_MUSIC,
    "song": MEDIA_TYPE_MUSIC,
    "songs": MEDIA_TYPE_MUSIC,
    "music": MEDIA_TYPE_MUSIC,
    "movie": MEDIA_TYPE_VIDEO,
    "movies": MEDIA_TYPE_VIDEO,
    "video": MEDIA_TYPE_VIDEO,
    "videos": MEDIA_TYPE_VIDEO,
    "image": MEDIA_TYPE_PHOTO,
    "images": MEDIA_TYPE_PHOTO,
    "photo": MEDIA_TYPE_PHOTO,
    "photos": MEDIA_TYPE_PHOTO,
    "picture": MEDIA_TYPE_PHOTO,
    "pictures": MEDIA_TYPE_PHOTO,
    "playlist": MEDIA_TYPE_PLAYLISTS,
    "playlists": MEDIA_TYPE_PLAYLISTS,
    "playlist_file": MEDIA_TYPE_PLAYLISTS,
    "playlist_files": MEDIA_TYPE_PLAYLISTS,
}


@dataclass(frozen=True)
class MediaFolderEntry:
    """Normalized scan settings for one local media directory."""

    directory: str
    recurse: bool = True
    media_types: tuple[str, ...] = DEFAULT_MEDIA_TYPES

    def to_settings_dict(self) -> dict[str, object]:
        return {
            "directory": self.directory,
            "recurse": bool(self.recurse),
            "media_types": list(self.media_types),
        }


def _folder_key(folder: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(folder)))


def _iter_candidates(group: object) -> Iterable[object]:
    if not group:
        return ()
    if isinstance(group, (MediaFolderEntry, str, os.PathLike, Mapping)):
        return (group,)
    try:
        return tuple(group)  # type: ignore[arg-type]
    except TypeError:
        return (group,)


def _coerce_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_media_types(value: object = _MISSING) -> tuple[str, ...]:
    if value is _MISSING or value is None:
        return DEFAULT_MEDIA_TYPES
    if isinstance(value, str):
        raw_values = [value]
    else:
        try:
            raw_values = list(value)  # type: ignore[arg-type]
        except TypeError:
            raw_values = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        media_type = _MEDIA_ALIASES.get(str(raw or "").strip().casefold())
        if media_type is None or media_type in seen:
            continue
        seen.add(media_type)
        normalized.append(media_type)
    return tuple(normalized)


def _coerce_entry(candidate: object) -> MediaFolderEntry | None:
    if isinstance(candidate, MediaFolderEntry):
        directory = candidate.directory
        recurse = candidate.recurse
        media_types = candidate.media_types
    elif isinstance(candidate, Mapping):
        directory = (
            candidate.get("directory")
            or candidate.get("path")
            or candidate.get("folder")
            or candidate.get("root")
            or ""
        )
        recurse = _coerce_bool(candidate.get("recurse", True), default=True)
        media_value = _MISSING
        for key in ("media_types", "media_allowlist", "media"):
            if key in candidate:
                media_value = candidate[key]
                break
        media_types = _normalize_media_types(media_value)
    else:
        directory = candidate
        recurse = True
        media_types = DEFAULT_MEDIA_TYPES

    folder = str(directory or "").strip()
    if not folder:
        return None
    return MediaFolderEntry(
        directory=folder,
        recurse=bool(recurse),
        media_types=_normalize_media_types(media_types),
    )


def normalize_media_folder_entries(*folder_groups: object) -> list[MediaFolderEntry]:
    """Return deduplicated folder entries, accepting old string-list settings."""

    entries: list[MediaFolderEntry] = []
    seen: set[str] = set()
    for group in folder_groups:
        for candidate in _iter_candidates(group):
            entry = _coerce_entry(candidate)
            if entry is None:
                continue
            key = _folder_key(entry.directory)
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    return entries


def media_folder_entries_to_settings(*folder_groups: object) -> list[dict[str, object]]:
    """Return the JSON-serializable settings shape for folder entries."""

    return [
        entry.to_settings_dict()
        for entry in normalize_media_folder_entries(*folder_groups)
    ]


def media_folder_paths(*folder_groups: object) -> list[str]:
    """Return just the directory strings from one or more folder groups."""

    return [
        entry.directory
        for entry in normalize_media_folder_entries(*folder_groups)
    ]
