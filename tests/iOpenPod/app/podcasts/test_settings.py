"""Podcast defaults persist atomically in the Host settings document."""

import json
from pathlib import Path

import pytest

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, JsonSettingsStore
from iOpenPod.app.podcasts.models import (
    PodcastClearAge,
    PodcastClearMethod,
    PodcastFillMode,
    PodcastSyncSettings,
)
from iOpenPod.app.podcasts.settings import (
    DEFAULT_PODCAST_SYNC_SETTINGS,
    read_default_podcast_sync_settings,
    save_default_podcast_sync_settings,
)
from storage import AtomicHostFile


@pytest.mark.parametrize("slots", (0, 7, 50))
def test_defaults_round_trip_all_choices_in_host_settings(
    tmp_path: Path, slots: int
) -> None:
    path = tmp_path / "settings-v2.json"
    service = SettingsService(
        JsonSettingsStore(AtomicHostFile(path)), DeviceSettingsStore()
    )
    assert read_default_podcast_sync_settings(service) == PodcastSyncSettings()
    assert not path.exists()
    chosen = PodcastSyncSettings(
        slots,
        PodcastFillMode.NEXT,
        False,
        PodcastClearAge.WEEK,
        PodcastClearMethod.REPLACE,
    )
    save_default_podcast_sync_settings(service, chosen)
    restored = SettingsService(
        JsonSettingsStore(AtomicHostFile(path)), DeviceSettingsStore()
    )
    assert read_default_podcast_sync_settings(restored) == chosen
    assert not DEFAULT_PODCAST_SYNC_SETTINGS.device_overridable
    restored.load_device("ipod", {DEFAULT_PODCAST_SYNC_SETTINGS.key: {}})
    assert read_default_podcast_sync_settings(restored) == chosen


@pytest.mark.parametrize(
    "invalid",
    (
        None,
        "invalid",
        {},
        {"episode_slots": 99},
        {
            "episode_slots": True,
            "fill_mode": "newest",
            "clear_when_listened": True,
            "clear_older_than": "never",
            "clear_method": "remove",
        },
    ),
)
def test_invalid_defaults_fall_back_without_rewriting_file(
    tmp_path: Path, invalid: object
) -> None:
    path = tmp_path / "settings-v2.json"
    payload = json.dumps({DEFAULT_PODCAST_SYNC_SETTINGS.key: invalid})
    path.write_text(payload, encoding="utf-8")
    service = SettingsService(
        JsonSettingsStore(AtomicHostFile(path)), DeviceSettingsStore()
    )
    assert read_default_podcast_sync_settings(service) == PodcastSyncSettings()
    assert path.read_text(encoding="utf-8") == payload
