from typing import cast

from iopenpod.application.services import DeviceSessionService, SettingsService
from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets import settingsPage


def test_theme_default_accent_label_round_trips_to_blue_setting() -> None:
    assert settingsPage._ACCENT_COLOR_DISPLAY["blue"] == "Theme Default"
    assert settingsPage._ACCENT_COLOR_BY_TEXT["Theme Default"] == "blue"
    assert settingsPage._ACCENT_COLOR_DISPLAY["preset-blue"] == "Blue"
    assert settingsPage._ACCENT_COLOR_BY_TEXT["Blue"] == "preset-blue"


def test_settings_rows_use_resolved_surface_and_control_paints(qtbot) -> None:
    standalone_row = settingsPage.SettingRow("Library", "Where iOpenPod stores its cache.")
    row = settingsPage.SettingRow("Cache", "A card makes grouped rows transparent.")
    toggle = settingsPage.ToggleRow("Live updates", checked=True)
    card = settingsPage._SettingsCard(row, toggle)
    qtbot.addWidget(standalone_row)
    qtbot.addWidget(card)

    assert paint_css("surface.default") in standalone_row.styleSheet()
    assert paint_css("border.subtle") in standalone_row.styleSheet()
    assert paint_css("control.primary.fill") in toggle.checkbox.styleSheet()
    assert paint_css("surface.inset") in card.styleSheet()


def test_reencode_lossy_control_respects_device_settings_scope(qtbot) -> None:
    page = settingsPage.SettingsPage(
        settings_service=cast(SettingsService, object()),
        device_sessions=cast(DeviceSessionService, object()),
    )
    qtbot.addWidget(page)

    page._set_device_rows_enabled(False)

    assert page.always_encode_lossy.isEnabled() is False
    assert page.always_encode_lossy in page._device_overridable_rows()
