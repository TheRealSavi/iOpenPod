from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from iopenpod.application.services import SettingsSnapshot
from iopenpod.infrastructure.settings_schema import AppSettings


def test_settings_snapshot_copies_values_and_freezes_lists() -> None:
    settings = AppSettings(
        media_folder="C:/Music",
        media_folders=[
            {
                "directory": "C:/Music",
                "recurse": True,
                "media_types": ["music", "video", "photo"],
            },
            {
                "directory": "D:/Audiobooks",
                "recurse": False,
                "media_types": ["music"],
            },
        ],
        theme="light",
        theme_mode="light",
        light_theme="catppuccin-latte",
        dark_theme="catppuccin-mocha",
        accent_color="#123456",
        player_position="top",
        rounded_artwork=True,
        sharpen_artwork=False,
        grid_item_size="small",
        track_list_columns_by_content={
            "music": {"Title": 240, "Album": 180, "Artist": 160}
        },
        device_write_workers=2,
        always_encode_lossy=True,
        convert_wav_to_alac=False,
        splitter_sizes=[300, 700],
        window_width=1440,
        window_height=900,
        scrobble_on_sync=True,
        listenbrainz_token="lb-token",
        listenbrainz_username="lb-user",
        lastfm_api_key="lf-key",
        lastfm_api_secret="lf-secret",
        lastfm_session_key="lf-session",
        lastfm_username="lf-user",
        backup_before_sync_mode="ask",
        normalize_tags_after_sync=True,
    )

    snapshot = SettingsSnapshot.from_settings(cast(Any, settings))

    assert snapshot.media_folder == "C:/Music"
    assert snapshot.media_folders == (
        {
            "directory": "C:/Music",
            "recurse": True,
            "media_types": ["music", "video", "photo"],
        },
        {
            "directory": "D:/Audiobooks",
            "recurse": False,
            "media_types": ["music"],
        },
    )
    assert snapshot.theme == "light"
    assert snapshot.theme_mode == "light"
    assert snapshot.light_theme == "catppuccin-latte"
    assert snapshot.dark_theme == "catppuccin-mocha"
    assert snapshot.accent_color == "#123456"
    assert snapshot.player_position == "top"
    assert snapshot.rounded_artwork is True
    assert snapshot.sharpen_artwork is False
    assert snapshot.grid_item_size == "small"
    assert snapshot.track_list_columns_by_content == {
        "music": {"Title": 240, "Album": 180, "Artist": 160}
    }
    assert snapshot.device_write_workers == 2
    assert snapshot.always_encode_lossy is True
    assert snapshot.convert_wav_to_alac is False
    assert snapshot.splitter_sizes == (300, 700)
    assert snapshot.window_width == 1440
    assert snapshot.window_height == 900
    assert snapshot.scrobble_on_sync is True
    assert snapshot.listenbrainz_token == "lb-token"
    assert snapshot.listenbrainz_username == "lb-user"
    assert snapshot.lastfm_api_key == "lf-key"
    assert snapshot.lastfm_api_secret == "lf-secret"
    assert snapshot.lastfm_session_key == "lf-session"
    assert snapshot.lastfm_username == "lf-user"
    assert snapshot.backup_before_sync_mode == "ask"
    assert snapshot.backup_before_sync is False
    assert snapshot.normalize_tags_after_sync is True

    settings.track_list_columns_by_content["music"]["year"] = 120
    assert "year" not in snapshot.track_list_columns_by_content["music"]
    settings.media_folders.append({
        "directory": "E:/Podcasts",
        "recurse": True,
        "media_types": ["music"],
    })
    assert snapshot.media_folders == (
        {
            "directory": "C:/Music",
            "recurse": True,
            "media_types": ["music", "video", "photo"],
        },
        {
            "directory": "D:/Audiobooks",
            "recurse": False,
            "media_types": ["music"],
        },
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.theme = "dark"  # type: ignore[misc]


def test_settings_snapshot_upgrades_legacy_media_folder_strings() -> None:
    settings = AppSettings(media_folders=["C:/Music"])  # type: ignore

    snapshot = SettingsSnapshot.from_settings(settings)

    assert snapshot.media_folders == (
        {
            "directory": "C:/Music",
            "recurse": True,
            "media_types": ["music", "video", "photo", "playlists"],
        },
    )
