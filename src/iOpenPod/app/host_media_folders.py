"""Typed global settings for the user-owned Host Media Library roots."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from iOpenPod.app.core.settings.definitions import SettingDefinition
from storage import HostPath

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService


class HostMediaType(StrEnum):
    """Media categories that a Host Media Library root may contribute."""

    AUDIO = "audio"
    VIDEO = "video"
    PHOTOS = "photos"
    PLAYLISTS = "playlists"


ALL_HOST_MEDIA_TYPES: tuple[HostMediaType, ...] = (
    HostMediaType.AUDIO,
    HostMediaType.VIDEO,
    HostMediaType.PHOTOS,
    HostMediaType.PLAYLISTS,
)


@dataclass(frozen=True, slots=True)
class HostMediaFolder:
    """One user-selected Host folder and its future scan boundaries."""

    path: HostPath
    recurse: bool = True
    media_types: frozenset[HostMediaType] = frozenset(ALL_HOST_MEDIA_TYPES)
    follow_symlinks: bool = False


type HostMediaFoldersSetting = list[object]


def _valid_folder_setting(value: HostMediaFoldersSetting) -> bool:
    identities: set[str] = set()
    for candidate in value:
        if not isinstance(candidate, dict):
            return False
        item = cast("dict[object, object]", candidate)
        if set(item) not in (
            {"media_types", "path", "recurse"},
            {"media_types", "path", "recurse", "follow_symlinks"},
        ):
            return False
        path = item.get("path")
        recurse = item.get("recurse")
        media_types = item.get("media_types")
        if (
            not isinstance(path, str)
            or not path.strip()
            or "\x00" in path
            or not Path(path).is_absolute()
            or not isinstance(recurse, bool)
            or not isinstance(item.get("follow_symlinks", False), bool)
            or not isinstance(media_types, list)
        ):
            return False
        raw_media_types = cast("list[object]", media_types)
        if any(
            not isinstance(media_type, str)
            or media_type not in {item.value for item in ALL_HOST_MEDIA_TYPES}
            for media_type in raw_media_types
        ):
            return False
        if len(raw_media_types) != len(set(cast("list[str]", raw_media_types))):
            return False
        identity = _path_identity(Path(path))
        if identity in identities:
            return False
        identities.add(identity)
    return True


HOST_MEDIA_FOLDERS = SettingDefinition[HostMediaFoldersSetting](
    key="sync/media-folders",
    value_type=list,
    default=[],
    validator=_valid_folder_setting,
)


def create_host_media_folder(path: str | os.PathLike[str]) -> HostMediaFolder:
    """Create a normalized folder selection with safe default scan settings."""

    raw = os.fspath(path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("A Host Media Library folder must not be empty")
    normalized = Path(os.path.abspath(os.path.expanduser(raw)))
    return HostMediaFolder(path=HostPath(normalized))


def load_host_media_folders(settings: SettingsService) -> tuple[HostMediaFolder, ...]:
    """Load validated Host Media Library folders from global settings."""

    folders: list[HostMediaFolder] = []
    for candidate in settings.get(HOST_MEDIA_FOLDERS):
        item = cast("dict[str, object]", candidate)
        path = cast("str", item["path"])
        recurse = cast("bool", item["recurse"])
        media_types = frozenset(
            HostMediaType(value) for value in cast("list[str]", item["media_types"])
        )
        folders.append(
            HostMediaFolder(
                path=HostPath(path),
                recurse=recurse,
                media_types=media_types,
                follow_symlinks=cast("bool", item.get("follow_symlinks", False)),
            )
        )
    return tuple(folders)


def save_host_media_folders(
    settings: SettingsService,
    folders: tuple[HostMediaFolder, ...],
) -> None:
    """Persist the complete ordered Host Media Library folder selection."""

    value: HostMediaFoldersSetting = [
        {
            "path": os.fspath(folder.path),
            "recurse": folder.recurse,
            "follow_symlinks": folder.follow_symlinks,
            "media_types": [
                media_type.value
                for media_type in ALL_HOST_MEDIA_TYPES
                if media_type in folder.media_types
            ],
        }
        for folder in folders
    ]
    settings.set_global(HOST_MEDIA_FOLDERS, value)


def same_host_media_folder(first: HostMediaFolder, second: HostMediaFolder) -> bool:
    """Return whether two folder selections resolve to the same platform path."""

    return _path_identity(first.path.path) == _path_identity(second.path.path)


def _path_identity(path: os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


__all__ = [
    "ALL_HOST_MEDIA_TYPES",
    "HOST_MEDIA_FOLDERS",
    "HostMediaFolder",
    "HostMediaType",
    "create_host_media_folder",
    "load_host_media_folders",
    "same_host_media_folder",
    "save_host_media_folders",
]
