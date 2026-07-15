import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from iopenpod.infrastructure import settings_persistence
from iopenpod.infrastructure.settings_persistence import load_app_settings, save_app_settings
from iopenpod.infrastructure.settings_schema import PLAYER_POSITION_TOP, AppSettings


@contextmanager
def repo_temp_dir():
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / ".tmp" / f"settings-persistence-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_settings_persistence_round_trip(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        monkeypatch.setattr(
            settings_persistence,
            "default_settings_dir",
            lambda: str(settings_dir),
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_dir / "settings.json"),
        )

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
            rounded_artwork=True,
            sharpen_artwork=False,
            grid_item_size="small",
            player_position="top",
            track_list_columns_by_content={
                "music": {"Title": 220, "Album": 180, "Artist": 160}
            },
            window_width=1440,
            device_write_workers=2,
            always_encode_lossy=True,
            convert_wav_to_alac=False,
            scrobble_on_sync=True,
            listenbrainz_token="lb-token",
            listenbrainz_username="lb-user",
            lastfm_api_key="lf-key",
            lastfm_api_secret="lf-secret",
            lastfm_session_key="lf-session",
            lastfm_username="lf-user",
            backup_before_sync_mode="off",
            theme_mode="auto",
            light_theme="catppuccin-latte",
            dark_theme="catppuccin-macchiato",
        )
        save_app_settings(settings)

        loaded = load_app_settings()

    assert loaded.media_folder == "C:/Music"
    assert loaded.media_folders == [
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
    ]
    assert loaded.rounded_artwork is True
    assert loaded.sharpen_artwork is False
    assert loaded.grid_item_size == "small"
    assert loaded.player_position == "top"
    assert loaded.track_list_columns_by_content == {
        "music": {"Title": 220, "Album": 180, "Artist": 160}
    }
    assert loaded.window_width == 1440
    assert loaded.device_write_workers == 2
    assert loaded.always_encode_lossy is True
    assert loaded.convert_wav_to_alac is False
    assert loaded.scrobble_on_sync is True
    assert loaded.listenbrainz_token == "lb-token"
    assert loaded.listenbrainz_username == "lb-user"
    assert loaded.lastfm_api_key == "lf-key"
    assert loaded.lastfm_api_secret == "lf-secret"
    assert loaded.lastfm_session_key == "lf-session"
    assert loaded.lastfm_username == "lf-user"
    assert loaded.backup_before_sync_mode == "off"
    assert loaded.backup_before_sync is False
    assert loaded.theme_mode == "auto"
    assert loaded.light_theme == "catppuccin-latte"
    assert loaded.dark_theme == "catppuccin-macchiato"
    assert loaded.theme == "system"


def test_settings_persistence_upgrades_legacy_media_folder_strings(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(
            json.dumps({"media_folders": ["C:/Music"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        loaded = load_app_settings()

    assert loaded.media_folders == [
        {
            "directory": "C:/Music",
            "recurse": True,
            "media_types": ["music", "video", "photo", "playlists"],
        }
    ]


def test_settings_persistence_migrates_legacy_single_theme(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(
            json.dumps({"theme": "catppuccin-latte"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        loaded = load_app_settings()

    assert loaded.theme_mode == "light"
    assert loaded.light_theme == "catppuccin-latte"
    assert loaded.dark_theme == "dark"
    assert loaded.theme == "catppuccin-latte"


def test_settings_persistence_migrates_legacy_backup_false_to_ask(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(
            json.dumps({"backup_before_sync": False}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        loaded = load_app_settings()

    assert loaded.backup_before_sync_mode == "ask"
    assert loaded.backup_before_sync is False


def test_settings_persistence_preserves_legacy_bool_setter(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        monkeypatch.setattr(
            settings_persistence,
            "default_settings_dir",
            lambda: str(settings_dir),
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_dir / "settings.json"),
        )
        settings = AppSettings()
        settings.backup_before_sync = False

        save_app_settings(settings)
        loaded = load_app_settings()

    assert loaded.backup_before_sync_mode == "ask"
    assert loaded.backup_before_sync is False


def test_settings_defaults_player_position_to_top() -> None:
    settings = AppSettings()

    assert settings.player_position == PLAYER_POSITION_TOP
    assert settings.theme_mode == "auto"
    assert settings.light_theme == "light"
    assert settings.dark_theme == "dark"


def test_settings_persistence_defaults_missing_player_position_to_top(monkeypatch) -> None:
    with repo_temp_dir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        loaded = load_app_settings()

    assert loaded.player_position == PLAYER_POSITION_TOP
