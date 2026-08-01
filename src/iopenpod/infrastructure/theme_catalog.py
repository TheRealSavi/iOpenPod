"""File-backed theme discovery and semantic color resolution.

Theme files intentionally contain opaque, semantic ``#RRGGBB`` values only.
Transparency, interaction states, and contrast treatment are application
behaviour, so they stay consistent across every community-authored theme.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from iopenpod.resources import resource_path

from .settings_paths import get_settings_path

if TYPE_CHECKING:
    from .settings_schema import AppSettings

logger = logging.getLogger(__name__)

ThemeType = Literal["light", "dark"]

# These names are the stable, documented theme-authoring interface. The
# renderer derives CSS alpha variants and framework-specific RGB tuples from
# them so widget code does not need to understand a theme file.
THEME_COLOR_NAMES = (
    "accent",
    "accent_light",
    "background",
    "background_alt",
    "surface",
    "surface_alt",
    "surface_raised",
    "surface_hover",
    "surface_active",
    "menu_background",
    "dialog_background",
    "tooltip_background",
    "text_primary",
    "text_secondary",
    "text_tertiary",
    "text_disabled",
    "border",
    "border_subtle",
    "gridline",
    "danger",
    "success",
    "warning",
    "info",
    "star",
    "sync_cyan",
    "sync_purple",
    "sync_magenta",
    "sync_orange",
    "sync_freed",
    "playlist_smart",
    "playlist_podcast",
    "playlist_master",
    "playlist_regular",
)
_THEME_COLOR_SET = frozenset(THEME_COLOR_NAMES)
# These are the compact, community-authored foundation palette. Every other
# documented role is an optional opaque override with a Theme Renderer recipe
# behind it, so an application feature never forces every theme to grow.
_REQUIRED_THEME_COLOR_SET = frozenset(
    {
        "accent",
        "background",
        "background_alt",
        "surface",
        "surface_raised",
        "text_primary",
        "text_secondary",
        "text_tertiary",
        "text_disabled",
        "border",
        "danger",
        "success",
        "warning",
        "info",
    }
)
_THEME_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ThemeValidationError(ValueError):
    """Raised when a theme file does not match the public theme format."""


@dataclass(frozen=True)
class ThemeDefinition:
    """A validated theme as written by a user or bundled with the app."""

    id: str
    name: str
    type: ThemeType
    colors: Mapping[str, str]
    high_contrast: Mapping[str, str]
    built_in: bool = False


@dataclass(frozen=True)
class ThemeCatalog:
    """All themes available to the current app settings directory."""

    themes: Mapping[str, ThemeDefinition]
    directory: Path

    def get(self, theme_id: str) -> ThemeDefinition:
        """Return ``theme_id``, falling back to the permanent dark default."""

        return self.themes.get(theme_id, self.themes["dark"])

    def available(self, theme_type: ThemeType) -> tuple[ThemeDefinition, ...]:
        """Return menu-ready themes of one appearance type."""

        matches = [theme for theme in self.themes.values() if theme.type == theme_type]
        return tuple(
            sorted(
                matches,
                key=lambda theme: (not theme.built_in, theme.name.casefold()),
            )
        )

    def contains(self, theme_id: str, theme_type: ThemeType) -> bool:
        theme = self.themes.get(theme_id)
        return theme is not None and theme.type == theme_type

    def normalize_settings(self, settings: AppSettings) -> bool:
        """Replace unavailable or wrongly typed selections with safe defaults.

        The return value indicates that callers should persist the corrected
        preferences. Both selections are checked even in Auto mode, so a
        removed theme never remains latent in the settings file.
        """

        changed = False
        if not self.contains(settings.light_theme, "light"):
            settings.light_theme = "light"
            changed = True
        if not self.contains(settings.dark_theme, "dark"):
            settings.dark_theme = "dark"
            changed = True

        expected_legacy = "system" if settings.theme_mode == "auto" else settings.light_theme if settings.theme_mode == "light" else settings.dark_theme
        if settings.theme != expected_legacy:
            settings.theme = expected_legacy
            changed = True
        return changed


def theme_directory(settings_path: str | Path | None = None) -> Path:
    """Return the writable directory that users manage theme files in."""

    path = Path(settings_path) if settings_path is not None else Path(get_settings_path())
    return path.parent / "themes"


def bundled_theme_directory() -> Path:
    """Return the packaged JSON templates used to seed a new theme directory."""

    return resource_path("themes")


def install_bundled_theme_files(directory: Path | None = None) -> Path:
    """Seed Catppuccin files on first launch without restoring deleted themes.

    The directory itself is the first-launch marker: after it exists, this
    function never recreates an individual file. A user may therefore remove a
    supplied or community theme and the next launch will safely fall back.
    """

    target = directory or theme_directory()
    if target.exists():
        return target

    try:
        target.mkdir(parents=True, exist_ok=False)
        for source in sorted(bundled_theme_directory().glob("*.json")):
            shutil.copyfile(source, target / source.name)
    except OSError:
        logger.warning("Could not create theme directory %s", target, exc_info=True)
    return target


def load_theme_catalog(
    directory: Path | None = None,
    *,
    seed_bundled: bool = False,
) -> ThemeCatalog:
    """Load built-in defaults plus valid user-managed JSON files.

    Invalid files are ignored rather than preventing application startup. The
    built-in ``dark`` and ``light`` themes never come from disk and cannot be
    shadowed by a user file.
    """

    target = directory or theme_directory()
    if seed_bundled:
        target = install_bundled_theme_files(target)

    themes: dict[str, ThemeDefinition] = dict(_BUILT_IN_THEMES)
    if not target.is_dir():
        return ThemeCatalog(themes=themes, directory=target)

    for path in sorted(target.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            theme = _load_theme_file(path)
        except ThemeValidationError as exc:
            logger.warning("Ignoring invalid theme file %s: %s", path, exc)
            continue
        except OSError:
            logger.warning("Could not read theme file %s", path, exc_info=True)
            continue

        if theme.id in _BUILT_IN_THEMES:
            logger.warning("Ignoring %s: built-in theme IDs cannot be overridden", path)
            continue
        themes[theme.id] = theme

    return ThemeCatalog(themes=themes, directory=target)


def _load_theme_file(path: Path) -> ThemeDefinition:
    if not _THEME_ID_RE.fullmatch(path.stem):
        raise ThemeValidationError("filename must be a portable theme identifier")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThemeValidationError("not valid JSON") from exc

    if not isinstance(raw, dict):
        raise ThemeValidationError("top-level value must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ThemeValidationError("'name' must be a non-empty string")
    theme_type = raw.get("type")
    if theme_type not in ("light", "dark"):
        raise ThemeValidationError("'type' must be 'light' or 'dark'")
    colors = _validated_colors(raw.get("colors"), required=True)
    high_contrast = _validated_colors(raw.get("high_contrast", {}), required=False)
    return ThemeDefinition(
        id=path.stem,
        name=name.strip(),
        type=theme_type,
        colors=colors,
        high_contrast=high_contrast,
    )


def _validated_colors(raw: object, *, required: bool) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ThemeValidationError("'colors' must be an object")
    invalid_names = set(raw) - _THEME_COLOR_SET
    if invalid_names:
        invalid = ", ".join(sorted(map(str, invalid_names)))
        raise ThemeValidationError(f"unknown color name(s): {invalid}")
    missing = _REQUIRED_THEME_COLOR_SET - set(raw)
    if required and missing:
        raise ThemeValidationError("missing required color name(s): " + ", ".join(sorted(missing)))

    colors: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
            raise ThemeValidationError(f"'{name}' must be a #RGB or #RRGGBB value")
        colors[name] = _normalize_hex(value)
    return colors


def _normalize_hex(value: str) -> str:
    value = value.lower()
    if len(value) == 4:
        return "#" + "".join(channel * 2 for channel in value[1:])
    return value


_BUILT_IN_THEMES: dict[str, ThemeDefinition] = {
    "dark": ThemeDefinition(
        id="dark",
        name="Dark",
        type="dark",
        built_in=True,
        colors={
            "accent": "#409cff",
            "accent_light": "#60b0ff",
            "background": "#1a1a2e",
            "background_alt": "#1e1e32",
            "surface": "#212135",
            "surface_alt": "#252538",
            "surface_raised": "#2a2a3d",
            "surface_hover": "#303042",
            "surface_active": "#39394b",
            "menu_background": "#2a2a40",
            "dialog_background": "#222233",
            "tooltip_background": "#2a2d3a",
            "text_primary": "#e9e9eb",
            "text_secondary": "#a1a1a9",
            "text_tertiary": "#74747f",
            "text_disabled": "#50505f",
            "border": "#353546",
            "border_subtle": "#27273a",
            "gridline": "#252538",
            "danger": "#ff6b6b",
            "success": "#51cf66",
            "warning": "#fcc419",
            "info": "#74c0fc",
            "star": "#ffc857",
            "sync_cyan": "#66d9e8",
            "sync_purple": "#b197fc",
            "sync_magenta": "#f06595",
            "sync_orange": "#ff922b",
            "sync_freed": "#66d9c2",
            "playlist_smart": "#805ad5",
            "playlist_podcast": "#2ea043",
            "playlist_master": "#646478",
            "playlist_regular": "#409cff",
        },
        high_contrast={},
    ),
    "light": ThemeDefinition(
        id="light",
        name="Light",
        type="light",
        built_in=True,
        colors={
            "accent": "#0a6fdb",
            "accent_light": "#3d8de5",
            "background": "#f0f0f5",
            "background_alt": "#e8e8f0",
            "surface": "#e8e8ed",
            "surface_alt": "#e3e3e8",
            "surface_raised": "#dddde2",
            "surface_hover": "#d8d8dd",
            "surface_active": "#d2d2d6",
            "menu_background": "#ffffff",
            "dialog_background": "#ffffff",
            "tooltip_background": "#f5f5fa",
            "text_primary": "#212122",
            "text_secondary": "#6c6c6e",
            "text_tertiary": "#929295",
            "text_disabled": "#c1c1c5",
            "border": "#d9d9de",
            "border_subtle": "#e1e1e6",
            "gridline": "#e5e5ea",
            "danger": "#d9363e",
            "success": "#2b8a3e",
            "warning": "#e07700",
            "info": "#1c7ed6",
            "star": "#e6a800",
            "sync_cyan": "#0c8599",
            "sync_purple": "#7048e8",
            "sync_magenta": "#c2255c",
            "sync_orange": "#d9480f",
            "sync_freed": "#09a389",
            "playlist_smart": "#7248c8",
            "playlist_podcast": "#268737",
            "playlist_master": "#5a5a6e",
            "playlist_regular": "#0a6fdb",
        },
        high_contrast={},
    ),
}
