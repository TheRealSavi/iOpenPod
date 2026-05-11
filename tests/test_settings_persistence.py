import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from infrastructure import settings_persistence
from infrastructure.settings_persistence import load_app_settings, save_app_settings
from infrastructure.settings_schema import AppSettings


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
            rounded_artwork=True,
            sharpen_artwork=False,
            track_list_columns_by_content={
                "music": {"Title": 220, "Album": 180, "Artist": 160}
            },
            window_width=1440,
            device_write_workers=2,
        )
        save_app_settings(settings)

        loaded = load_app_settings()

    assert loaded.media_folder == "C:/Music"
    assert loaded.rounded_artwork is True
    assert loaded.sharpen_artwork is False
    assert loaded.track_list_columns_by_content == {
        "music": {"Title": 220, "Album": 180, "Artist": 160}
    }
    assert loaded.window_width == 1440
    assert loaded.device_write_workers == 2
