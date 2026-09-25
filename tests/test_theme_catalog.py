import json

import pytest

from iopenpod.infrastructure.settings_schema import AppSettings
from iopenpod.infrastructure.theme_catalog import (
    bundled_theme_directory,
    install_bundled_theme_files,
    load_theme_catalog,
)
from iopenpod.infrastructure.theme_renderer import render_theme


def _theme_json(*, name: str = "Ocean", theme_type: str = "dark") -> dict:
    colors = dict(load_theme_catalog().get("dark").colors)
    colors["accent"] = "#123"
    return {"name": name, "type": theme_type, "colors": colors}


def test_catalog_discovers_valid_theme_and_sorts_it_by_type(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    (theme_dir / "ocean.json").write_text(json.dumps(_theme_json()), encoding="utf-8")

    catalog = load_theme_catalog(theme_dir)

    assert catalog.get("ocean").name == "Ocean"
    assert catalog.get("ocean").colors["accent"] == "#112233"
    assert [theme.id for theme in catalog.available("dark")] == ["dark", "ocean"]
    assert [theme.id for theme in catalog.available("light")] == ["light"]


def test_catalog_ignores_json_that_breaks_the_public_color_contract(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    broken = _theme_json()
    broken["colors"]["accent"] = "rgba(1, 2, 3, 0.5)"
    (theme_dir / "broken.json").write_text(json.dumps(broken), encoding="utf-8")

    catalog = load_theme_catalog(theme_dir)

    assert "broken" not in catalog.themes


def test_catalog_accepts_a_compact_foundation_palette_and_renderer_fills_optional_roles(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    minimal = {
        "name": "Minimal",
        "type": "dark",
        "colors": {
            "accent": "#123456",
            "background": "#101820",
            "background_alt": "#182838",
            "surface": "#203040",
            "surface_raised": "#304050",
            "text_primary": "#f0f4f8",
            "text_secondary": "#c8d4e0",
            "text_tertiary": "#a0b0c0",
            "text_disabled": "#708090",
            "border": "#506070",
            "danger": "#d94040",
            "success": "#40b870",
            "warning": "#e0a030",
            "info": "#5098d8",
        },
    }
    (theme_dir / "minimal.json").write_text(json.dumps(minimal), encoding="utf-8")

    theme = load_theme_catalog(theme_dir).get("minimal")
    rendered = render_theme(theme)

    assert rendered.paint("control.primary.hover_fill").css == "#4d6680"
    assert rendered.paint("surface.inset").css == "#203040"
    assert rendered.paint("data.rating.text").css == "#e0a030"
    assert rendered.paint("playlist.regular").color.rgb == (18, 52, 86)


def test_high_contrast_uses_theme_override_then_automatic_adjustment(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    ocean = _theme_json()
    ocean["high_contrast"] = {"text_secondary": "#55aa55"}
    (theme_dir / "ocean.json").write_text(json.dumps(ocean), encoding="utf-8")

    rendered = render_theme(load_theme_catalog(theme_dir).get("ocean"), high_contrast=True)

    assert rendered.paint("text.primary").css == "#ffffff"
    assert rendered.paint("text.secondary").css == "#55aa55"
    assert rendered.paint("border.default").css == "#ffffff"


def test_playlist_colors_are_named_renderer_paints(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    ocean = _theme_json()
    ocean["colors"]["playlist_regular"] = "#123456"
    (theme_dir / "ocean.json").write_text(json.dumps(ocean), encoding="utf-8")

    theme = load_theme_catalog(theme_dir).get("ocean")

    assert render_theme(theme).paint("playlist.regular").color.rgb == (18, 52, 86)


def test_legacy_theme_files_receive_visible_surface_interaction_fallbacks(tmp_path) -> None:
    theme_dir = tmp_path / "themes"
    theme_dir.mkdir()
    legacy = _theme_json()
    for name in (
        "surface_alt",
        "surface_hover",
        "surface_active",
        "menu_background",
        "dialog_background",
        "tooltip_background",
        "border_subtle",
        "gridline",
    ):
        legacy["colors"].pop(name, None)
    (theme_dir / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")

    rendered = render_theme(load_theme_catalog(theme_dir).get("legacy"))

    assert rendered.paint("surface.inset").css == legacy["colors"]["surface"]
    normal = rendered.paint("control.secondary.fill").color
    hover = rendered.paint("control.secondary.hover_fill").color
    pressed = rendered.paint("control.secondary.pressed_fill").color

    assert rendered.paint("surface.hover").css != legacy["colors"]["surface_raised"]
    assert max(abs(left - right) for left, right in zip(normal.rgb, hover.rgb, strict=True)) >= 10
    assert pressed != hover
    assert rendered.paint("modal.background").css == legacy["colors"]["background_alt"]


@pytest.mark.parametrize(
    ("theme_id", "expected"),
    [
        (
            "catppuccin-mocha",
            {
                "surface.default": "#222333",
                "surface.inset": "#313244",
                "surface.raised": "#45475a",
                "surface.hover": "#585b70",
                "menu.background": "#313244",
                "modal.background": "#181825",
                "tooltip.background": "#313244",
                "text.primary": "#cdd6f4",
            },
        ),
        (
            "catppuccin-macchiato",
            {
                "surface.default": "#282b3f",
                "surface.inset": "#363a4f",
                "surface.raised": "#494d64",
                "surface.hover": "#5b6078",
                "menu.background": "#363a4f",
                "modal.background": "#1e2030",
                "tooltip.background": "#363a4f",
                "text.primary": "#cad3f5",
            },
        ),
        (
            "catppuccin-frappe",
            {
                "surface.default": "#34384a",
                "surface.inset": "#414559",
                "surface.raised": "#51576d",
                "surface.hover": "#626880",
                "menu.background": "#414559",
                "modal.background": "#292c3c",
                "tooltip.background": "#414559",
                "text.primary": "#c6d0f5",
            },
        ),
        (
            "catppuccin-latte",
            {
                "surface.default": "#e7e9ef",
                "surface.inset": "#ccd0da",
                "surface.raised": "#bcc0cc",
                "surface.hover": "#acb0be",
                "menu.background": "#eff1f5",
                "modal.background": "#eff1f5",
                "tooltip.background": "#e6e9ef",
                "text.primary": "#4c4f69",
            },
        ),
    ],
)
def test_catppuccin_palette_preserves_its_named_surface_hierarchy(
    theme_id: str,
    expected: dict[str, str],
) -> None:
    theme = load_theme_catalog(bundled_theme_directory()).get(theme_id)

    rendered = render_theme(theme)

    assert {key: rendered.paint(key).css for key in expected} == expected


def test_seeding_happens_once_so_deleted_theme_files_stay_deleted(tmp_path) -> None:
    theme_dir = tmp_path / "themes"

    install_bundled_theme_files(theme_dir)
    (theme_dir / "catppuccin-mocha.json").unlink()
    install_bundled_theme_files(theme_dir)

    assert "catppuccin-mocha" not in load_theme_catalog(theme_dir).themes


def test_catalog_normalizes_deleted_or_wrongly_typed_selections() -> None:
    settings = AppSettings(
        theme_mode="auto",
        light_theme="catppuccin-mocha",
        dark_theme="removed-theme",
    )

    changed = load_theme_catalog().normalize_settings(settings)

    assert changed is True
    assert settings.light_theme == "light"
    assert settings.dark_theme == "dark"
    assert settings.theme == "system"
