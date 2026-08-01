import pytest

from iopenpod.gui import styles
from iopenpod.gui.styles import (
    apply_theme,
    apply_theme_selection,
    button_css,
    combo_css,
    current_theme,
    input_css,
    paint_css,
    table_css,
)
from iopenpod.infrastructure import theme_catalog


def test_auto_theme_uses_the_matching_configured_palette(monkeypatch, tmp_path) -> None:
    theme_snapshot = current_theme()
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(theme_catalog, "get_settings_path", lambda: str(settings_path))
    theme_catalog.load_theme_catalog(seed_bundled=True)
    monkeypatch.setattr(styles, "_detect_system_dark", lambda: False)
    try:
        apply_theme_selection(
            "auto",
            "catppuccin-latte",
            "catppuccin-mocha",
        )
        assert current_theme().theme_id == "catppuccin-latte"
        assert not current_theme().is_dark
    finally:
        styles._THEME_RUNTIME.replace(theme_snapshot)


def test_shared_style_factories_consume_final_component_paints() -> None:
    theme_snapshot = current_theme()
    apply_theme("dark", "off", "blue")
    try:
        resolved = current_theme()
        stylesheet = "\n".join(
            (
                button_css("primary"),
                button_css("danger"),
                input_css(),
                combo_css(),
                table_css(),
            )
        )

        for name in (
            "control.primary.pressed_fill",
            "status.danger.subtle_fill",
            "focus.border",
            "selection.fill",
            "table.row.selected_fill",
        ):
            assert resolved.paint(name).css in stylesheet
        assert "rgba(" not in stylesheet
        with pytest.raises(ValueError, match="legacy token"):
            paint_css("ACCENT")
    finally:
        styles._THEME_RUNTIME.replace(theme_snapshot)


def test_theme_selection_reports_non_accent_palette_changes(monkeypatch, tmp_path) -> None:
    """A rebuild is required when a same-accent theme changes other paints."""

    built_in_dark = theme_catalog.load_theme_catalog().get("dark")
    first_colors = dict(built_in_dark.colors)
    second_colors = dict(first_colors)
    second_colors["background"] = "#202040"
    catalog = theme_catalog.ThemeCatalog(
        themes={
            "dark": built_in_dark,
            "first": theme_catalog.ThemeDefinition(
                id="first",
                name="First",
                type="dark",
                colors=first_colors,
                high_contrast={},
            ),
            "second": theme_catalog.ThemeDefinition(
                id="second",
                name="Second",
                type="dark",
                colors=second_colors,
                high_contrast={},
            ),
        },
        directory=tmp_path,
    )
    monkeypatch.setattr("iopenpod.gui.styles.load_theme_catalog", lambda: catalog)

    theme_snapshot = current_theme()
    try:
        apply_theme_selection("dark", "light", "first")
        first_accent = paint_css("control.primary.fill")
        assert apply_theme_selection("dark", "light", "second")
        assert paint_css("control.primary.fill") == first_accent
        assert current_theme().paint("canvas.default").css == "#202040"
    finally:
        styles._THEME_RUNTIME.replace(theme_snapshot)
