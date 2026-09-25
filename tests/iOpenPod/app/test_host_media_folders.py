"""Tests for persisted Host Media Library folder choices."""

import json
import os
from pathlib import Path

import pytest

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, JsonSettingsStore
from iOpenPod.app.host_media_folders import (
    ALL_HOST_MEDIA_TYPES,
    HOST_MEDIA_FOLDERS,
    HostMediaFolder,
    HostMediaType,
    create_host_media_folder,
    load_host_media_folders,
    save_host_media_folders,
)
from storage import AtomicHostFile


def _settings(path: Path) -> SettingsService:
    return SettingsService(
        JsonSettingsStore(AtomicHostFile(path)),
        DeviceSettingsStore(),
    )


def test_new_folder_enables_recursion_and_every_media_type(tmp_path: Path) -> None:
    folder = create_host_media_folder(tmp_path / "Media")

    assert os.fspath(folder.path) == os.fspath(tmp_path / "Media")
    assert folder.recurse is True
    assert folder.media_types == frozenset(ALL_HOST_MEDIA_TYPES)


def test_folders_and_individual_settings_round_trip_as_readable_json(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings-v2.json"
    service = _settings(settings_path)
    music = create_host_media_folder(tmp_path / "Music")
    photos = HostMediaFolder(
        path=create_host_media_folder(tmp_path / "Photos").path,
        recurse=False,
        media_types=frozenset({HostMediaType.PHOTOS}),
    )

    save_host_media_folders(service, (music, photos))

    reloaded = load_host_media_folders(_settings(settings_path))
    assert reloaded == (music, photos)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        HOST_MEDIA_FOLDERS.key: [
            {
                "path": os.fspath(tmp_path / "Music"),
                "recurse": True,
                "media_types": ["audio", "video", "photos", "playlists"],
            },
            {
                "path": os.fspath(tmp_path / "Photos"),
                "recurse": False,
                "media_types": ["photos"],
            },
        ]
    }


def test_duplicate_persisted_folders_are_rejected(tmp_path: Path) -> None:
    service = _settings(tmp_path / "settings-v2.json")
    path = os.fspath(tmp_path / "Music")
    duplicate = {
        "path": path,
        "recurse": True,
        "media_types": ["audio"],
    }

    duplicated_setting: list[object] = [duplicate, duplicate]
    with pytest.raises(ValueError, match=HOST_MEDIA_FOLDERS.key):
        service.set_global(HOST_MEDIA_FOLDERS, duplicated_setting)
