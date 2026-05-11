from dataclasses import FrozenInstanceError

import pytest

from app_core.services import SettingsSnapshot
from infrastructure.settings_schema import AppSettings


def test_settings_snapshot_copies_values_and_freezes_lists() -> None:
    settings = AppSettings(
        media_folder="C:/Music",
        theme="light",
        accent_color="#123456",
        rounded_artwork=True,
        sharpen_artwork=False,
        track_list_columns_by_content={
            "music": {"Title": 240, "Album": 180, "Artist": 160}
        },
        device_write_workers=2,
        splitter_sizes=[300, 700],
        window_width=1440,
        window_height=900,
    )

    snapshot = SettingsSnapshot.from_settings(settings)

    assert snapshot.media_folder == "C:/Music"
    assert snapshot.theme == "light"
    assert snapshot.accent_color == "#123456"
    assert snapshot.rounded_artwork is True
    assert snapshot.sharpen_artwork is False
    assert snapshot.track_list_columns_by_content == {
        "music": {"Title": 240, "Album": 180, "Artist": 160}
    }
    assert snapshot.device_write_workers == 2
    assert snapshot.splitter_sizes == (300, 700)
    assert snapshot.window_width == 1440
    assert snapshot.window_height == 900

    settings.track_list_columns_by_content["music"]["year"] = 120
    assert "year" not in snapshot.track_list_columns_by_content["music"]

    with pytest.raises(FrozenInstanceError):
        snapshot.theme = "dark"  # type: ignore[misc]
