"""Behavioral tests for typed and persistent application settings."""

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray

from iOpenPod.app.core.settings import paths as settings_paths
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_DARK_THEME,
    APPEARANCE_LIGHT_THEME,
    APPEARANCE_MODE,
    COLORFUL_MODE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    LAST_SELECTED_IPOD_VOLUME_ID,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    PLAYER_POSITION,
    TRACK_TITLE_BAR_STYLE,
    WINDOW_GEOMETRY,
    DarkTheme,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
    LightTheme,
    PlayerPosition,
    SettingDefinition,
    TrackTitleBarStyle,
)
from iOpenPod.app.core.settings.service import SettingSource, SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
    JsonSettingsStore,
    SettingsStore,
    create_global_settings_store,
)
from storage import AtomicHostFile, Storage
from storage.testing import VirtualStoragePlatform


class _LinuxHostPlatform(VirtualStoragePlatform):
    @property
    def name(self) -> str:
        return "linux"


def _service(global_store: SettingsStore | None = None) -> SettingsService:
    return SettingsService(
        global_store or GlobalSettingsStore(),
        DeviceSettingsStore(),
    )


def test_default_global_and_reset_resolution() -> None:
    service = _service()

    assert service.get(APPEARANCE_MODE) == "system"
    assert service.source(APPEARANCE_MODE) is SettingSource.DEFAULT
    assert service.get(PLAYER_POSITION) == PlayerPosition.TOP.value
    assert service.source(PLAYER_POSITION) is SettingSource.DEFAULT
    assert service.get(DRAFT_ALL_CHANGES) is False
    assert service.source(DRAFT_ALL_CHANGES) is SettingSource.DEFAULT

    service.set_global(APPEARANCE_MODE, "dark")
    assert service.get(APPEARANCE_MODE) == "dark"
    assert service.source(APPEARANCE_MODE) is SettingSource.GLOBAL

    service.reset_global(APPEARANCE_MODE)
    assert service.get(APPEARANCE_MODE) == "system"
    assert service.source(APPEARANCE_MODE) is SettingSource.DEFAULT


def test_legacy_recovery_hints_are_removed_without_changing_preferences(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings-v2.json"
    path.write_text(
        json.dumps(
            {
                APPEARANCE_MODE.key: "dark",
                "sync/pending-recovery-journal": ".iopenpod-recovery/"
                + "a" * 32
                + "/transaction.json",
                "sync/pending-cleanup-journal": "invalid stale value",
            }
        )
    )
    store = JsonSettingsStore(AtomicHostFile(path))
    assert not store.has("sync/pending-recovery-journal")
    assert not store.has("sync/pending-cleanup-journal")
    store.sync()
    assert json.loads(path.read_text()) == {APPEARANCE_MODE.key: "dark"}


def test_invalid_persisted_value_falls_back_without_poisoning_settings() -> None:
    store = GlobalSettingsStore()
    store.set(APPEARANCE_MODE.key, "sepia")
    service = _service(store)

    assert service.get(APPEARANCE_MODE) == "system"
    assert service.source(APPEARANCE_MODE) is SettingSource.DEFAULT


def test_invalid_write_is_rejected() -> None:
    service = _service()

    try:
        service.set_global(APPEARANCE_MODE, "sepia")
    except ValueError as error:
        assert APPEARANCE_MODE.key in str(error)
    else:
        raise AssertionError("An invalid theme value was accepted")


def test_invalid_player_position_is_rejected() -> None:
    service = _service()

    with pytest.raises(ValueError, match=PLAYER_POSITION.key):
        service.set_global(PLAYER_POSITION, "left")


def test_ipod_view_mode_defaults_and_rejects_invalid_values() -> None:
    store = GlobalSettingsStore()
    service = _service(store)
    assert service.get(IPOD_LIBRARY_VIEW_MODE) == IPodLibraryViewMode.SPLIT_TABLE.value
    store.set(IPOD_LIBRARY_VIEW_MODE.key, "unknown")
    assert service.get(IPOD_LIBRARY_VIEW_MODE) == IPodLibraryViewMode.SPLIT_TABLE.value
    with pytest.raises(ValueError, match=IPOD_LIBRARY_VIEW_MODE.key):
        service.set_global(IPOD_LIBRARY_VIEW_MODE, "unknown")


def test_track_title_bar_style_defaults_and_rejects_invalid_values() -> None:
    store = GlobalSettingsStore()
    service = _service(store)
    assert service.get(TRACK_TITLE_BAR_STYLE) == TrackTitleBarStyle.FLAT.value
    store.set(TRACK_TITLE_BAR_STYLE.key, "unknown")
    assert service.get(TRACK_TITLE_BAR_STYLE) == TrackTitleBarStyle.FLAT.value
    with pytest.raises(ValueError, match=TRACK_TITLE_BAR_STYLE.key):
        service.set_global(TRACK_TITLE_BAR_STYLE, "unknown")


def test_library_double_click_defaults_and_rejects_invalid_values() -> None:
    store = GlobalSettingsStore()
    service = _service(store)
    assert service.get(LIBRARY_DOUBLE_CLICK_SHORTCUT) == "add-to-queue"
    store.set(LIBRARY_DOUBLE_CLICK_SHORTCUT.key, "unknown")
    assert service.get(LIBRARY_DOUBLE_CLICK_SHORTCUT) == "add-to-queue"
    with pytest.raises(ValueError, match=LIBRARY_DOUBLE_CLICK_SHORTCUT.key):
        service.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, "unknown")


@pytest.mark.parametrize("action", LibraryDoubleClickShortcut)
def test_library_double_click_preference_survives_restart(
    tmp_path: Path, action: LibraryDoubleClickShortcut
) -> None:
    settings_path = tmp_path / "settings-v2.json"
    first = _service(JsonSettingsStore(AtomicHostFile(settings_path)))
    first.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, action.value)
    second = _service(JsonSettingsStore(AtomicHostFile(settings_path)))
    assert second.get(LIBRARY_DOUBLE_CLICK_SHORTCUT) == action.value


def test_windows_native_backup_default_does_not_reuse_original_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "platform", "win32")

    resolved = settings_paths.default_backup_path()

    assert resolved == tmp_path / "local" / "iOpenPod" / "Backups"
    assert resolved != Path.home() / "iOpenPod" / "backups"


def test_windows_native_backup_default_ignores_relative_environment_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "relative-local-data")
    monkeypatch.setattr(sys, "platform", "win32")

    resolved = settings_paths.default_backup_path()

    assert resolved == Path.home() / "AppData" / "Local" / "iOpenPod" / "Backups"
    assert resolved.is_absolute()


def test_device_override_wins_only_for_an_active_ipod() -> None:
    volume = SettingDefinition[int](
        key="playback/volume",
        value_type=int,
        default=50,
        device_overridable=True,
        validator=lambda value: 0 <= value <= 100,
    )
    service = _service()
    service.set_global(volume, 40)
    service.load_device("device-1", {volume.key: 75})

    assert service.get(volume) == 75
    assert service.source(volume) is SettingSource.DEVICE

    service.unload_device()
    assert service.get(volume) == 40
    assert service.source(volume) is SettingSource.GLOBAL


def test_json_store_immediately_persists_typed_settings_through_storage(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings-v2.json"
    first = SettingsService(
        JsonSettingsStore(AtomicHostFile(settings_path)),
        DeviceSettingsStore(),
    )
    geometry = QByteArray(b"window-geometry")
    first.set_global(APPEARANCE_MODE, "dark")
    first.set_global(APPEARANCE_LIGHT_THEME, LightTheme.PORCELAIN.value)
    first.set_global(APPEARANCE_DARK_THEME, DarkTheme.ORIGINAL.value)
    first.set_global(COLORFUL_MODE, True)
    first.set_global(DRAFT_ALL_CHANGES, True)
    first.set_global(IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value)
    first.set_global(PLAYER_POSITION, PlayerPosition.BOTTOM.value)
    first.set_global(TRACK_TITLE_BAR_STYLE, TrackTitleBarStyle.ROUND.value)
    first.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "windows:volume-id")
    first.set_global(WINDOW_GEOMETRY, geometry)

    second = SettingsService(
        JsonSettingsStore(AtomicHostFile(settings_path)),
        DeviceSettingsStore(),
    )

    assert second.get(APPEARANCE_MODE) == "dark"
    assert second.get(APPEARANCE_LIGHT_THEME) == LightTheme.PORCELAIN.value
    assert second.get(APPEARANCE_DARK_THEME) == DarkTheme.ORIGINAL.value
    assert second.get(COLORFUL_MODE) is True
    assert second.get(DRAFT_ALL_CHANGES) is True
    assert (
        second.get(IPOD_LIBRARY_VIEW_MODE) == IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    assert second.get(PLAYER_POSITION) == PlayerPosition.BOTTOM.value
    assert second.get(TRACK_TITLE_BAR_STYLE) == TrackTitleBarStyle.ROUND.value
    assert second.get(LAST_SELECTED_IPOD_VOLUME_ID) == "windows:volume-id"
    assert second.get(WINDOW_GEOMETRY) == geometry
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "appearance/player-position": "bottom",
        "appearance/colorful-mode": True,
        "appearance/dark-theme": "original",
        "appearance/light-theme": "porcelain",
        "appearance/theme": "dark",
        "appearance/track-title-bar-style": "round",
        "devices/last-selected-volume-id": "windows:volume-id",
        "library/draft-all-changes": True,
        "library/ipod-view-mode": "whole-page-table",
        "window/main/geometry": {
            "encoding": "base64",
            "type": "QByteArray",
            "value": "d2luZG93LWdlb21ldHJ5",
        },
    }


def test_global_settings_factory_uses_a_v2_file_without_touching_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    service = SettingsService(
        create_global_settings_store(Storage(_LinuxHostPlatform())),
        DeviceSettingsStore(),
    )

    service.set_global(APPEARANCE_MODE, "dark")

    v2_path = tmp_path / "iopenpod" / "settings-v2.json"
    assert json.loads(v2_path.read_text(encoding="utf-8")) == {
        APPEARANCE_MODE.key: "dark"
    }
    assert not (tmp_path / "iopenpod" / "settings.json").exists()
