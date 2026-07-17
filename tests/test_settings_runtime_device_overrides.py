from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.infrastructure import settings_runtime
from iopenpod.infrastructure.settings_runtime import SettingsRuntime
from iopenpod.infrastructure.settings_schema import AppSettings


@contextmanager
def repo_temp_dir():
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / ".tmp" / f"settings-runtime-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_device_settings_round_trip_preserves_device_write_workers(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        monkeypatch.setattr(settings_runtime, "_clear_transcoder_caches", lambda: None)
        (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
        (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
        runtime = SettingsRuntime()

        device_settings = AppSettings(
            sync_workers=6,
            device_write_workers=1,
            always_encode_lossy=True,
            convert_wav_to_alac=False,
            media_folder="C:/Music",
            listenbrainz_token="lb-token",
            listenbrainz_username="lb-user",
            lastfm_api_key="lf-key",
            lastfm_api_secret="lf-secret",
            lastfm_session_key="lf-session",
            lastfm_username="lf-user",
            backup_before_sync_mode="off",
            normalize_tags_after_sync=True,
        )
        runtime.save_device_settings(
            str(tmp_path),
            device_settings,
            device_key="SERIAL123",
        )
        raw = json.loads(
            (
                tmp_path
                / "iPod_Control"
                / "iOpenPod"
                / "settings.json"
            ).read_text(encoding="utf-8")
        )

        loaded = runtime.load_device_settings(
            str(tmp_path),
            "SERIAL123",
            AppSettings(),
        )

    assert loaded.settings.sync_workers == 6
    assert loaded.settings.device_write_workers == 1
    assert loaded.settings.always_encode_lossy is True
    assert loaded.settings.convert_wav_to_alac is False
    assert loaded.settings.listenbrainz_token == "lb-token"
    assert loaded.settings.listenbrainz_username == "lb-user"
    assert loaded.settings.lastfm_api_key == "lf-key"
    assert loaded.settings.lastfm_api_secret == "lf-secret"
    assert loaded.settings.lastfm_session_key == "lf-session"
    assert loaded.settings.lastfm_username == "lf-user"
    assert loaded.settings.backup_before_sync_mode == "off"
    assert loaded.settings.backup_before_sync is False
    assert loaded.settings.normalize_tags_after_sync is True
    assert raw["settings"]["lastfm_api_key"].startswith("xor1:")
    assert raw["settings"]["lastfm_api_secret"].startswith("xor1:")
    assert raw["settings"]["lastfm_session_key"].startswith("xor1:")
    assert raw["settings"]["lastfm_username"] == "lf-user"
    assert raw["settings"]["backup_before_sync_mode"] == "off"
    assert raw["settings"]["normalize_tags_after_sync"] is True
    assert raw["settings"]["always_encode_lossy"] is True
    assert raw["settings"]["convert_wav_to_alac"] is False


def test_normalize_tags_after_sync_defaults_off() -> None:
    assert AppSettings().normalize_tags_after_sync is False


def test_corrupt_device_settings_are_not_silently_overwritten(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        monkeypatch.setattr(settings_runtime, "_clear_transcoder_caches", lambda: None)
        settings_path = tmp_path / "iPod_Control" / "iOpenPod" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{broken", encoding="utf-8")
        original = settings_path.read_bytes()
        runtime = SettingsRuntime()

        loaded = runtime.load_device_settings(str(tmp_path), "", AppSettings())

        assert loaded.exists is True
        assert "could not be read safely" in loaded.load_error
        with pytest.raises(DeviceWriteSafetyError, match="did not overwrite"):
            runtime.save_device_settings(str(tmp_path), AppSettings())
        assert settings_path.read_bytes() == original


def test_device_settings_migrates_legacy_backup_false_to_ask(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        monkeypatch.setattr(settings_runtime, "_clear_transcoder_caches", lambda: None)
        settings_path = (
            tmp_path / "iPod_Control" / "iOpenPod" / "settings.json"
        )
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"settings": {"backup_before_sync": False}}),
            encoding="utf-8",
        )
        runtime = SettingsRuntime()

        loaded = runtime.load_device_settings(str(tmp_path), "", AppSettings())

    assert loaded.settings.backup_before_sync_mode == "ask"
    assert loaded.settings.backup_before_sync is False


def test_grid_item_size_is_global_only_and_ignores_legacy_device_value(
    monkeypatch,
) -> None:
    with repo_temp_dir() as tmp_path:
        monkeypatch.setattr(settings_runtime, "_clear_transcoder_caches", lambda: None)
        settings_path = (
            tmp_path / "iPod_Control" / "iOpenPod" / "settings.json"
        )
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "use_global_settings": False,
                    "settings": {
                        "grid_item_size": "large",
                        "sync_workers": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        runtime = SettingsRuntime()

        loaded = runtime.load_device_settings(
            str(tmp_path),
            "",
            AppSettings(grid_item_size="small", sync_workers=6),
        )

    assert loaded.settings.grid_item_size == "small"
    assert loaded.settings.sync_workers == 2
