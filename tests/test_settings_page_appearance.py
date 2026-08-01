from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.settingsPage import SettingRow, ToggleRow, _SettingsCard


def test_settings_rows_use_resolved_surface_and_control_paints(qtbot) -> None:
    standalone_row = SettingRow("Library", "Where iOpenPod stores its cache.")
    row = SettingRow("Cache", "A card makes grouped rows transparent.")
    toggle = ToggleRow("Live updates", checked=True)
    card = _SettingsCard(row, toggle)
    qtbot.addWidget(standalone_row)
    qtbot.addWidget(card)

    assert paint_css("surface.default") in standalone_row.styleSheet()
    assert paint_css("border.subtle") in standalone_row.styleSheet()
    assert paint_css("control.primary.fill") in toggle.checkbox.styleSheet()
    assert paint_css("surface.inset") in card.styleSheet()
