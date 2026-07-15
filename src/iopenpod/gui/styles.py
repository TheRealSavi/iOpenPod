"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.
"""

from __future__ import annotations

import colorsys
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QProxyStyle,
    QStyle,
    QStyleOptionComplex,
    QStyleOptionSlider,
    QTabBar,
)

from iopenpod.application.device_identity import resolve_ipod_image_color

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QWidget

# ── Cross-platform font ─────────────────────────────────────────────────────

if sys.platform == "darwin":
    FONT_FAMILY = ".AppleSystemUIFont"
    MONO_FONT_FAMILY = "Menlo"
    _CSS_FONT_STACK = '".AppleSystemUIFont", "Helvetica Neue"'
elif sys.platform == "win32":
    FONT_FAMILY = "Segoe UI"
    MONO_FONT_FAMILY = "Consolas"
    _CSS_FONT_STACK = '"Segoe UI"'
else:
    FONT_FAMILY = "Noto Sans"
    MONO_FONT_FAMILY = "Noto Sans Mono"
    _CSS_FONT_STACK = (
        '"Noto Sans", "Noto Sans Symbols 2", "Noto Emoji",'
        ' "Ubuntu", "DejaVu Sans"'
    )

# ── Theme palettes ───────────────────────────────────────────────────────────
# Each palette is a dict mapping attribute name → color string.
# Colors.apply_theme() copies the selected palette onto class attributes.
#
# Token semantics (applies to all palettes):
#   BG_DARK / BG_MID       — window background gradient stops
#   SURFACE                — subtle card/panel tint (semi-transparent)
#   SURFACE_ALT            — input field backgrounds; inset areas
#   SURFACE_RAISED         — raised elements: buttons, chips
#   SURFACE_HOVER          — hover state for interactive surfaces
#   SURFACE_ACTIVE         — pressed / active state
#   TEXT_PRIMARY/SECONDARY/TERTIARY/DISABLED — text hierarchy
#   BORDER / BORDER_SUBTLE — dividers, outlines; BORDER_SUBTLE is hairlines
#   BORDER_FOCUS           — focus rings on inputs
#   SELECTION              — row/item highlight background
#   SYNC_FREED             — "freed storage" teal in the storage bar legend

# ── Built-in dark ────────────────────────────────────────────────────────────
_DARK_PALETTE = dict(
    ACCENT="#409cff", ACCENT_LIGHT="#60b0ff",
    ACCENT_DIM="rgba(64,156,255,80)", ACCENT_HOVER="rgba(64,156,255,120)",
    ACCENT_PRESS="rgba(64,156,255,60)", ACCENT_BORDER="rgba(64,156,255,100)",
    ACCENT_MUTED="rgba(64,156,255,35)",
    ACCENT_SOLID="rgba(64,156,255,200)", ACCENT_SOLID_PRESS="rgba(64,156,255,160)",
    ACCENT_DARK="rgba(40,100,200,100)", ACCENT_DARK_DIM="rgba(40,100,180,60)",
    BG_DARK="#1a1a2e", BG_MID="#1e1e32",
    SURFACE="rgba(255,255,255,8)", SURFACE_ALT="rgba(255,255,255,12)",
    SURFACE_RAISED="rgba(255,255,255,18)", SURFACE_HOVER="rgba(255,255,255,25)",
    SURFACE_ACTIVE="rgba(255,255,255,35)",
    MENU_BG="#2a2a40",
    TEXT_PRIMARY="rgba(255,255,255,230)", TEXT_SECONDARY="rgba(255,255,255,150)",
    TEXT_TERTIARY="rgba(255,255,255,100)", TEXT_DISABLED="rgba(255,255,255,60)",
    BORDER="rgba(255,255,255,30)", BORDER_SUBTLE="rgba(255,255,255,15)",
    BORDER_FOCUS="rgba(64,156,255,150)",
    DIALOG_BG="#222233", TOOLTIP_BG="#2a2d3a", DROPDOWN_BG="#2a2d3a",
    GRIDLINE="rgba(255,255,255,12)", SELECTION="rgba(64,156,255,90)",
    STAR="#ffc857",
    DANGER="#ff6b6b", DANGER_DIM="rgba(255,100,100,30)", DANGER_HOVER="rgba(255,100,100,50)",
    DANGER_BORDER="rgba(220,60,60,80)",
    SUCCESS="#51cf66", SUCCESS_DIM="rgba(80,180,80,40)", SUCCESS_HOVER="rgba(80,180,80,60)",
    SUCCESS_BORDER="rgba(80,180,80,80)",
    WARNING="#fcc419", INFO="#74c0fc",
    OVERLAY="rgba(30,30,38,220)",
    SHADOW_LIGHT="rgba(0,0,0,25)", SHADOW="rgba(0,0,0,40)", SHADOW_DEEP="rgba(0,0,0,60)",
    TEXT_ON_ACCENT="#ffffff",
    SYNC_CYAN="#66d9e8", SYNC_PURPLE="#b197fc",
    SYNC_MAGENTA="#f06595", SYNC_ORANGE="#ff922b",
    SYNC_FREED="#66d9c2",
)

# ── Built-in light ───────────────────────────────────────────────────────────
_LIGHT_PALETTE = dict(
    ACCENT="#0a6fdb", ACCENT_LIGHT="#3d8de5",
    ACCENT_DIM="rgba(10,111,219,60)", ACCENT_HOVER="rgba(10,111,219,100)",
    ACCENT_PRESS="rgba(10,111,219,45)", ACCENT_BORDER="rgba(10,111,219,80)",
    ACCENT_MUTED="rgba(10,111,219,18)",
    ACCENT_SOLID="rgba(10,111,219,180)", ACCENT_SOLID_PRESS="rgba(10,111,219,140)",
    ACCENT_DARK="rgba(10,80,160,80)", ACCENT_DARK_DIM="rgba(10,80,160,40)",
    BG_DARK="#f0f0f5", BG_MID="#e8e8f0",
    SURFACE="rgba(0,0,0,8)", SURFACE_ALT="rgba(0,0,0,14)",
    SURFACE_RAISED="rgba(0,0,0,20)", SURFACE_HOVER="rgba(0,0,0,26)",
    SURFACE_ACTIVE="rgba(0,0,0,32)",
    MENU_BG="#ffffff",
    TEXT_PRIMARY="rgba(0,0,0,220)", TEXT_SECONDARY="rgba(0,0,0,140)",
    TEXT_TERTIARY="rgba(0,0,0,100)", TEXT_DISABLED="rgba(0,0,0,50)",
    BORDER="rgba(0,0,0,24)", BORDER_SUBTLE="rgba(0,0,0,16)",
    BORDER_FOCUS="rgba(10,111,219,130)",
    DIALOG_BG="#ffffff", TOOLTIP_BG="#f5f5fa", DROPDOWN_BG="#ffffff",
    GRIDLINE="rgba(0,0,0,12)", SELECTION="rgba(10,111,219,70)",
    STAR="#e6a800",
    DANGER="#d9363e", DANGER_DIM="rgba(217,54,62,20)", DANGER_HOVER="rgba(217,54,62,35)",
    DANGER_BORDER="rgba(217,54,62,60)",
    SUCCESS="#2b8a3e", SUCCESS_DIM="rgba(43,138,62,25)", SUCCESS_HOVER="rgba(43,138,62,40)",
    SUCCESS_BORDER="rgba(43,138,62,60)",
    WARNING="#e07700", INFO="#1c7ed6",
    OVERLAY="rgba(240,240,245,230)",
    SHADOW_LIGHT="rgba(0,0,0,14)", SHADOW="rgba(0,0,0,22)", SHADOW_DEEP="rgba(0,0,0,32)",
    TEXT_ON_ACCENT="#ffffff",
    SYNC_CYAN="#0c8599", SYNC_PURPLE="#7048e8",
    SYNC_MAGENTA="#c2255c", SYNC_ORANGE="#d9480f",
    SYNC_FREED="#09a389",
)

# ── High-contrast overlays: merged on top of dark or light palette ───────────
_HC_DARK_OVERRIDES = dict(
    TEXT_PRIMARY="rgba(255,255,255,255)", TEXT_SECONDARY="rgba(255,255,255,200)",
    TEXT_TERTIARY="rgba(255,255,255,160)", TEXT_DISABLED="rgba(255,255,255,100)",
    BORDER="rgba(255,255,255,60)", BORDER_SUBTLE="rgba(255,255,255,35)",
    BORDER_FOCUS="rgba(64,156,255,220)",
    GRIDLINE="rgba(255,255,255,25)",
    DANGER="#ff8787", SUCCESS="#69db7c", WARNING="#ffe066", INFO="#91d5ff",
    DANGER_BORDER="rgba(255,135,135,120)", SUCCESS_BORDER="rgba(105,219,124,120)",
)

_HC_LIGHT_OVERRIDES = dict(
    TEXT_PRIMARY="rgba(0,0,0,255)", TEXT_SECONDARY="rgba(0,0,0,200)",
    TEXT_TERTIARY="rgba(0,0,0,160)", TEXT_DISABLED="rgba(0,0,0,100)",
    BORDER="rgba(0,0,0,40)", BORDER_SUBTLE="rgba(0,0,0,25)",
    BORDER_FOCUS="rgba(10,111,219,220)",
    GRIDLINE="rgba(0,0,0,18)",
    DANGER="#a91e25", SUCCESS="#1a6b2d", WARNING="#b85c00", INFO="#1062b0",
    DANGER_BORDER="rgba(169,30,37,110)", SUCCESS_BORDER="rgba(26,107,45,110)",
)

# ── Catppuccin Mocha (darkest) ────────────────────────────────────────────────
# https://catppuccin.com/palette — Mocha flavor
_CATPPUCCIN_MOCHA = dict(
    ACCENT="#89b4fa", ACCENT_LIGHT="#b4befe",          # Blue / Lavender
    ACCENT_DIM="rgba(137,180,250,70)", ACCENT_HOVER="rgba(137,180,250,110)",
    ACCENT_PRESS="rgba(137,180,250,55)", ACCENT_BORDER="rgba(137,180,250,90)",
    ACCENT_MUTED="rgba(137,180,250,25)",
    ACCENT_SOLID="rgba(137,180,250,200)", ACCENT_SOLID_PRESS="rgba(137,180,250,160)",
    ACCENT_DARK="rgba(80,120,200,90)", ACCENT_DARK_DIM="rgba(80,120,200,55)",
    BG_DARK="#1e1e2e", BG_MID="#181825",               # Base / Mantle
    SURFACE="rgba(49,50,68,60)",                        # Surface0 tinted
    SURFACE_ALT="#313244",                              # Surface0
    SURFACE_RAISED="#45475a",                           # Surface1
    SURFACE_HOVER="#585b70",                            # Surface2
    SURFACE_ACTIVE="rgba(88,91,112,220)",               # Surface2 opaque
    MENU_BG="#313244",
    TEXT_PRIMARY="#cdd6f4",                             # Text
    TEXT_SECONDARY="#bac2de",                           # Subtext1
    TEXT_TERTIARY="#a6adc8",                            # Subtext0
    TEXT_DISABLED="#6c7086",                            # Overlay0
    BORDER="rgba(69,71,90,200)",                        # Surface1
    BORDER_SUBTLE="rgba(49,50,68,200)",                 # Surface0
    BORDER_FOCUS="rgba(137,180,250,160)",
    DIALOG_BG="#181825",                                # Mantle
    TOOLTIP_BG="#313244",                               # Surface0
    DROPDOWN_BG="#313244",
    GRIDLINE="rgba(49,50,68,200)",
    SELECTION="rgba(137,180,250,80)",
    STAR="#f9e2af",                                     # Yellow
    DANGER="#f38ba8", DANGER_DIM="rgba(243,139,168,25)", DANGER_HOVER="rgba(243,139,168,45)",
    DANGER_BORDER="rgba(243,139,168,80)",               # Red
    SUCCESS="#a6e3a1", SUCCESS_DIM="rgba(166,227,161,25)", SUCCESS_HOVER="rgba(166,227,161,45)",
    SUCCESS_BORDER="rgba(166,227,161,80)",              # Green
    WARNING="#f9e2af", INFO="#89dceb",                  # Yellow / Sky
    OVERLAY="rgba(30,30,46,225)",
    SHADOW_LIGHT="rgba(17,17,27,35)", SHADOW="rgba(17,17,27,55)", SHADOW_DEEP="rgba(17,17,27,75)",
    TEXT_ON_ACCENT="#1e1e2e",                           # Base (dark on pastel blue)
    SYNC_CYAN="#94e2d5", SYNC_PURPLE="#cba6f7",        # Teal / Mauve
    SYNC_MAGENTA="#f5c2e7", SYNC_ORANGE="#fab387",     # Pink / Peach
    SYNC_FREED="#94e2d5",
)

# ── Catppuccin Macchiato ──────────────────────────────────────────────────────
_CATPPUCCIN_MACCHIATO = dict(
    ACCENT="#8aadf4", ACCENT_LIGHT="#b7bdf8",          # Blue / Lavender
    ACCENT_DIM="rgba(138,173,244,70)", ACCENT_HOVER="rgba(138,173,244,110)",
    ACCENT_PRESS="rgba(138,173,244,55)", ACCENT_BORDER="rgba(138,173,244,90)",
    ACCENT_MUTED="rgba(138,173,244,25)",
    ACCENT_SOLID="rgba(138,173,244,200)", ACCENT_SOLID_PRESS="rgba(138,173,244,160)",
    ACCENT_DARK="rgba(80,120,200,90)", ACCENT_DARK_DIM="rgba(80,120,200,55)",
    BG_DARK="#24273a", BG_MID="#1e2030",               # Base / Mantle
    SURFACE="rgba(54,58,79,60)",
    SURFACE_ALT="#363a4f",                              # Surface0
    SURFACE_RAISED="#494d64",                           # Surface1
    SURFACE_HOVER="#5b6078",                            # Surface2
    SURFACE_ACTIVE="rgba(91,96,120,220)",
    MENU_BG="#363a4f",
    TEXT_PRIMARY="#cad3f5",
    TEXT_SECONDARY="#b8c0e0",
    TEXT_TERTIARY="#a5adcb",
    TEXT_DISABLED="#6e738d",                            # Overlay0
    BORDER="rgba(73,77,100,200)",
    BORDER_SUBTLE="rgba(54,58,79,200)",
    BORDER_FOCUS="rgba(138,173,244,160)",
    DIALOG_BG="#1e2030",
    TOOLTIP_BG="#363a4f",
    DROPDOWN_BG="#363a4f",
    GRIDLINE="rgba(54,58,79,200)",
    SELECTION="rgba(138,173,244,80)",
    STAR="#eed49f",
    DANGER="#ed8796", DANGER_DIM="rgba(237,135,150,25)", DANGER_HOVER="rgba(237,135,150,45)",
    DANGER_BORDER="rgba(237,135,150,80)",
    SUCCESS="#a6da95", SUCCESS_DIM="rgba(166,218,149,25)", SUCCESS_HOVER="rgba(166,218,149,45)",
    SUCCESS_BORDER="rgba(166,218,149,80)",
    WARNING="#eed49f", INFO="#91d7e3",                  # Yellow / Sky
    OVERLAY="rgba(36,39,58,225)",
    SHADOW_LIGHT="rgba(24,25,38,35)", SHADOW="rgba(24,25,38,55)", SHADOW_DEEP="rgba(24,25,38,75)",
    TEXT_ON_ACCENT="#24273a",
    SYNC_CYAN="#8bd5ca", SYNC_PURPLE="#c6a0f6",
    SYNC_MAGENTA="#f5bde6", SYNC_ORANGE="#f5a97f",
    SYNC_FREED="#8bd5ca",
)

# ── Catppuccin Frappé ─────────────────────────────────────────────────────────
_CATPPUCCIN_FRAPPE = dict(
    ACCENT="#8caaee", ACCENT_LIGHT="#babbf1",          # Blue / Lavender
    ACCENT_DIM="rgba(140,170,238,70)", ACCENT_HOVER="rgba(140,170,238,110)",
    ACCENT_PRESS="rgba(140,170,238,55)", ACCENT_BORDER="rgba(140,170,238,90)",
    ACCENT_MUTED="rgba(140,170,238,25)",
    ACCENT_SOLID="rgba(140,170,238,200)", ACCENT_SOLID_PRESS="rgba(140,170,238,160)",
    ACCENT_DARK="rgba(80,115,190,90)", ACCENT_DARK_DIM="rgba(80,115,190,55)",
    BG_DARK="#303446", BG_MID="#292c3c",               # Base / Mantle
    SURFACE="rgba(65,69,89,60)",
    SURFACE_ALT="#414559",                              # Surface0
    SURFACE_RAISED="#51576d",                           # Surface1
    SURFACE_HOVER="#626880",                            # Surface2
    SURFACE_ACTIVE="rgba(98,104,128,220)",
    MENU_BG="#414559",
    TEXT_PRIMARY="#c6d0f5",
    TEXT_SECONDARY="#b5bfe2",
    TEXT_TERTIARY="#a5adce",
    TEXT_DISABLED="#737994",                            # Overlay0
    BORDER="rgba(81,87,109,200)",
    BORDER_SUBTLE="rgba(65,69,89,200)",
    BORDER_FOCUS="rgba(140,170,238,160)",
    DIALOG_BG="#292c3c",
    TOOLTIP_BG="#414559",
    DROPDOWN_BG="#414559",
    GRIDLINE="rgba(65,69,89,200)",
    SELECTION="rgba(140,170,238,80)",
    STAR="#e5c890",
    DANGER="#e78284", DANGER_DIM="rgba(231,130,132,25)", DANGER_HOVER="rgba(231,130,132,45)",
    DANGER_BORDER="rgba(231,130,132,80)",
    SUCCESS="#a6d189", SUCCESS_DIM="rgba(166,209,137,25)", SUCCESS_HOVER="rgba(166,209,137,45)",
    SUCCESS_BORDER="rgba(166,209,137,80)",
    WARNING="#e5c890", INFO="#99d1db",
    OVERLAY="rgba(48,52,70,225)",
    SHADOW_LIGHT="rgba(35,38,52,35)", SHADOW="rgba(35,38,52,55)", SHADOW_DEEP="rgba(35,38,52,75)",
    TEXT_ON_ACCENT="#303446",
    SYNC_CYAN="#81c8be", SYNC_PURPLE="#ca9ee6",
    SYNC_MAGENTA="#f4b8e4", SYNC_ORANGE="#ef9f76",
    SYNC_FREED="#81c8be",
)

# ── Catppuccin Latte (light) ──────────────────────────────────────────────────
_CATPPUCCIN_LATTE = dict(
    ACCENT="#1e66f5", ACCENT_LIGHT="#7287fd",          # Blue / Lavender
    ACCENT_DIM="rgba(30,102,245,60)", ACCENT_HOVER="rgba(30,102,245,100)",
    ACCENT_PRESS="rgba(30,102,245,45)", ACCENT_BORDER="rgba(30,102,245,80)",
    ACCENT_MUTED="rgba(30,102,245,18)",
    ACCENT_SOLID="rgba(30,102,245,180)", ACCENT_SOLID_PRESS="rgba(30,102,245,140)",
    ACCENT_DARK="rgba(20,80,200,80)", ACCENT_DARK_DIM="rgba(20,80,200,50)",
    BG_DARK="#eff1f5", BG_MID="#e6e9ef",               # Base / Mantle
    SURFACE="rgba(204,208,218,60)",
    SURFACE_ALT="#ccd0da",                              # Surface0
    SURFACE_RAISED="#bcc0cc",                           # Surface1
    SURFACE_HOVER="#acb0be",                            # Surface2
    SURFACE_ACTIVE="rgba(172,176,190,220)",
    MENU_BG="#eff1f5",
    TEXT_PRIMARY="#4c4f69",                             # Text
    TEXT_SECONDARY="#5c5f77",                           # Subtext1
    TEXT_TERTIARY="#6c6f85",                            # Subtext0
    TEXT_DISABLED="#9ca0b0",                            # Overlay0
    BORDER="rgba(172,176,190,200)",                     # Surface2
    BORDER_SUBTLE="rgba(204,208,218,200)",              # Surface0
    BORDER_FOCUS="rgba(30,102,245,130)",
    DIALOG_BG="#eff1f5",
    TOOLTIP_BG="#e6e9ef",
    DROPDOWN_BG="#eff1f5",
    GRIDLINE="rgba(188,192,204,200)",
    SELECTION="rgba(30,102,245,70)",
    STAR="#df8e1d",                                     # Yellow
    DANGER="#d20f39", DANGER_DIM="rgba(210,15,57,20)", DANGER_HOVER="rgba(210,15,57,35)",
    DANGER_BORDER="rgba(210,15,57,60)",                 # Red
    SUCCESS="#40a02b", SUCCESS_DIM="rgba(64,160,43,25)", SUCCESS_HOVER="rgba(64,160,43,40)",
    SUCCESS_BORDER="rgba(64,160,43,60)",               # Green
    WARNING="#df8e1d", INFO="#04a5e5",                  # Yellow / Sky
    OVERLAY="rgba(239,241,245,230)",
    SHADOW_LIGHT="rgba(0,0,0,12)", SHADOW="rgba(0,0,0,20)", SHADOW_DEEP="rgba(0,0,0,30)",
    TEXT_ON_ACCENT="#eff1f5",                           # Base (light on dark blue)
    SYNC_CYAN="#179299", SYNC_PURPLE="#8839ef",        # Teal / Mauve
    SYNC_MAGENTA="#ea76cb", SYNC_ORANGE="#fe640b",     # Pink / Peach
    SYNC_FREED="#179299",
)

# Registry: theme-id → (palette_dict, is_dark)
_THEME_REGISTRY: dict[str, tuple[dict, bool]] = {
    "dark": (_DARK_PALETTE, True),
    "light": (_LIGHT_PALETTE, False),
    "catppuccin-mocha": (_CATPPUCCIN_MOCHA, True),
    "catppuccin-macchiato": (_CATPPUCCIN_MACCHIATO, True),
    "catppuccin-frappe": (_CATPPUCCIN_FRAPPE, True),
    "catppuccin-latte": (_CATPPUCCIN_LATTE, False),
}

# Playlist / category colors per theme (r,g,b tuples used by TrackListTitleBar)
_PLAYLIST_COLORS: dict[str, dict] = {
    "dark": dict(
        PLAYLIST_SMART=(128, 90, 213), PLAYLIST_PODCAST=(46, 160, 67),
        PLAYLIST_MASTER=(100, 100, 120), PLAYLIST_REGULAR=(64, 156, 255),
    ),
    "light": dict(
        PLAYLIST_SMART=(114, 72, 200), PLAYLIST_PODCAST=(38, 135, 55),
        PLAYLIST_MASTER=(90, 90, 110), PLAYLIST_REGULAR=(10, 111, 219),
    ),
    "catppuccin-mocha": dict(
        PLAYLIST_SMART=(203, 166, 247), PLAYLIST_PODCAST=(166, 227, 161),
        PLAYLIST_MASTER=(88, 91, 112), PLAYLIST_REGULAR=(137, 180, 250),
    ),
    "catppuccin-macchiato": dict(
        PLAYLIST_SMART=(198, 160, 246), PLAYLIST_PODCAST=(166, 218, 149),
        PLAYLIST_MASTER=(91, 96, 120), PLAYLIST_REGULAR=(138, 173, 244),
    ),
    "catppuccin-frappe": dict(
        PLAYLIST_SMART=(202, 158, 230), PLAYLIST_PODCAST=(166, 209, 137),
        PLAYLIST_MASTER=(98, 104, 128), PLAYLIST_REGULAR=(140, 170, 238),
    ),
    "catppuccin-latte": dict(
        PLAYLIST_SMART=(136, 57, 239), PLAYLIST_PODCAST=(64, 160, 43),
        PLAYLIST_MASTER=(140, 143, 161), PLAYLIST_REGULAR=(30, 102, 245),
    ),
}


class Colors:
    """Named colors used throughout the app.

    All attributes start with the dark palette.  Call ``apply_theme()``
    after QApplication is created to switch palettes based on user settings.
    """

    # Current resolved mode (set by apply_theme)
    _active_mode: str = "dark"
    _active_hc: bool = False

    # Initialise with dark palette defaults
    ACCENT: str = _DARK_PALETTE["ACCENT"]
    ACCENT_LIGHT: str = _DARK_PALETTE["ACCENT_LIGHT"]
    ACCENT_DIM = _DARK_PALETTE["ACCENT_DIM"]
    ACCENT_HOVER = _DARK_PALETTE["ACCENT_HOVER"]
    ACCENT_PRESS = _DARK_PALETTE["ACCENT_PRESS"]
    ACCENT_BORDER = _DARK_PALETTE["ACCENT_BORDER"]
    BG_DARK = _DARK_PALETTE["BG_DARK"]
    BG_MID = _DARK_PALETTE["BG_MID"]
    SURFACE = _DARK_PALETTE["SURFACE"]
    SURFACE_ALT = _DARK_PALETTE["SURFACE_ALT"]
    SURFACE_RAISED = _DARK_PALETTE["SURFACE_RAISED"]
    SURFACE_HOVER = _DARK_PALETTE["SURFACE_HOVER"]
    SURFACE_ACTIVE = _DARK_PALETTE["SURFACE_ACTIVE"]
    MENU_BG = _DARK_PALETTE["MENU_BG"]
    TEXT_PRIMARY = _DARK_PALETTE["TEXT_PRIMARY"]
    TEXT_SECONDARY = _DARK_PALETTE["TEXT_SECONDARY"]
    TEXT_TERTIARY = _DARK_PALETTE["TEXT_TERTIARY"]
    TEXT_DISABLED = _DARK_PALETTE["TEXT_DISABLED"]
    BORDER = _DARK_PALETTE["BORDER"]
    BORDER_SUBTLE = _DARK_PALETTE["BORDER_SUBTLE"]
    BORDER_FOCUS = _DARK_PALETTE["BORDER_FOCUS"]
    DIALOG_BG = _DARK_PALETTE["DIALOG_BG"]
    TOOLTIP_BG = _DARK_PALETTE["TOOLTIP_BG"]
    DROPDOWN_BG = _DARK_PALETTE["DROPDOWN_BG"]
    GRIDLINE = _DARK_PALETTE["GRIDLINE"]
    SELECTION = _DARK_PALETTE["SELECTION"]
    STAR = _DARK_PALETTE["STAR"]
    DANGER = _DARK_PALETTE["DANGER"]
    DANGER_DIM = _DARK_PALETTE["DANGER_DIM"]
    DANGER_HOVER = _DARK_PALETTE["DANGER_HOVER"]
    SUCCESS = _DARK_PALETTE["SUCCESS"]
    SUCCESS_DIM = _DARK_PALETTE["SUCCESS_DIM"]
    SUCCESS_HOVER = _DARK_PALETTE["SUCCESS_HOVER"]
    WARNING = _DARK_PALETTE["WARNING"]
    INFO = _DARK_PALETTE["INFO"]
    OVERLAY = _DARK_PALETTE["OVERLAY"]
    SHADOW_LIGHT = _DARK_PALETTE["SHADOW_LIGHT"]
    SHADOW = _DARK_PALETTE["SHADOW"]
    SHADOW_DEEP = _DARK_PALETTE["SHADOW_DEEP"]
    TEXT_ON_ACCENT = _DARK_PALETTE["TEXT_ON_ACCENT"]
    ACCENT_MUTED = _DARK_PALETTE["ACCENT_MUTED"]
    ACCENT_SOLID = _DARK_PALETTE["ACCENT_SOLID"]
    ACCENT_SOLID_PRESS = _DARK_PALETTE["ACCENT_SOLID_PRESS"]
    ACCENT_DARK = _DARK_PALETTE["ACCENT_DARK"]
    ACCENT_DARK_DIM = _DARK_PALETTE["ACCENT_DARK_DIM"]
    DANGER_BORDER = _DARK_PALETTE["DANGER_BORDER"]
    SUCCESS_BORDER = _DARK_PALETTE["SUCCESS_BORDER"]
    SYNC_CYAN = _DARK_PALETTE["SYNC_CYAN"]
    SYNC_PURPLE = _DARK_PALETTE["SYNC_PURPLE"]
    SYNC_MAGENTA = _DARK_PALETTE["SYNC_MAGENTA"]
    SYNC_ORANGE = _DARK_PALETTE["SYNC_ORANGE"]

    # Accent colors are normalized toward this contrast against the app
    # background so red, blue, gold, and artwork-derived colors read with
    # similar visual strength across themes.
    ACCENT_CONTRAST_TARGET = 3.35
    GRID_ART_CONTRAST_TARGET = 3.35

    # ── Semantic playlist / category color tuples (r, g, b) ──
    PLAYLIST_SMART: tuple[int, int, int] = (128, 90, 213)
    PLAYLIST_PODCAST: tuple[int, int, int] = (46, 160, 67)
    PLAYLIST_MASTER: tuple[int, int, int] = (100, 100, 120)
    PLAYLIST_REGULAR: tuple[int, int, int] = (64, 156, 255)

    # Sync storage legend color — theme-aware, initialised from dark palette
    SYNC_FREED = _DARK_PALETTE["SYNC_FREED"]

    # Active theme identifier (set by apply_theme)
    _active_theme: str = "dark"

    @classmethod
    def _detect_system_dark(cls) -> bool:
        """Return True if the OS is in dark mode."""
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QPalette as _QPalette
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if isinstance(app, QApplication):
                hints = app.styleHints()
                if hints is not None:
                    scheme = hints.colorScheme()
                    if scheme == Qt.ColorScheme.Dark:
                        return True
                    if scheme == Qt.ColorScheme.Light:
                        return False
                # Unknown — fall back to palette luminance
                bg = app.palette().color(_QPalette.ColorRole.Window)
                return bg.lightnessF() < 0.5
        except Exception:
            pass
        return True  # default to dark

    @classmethod
    def _detect_system_hc(cls) -> bool:
        """Return True if OS has increased-contrast / high-contrast enabled."""
        try:
            from PyQt6.QtGui import QPalette as _QPalette
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if isinstance(app, QApplication):
                pal = app.palette()
                bg = pal.color(_QPalette.ColorRole.Window)
                fg = pal.color(_QPalette.ColorRole.WindowText)
                contrast = abs(fg.lightnessF() - bg.lightnessF())
                return contrast > 0.9
        except Exception:
            pass
        return False

    @classmethod
    def apply_theme(
        cls,
        theme: str = "dark",
        high_contrast: str = "off",
        accent_color: str = "blue",
    ) -> None:
        """Resolve theme + contrast settings and update all class attributes.

        Parameters
        ----------
        theme : str
            ``"dark"``, ``"light"``, ``"system"``, or any ``"catppuccin-*"`` key.
        high_contrast : str
            ``"on"``, ``"off"``, or ``"system"`` (ignored for Catppuccin flavors)
        accent_color : str
            ``"blue"`` uses the theme default, ``"match-ipod"`` is resolved
            externally before calling, or a hex string like ``"#e34060"``.
        """
        # Resolve system theme
        if theme == "system":
            effective = "dark" if cls._detect_system_dark() else "light"
        else:
            effective = theme

        palette_entry = _THEME_REGISTRY.get(effective, _THEME_REGISTRY["dark"])
        base_palette, is_dark = palette_entry

        # Resolve contrast (ignored for Catppuccin — they have their own contrast ratios)
        if high_contrast == "system":
            hc = cls._detect_system_hc()
        else:
            hc = (high_contrast == "on")

        cls._active_mode = "dark" if is_dark else "light"
        cls._active_theme = effective
        cls._active_hc = hc

        # Build resolved palette, optionally merging HC overrides.
        # High contrast applies to all themes based on their is_dark flag,
        # including Catppuccin variants (Latte is light, others are dark).
        resolved = dict(base_palette)
        if hc:
            resolved.update(_HC_DARK_OVERRIDES if is_dark else _HC_LIGHT_OVERRIDES)

        # Apply custom accent color (skip for "blue" — use theme default)
        if accent_color and accent_color not in ("blue", "match-ipod"):
            rgb = _parse_accent_hex(accent_color)
            if rgb is not None:
                resolved.update(_accent_overrides(*rgb, is_dark))

        # Normalize every app accent, including theme defaults and iPod-matched
        # accents, so the chosen hue has a consistent contrast from the window.
        accent_rgb = _css_rgb_tuple(resolved.get("ACCENT", ""))
        bg_rgb = _css_rgb_tuple(resolved.get("BG_DARK", ""))
        if accent_rgb is not None and bg_rgb is not None:
            target = 4.5 if hc else cls.ACCENT_CONTRAST_TARGET
            accent_rgb = _normalize_rgb_for_contrast(accent_rgb, bg_rgb, target)
            resolved.update(_accent_overrides(*accent_rgb, is_dark))

        # Apply all palette values to class attributes
        for key, value in resolved.items():
            setattr(cls, key, value)

        # Apply per-theme playlist/category colors
        pc = _PLAYLIST_COLORS.get(effective, _PLAYLIST_COLORS["dark"])
        cls.PLAYLIST_SMART = pc["PLAYLIST_SMART"]
        cls.PLAYLIST_PODCAST = pc["PLAYLIST_PODCAST"]
        cls.PLAYLIST_MASTER = pc["PLAYLIST_MASTER"]
        cls.PLAYLIST_REGULAR = pc["PLAYLIST_REGULAR"]

        # If a custom accent color was applied, use it for PLAYLIST_REGULAR
        # so the default track title bar color matches the user's accent choice.
        if accent_color and accent_color not in ("blue", "match-ipod"):
            rgb = _css_rgb_tuple(cls.ACCENT)
            if rgb is not None:
                cls.PLAYLIST_REGULAR = rgb

    @classmethod
    def apply_theme_selection(
        cls,
        mode: str,
        light_theme: str,
        dark_theme: str,
        high_contrast: str = "off",
        accent_color: str = "blue",
    ) -> None:
        """Apply a palette from split light/dark appearance preferences."""

        if mode == "light":
            theme = light_theme
        elif mode == "dark":
            theme = dark_theme
        else:
            theme = dark_theme if cls._detect_system_dark() else light_theme
        cls.apply_theme(theme, high_contrast, accent_color)


# Named accent color presets (settings value → hex).
ACCENT_PRESETS: dict[str, str] = {
    "blue": "",           # empty = use theme default
    "match-ipod": "",     # resolved at runtime from device info
    "red": "#d94040",
    "orange": "#d98030",
    "gold": "#c8a840",
    "green": "#48a848",
    "teal": "#38a0a0",
    "purple": "#8040c8",
    "pink": "#d05090",
}


def resolve_accent_color(
    setting: str,
    ipod_image: str = "",
) -> str:
    """Turn an ``accent_color`` setting value into a hex string.

    Returns ``"blue"`` (meaning use theme default) when no override applies.
    """
    if setting == "blue":
        return "blue"
    if setting == "match-ipod":
        if ipod_image:
            rgb = resolve_ipod_image_color(ipod_image)
            if rgb is not None:
                # Reject white/silver and black/gray iPods — they don't work
                # as accent colors. Check saturation: achromatic colors have
                # R, G, B values very close together; colorful ones are spread out.
                r_min, r_max = min(rgb), max(rgb)
                saturation = r_max - r_min
                # Saturation < 15 indicates grayscale (white/silver/black/gray)
                if saturation < 15:
                    return "blue"  # fall back to theme default
                return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        return "blue"  # no iPod connected — fall back to default
    # Named preset
    hex_val = ACCENT_PRESETS.get(setting, "")
    if hex_val:
        return hex_val
    # Might be a raw hex from a future custom picker
    if setting.startswith("#") and len(setting) == 7:
        return setting
    return "blue"


def _parse_accent_hex(hex_str: str) -> tuple[int, int, int] | None:
    """Parse a hex color like ``'#e34060'`` into (R, G, B) or None."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            return None
    return None


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _css_rgb_tuple(css: str) -> tuple[int, int, int] | None:
    """Parse a CSS-ish color into an RGB tuple."""
    color = QColor(css)
    if color.isValid():
        return color.red(), color.green(), color.blue()

    match = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
        str(css).strip(),
    )
    if match:
        return (
            _clamp_byte(int(match.group(1))),
            _clamp_byte(int(match.group(2))),
            _clamp_byte(int(match.group(3))),
        )
    return None


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance for an RGB tuple."""
    def _linear(channel: int) -> float:
        value = channel / 255.0
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> float:
    la = _relative_luminance(a)
    lb = _relative_luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _normalize_rgb_for_contrast(
    rgb: tuple[int, int, int],
    background: tuple[int, int, int],
    target_ratio: float,
) -> tuple[int, int, int]:
    """Preserve hue/saturation while moving lightness toward target contrast."""
    target_ratio = max(1.0, float(target_ratio))
    h, lightness, saturation = colorsys.rgb_to_hls(
        rgb[0] / 255.0,
        rgb[1] / 255.0,
        rgb[2] / 255.0,
    )

    best_rgb = rgb
    best_score = (float("inf"), float("inf"))
    # Sampling is intentionally used instead of assuming perfect monotonicity:
    # HLS-to-RGB clipping and gamma contrast make edge cases a bit lumpy.
    for step in range(256):
        candidate_l = step / 255.0
        cr, cg, cb = colorsys.hls_to_rgb(h, candidate_l, saturation)
        candidate = (
            _clamp_byte(cr * 255),
            _clamp_byte(cg * 255),
            _clamp_byte(cb * 255),
        )
        ratio = _contrast_ratio(candidate, background)
        score = (abs(ratio - target_ratio), abs(candidate_l - lightness))
        if score < best_score:
            best_score = score
            best_rgb = candidate

    return best_rgb


def display_accent_rgb(
    rgb: tuple[int, int, int],
    background: str | tuple[int, int, int] | None = None,
    target_ratio: float | None = None,
) -> tuple[int, int, int]:
    """Normalize an accent/artwork RGB color for current app background."""
    if background is None:
        bg_rgb = _css_rgb_tuple(Colors.BG_DARK)
    elif isinstance(background, tuple):
        bg_rgb = background
    else:
        bg_rgb = _css_rgb_tuple(background)

    if bg_rgb is None:
        bg_rgb = (26, 26, 46) if Colors._active_mode == "dark" else (240, 240, 245)

    target = target_ratio
    if target is None:
        target = Colors.GRID_ART_CONTRAST_TARGET
    if Colors._active_hc:
        target = max(float(target), 4.5)
    return _normalize_rgb_for_contrast(rgb, bg_rgb, float(target))


def current_accent_rgb() -> tuple[int, int, int]:
    """Return the currently active app accent as an RGB tuple."""
    return _css_rgb_tuple(Colors.ACCENT) or Colors.PLAYLIST_REGULAR


def text_rgb_for_background(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Pick black or white text, whichever contrasts more with ``rgb``."""
    white = (255, 255, 255)
    black = (18, 18, 24)
    return white if _contrast_ratio(white, rgb) >= _contrast_ratio(black, rgb) else black


def _accent_overrides(r: int, g: int, b: int, is_dark: bool) -> dict[str, str]:
    """Generate all ACCENT_* palette entries from a single (R, G, B) color.

    Produces the same set of accent keys each palette defines, with
    alpha levels matching the built-in dark/light palettes.
    """
    # Darker shade — shift toward black by ~35%
    dr, dg, db = int(r * 0.62), int(g * 0.64), int(b * 0.78)
    # Lighter shade — shift toward white by ~25%
    lr = min(255, int(r + (255 - r) * 0.25))
    lg = min(255, int(g + (255 - g) * 0.25))
    lb = min(255, int(b + (255 - b) * 0.25))

    # Choose text-on-accent based on perceived luminance
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    text_on = "#ffffff" if lum < 160 else "#1a1a2e" if is_dark else "#000000"

    if is_dark:
        return {
            "ACCENT": f"#{r:02x}{g:02x}{b:02x}",
            "ACCENT_LIGHT": f"#{lr:02x}{lg:02x}{lb:02x}",
            "ACCENT_DIM": f"rgba({r},{g},{b},80)",
            "ACCENT_HOVER": f"rgba({r},{g},{b},120)",
            "ACCENT_PRESS": f"rgba({r},{g},{b},60)",
            "ACCENT_BORDER": f"rgba({r},{g},{b},100)",
            "ACCENT_MUTED": f"rgba({r},{g},{b},35)",
            "ACCENT_SOLID": f"rgba({r},{g},{b},200)",
            "ACCENT_SOLID_PRESS": f"rgba({r},{g},{b},160)",
            "ACCENT_DARK": f"rgba({dr},{dg},{db},100)",
            "ACCENT_DARK_DIM": f"rgba({dr},{dg},{db},60)",
            "BORDER_FOCUS": f"rgba({r},{g},{b},150)",
            "SELECTION": f"rgba({r},{g},{b},90)",
            "TEXT_ON_ACCENT": text_on,
        }
    else:
        return {
            "ACCENT": f"#{r:02x}{g:02x}{b:02x}",
            "ACCENT_LIGHT": f"#{lr:02x}{lg:02x}{lb:02x}",
            "ACCENT_DIM": f"rgba({r},{g},{b},60)",
            "ACCENT_HOVER": f"rgba({r},{g},{b},100)",
            "ACCENT_PRESS": f"rgba({r},{g},{b},45)",
            "ACCENT_BORDER": f"rgba({r},{g},{b},80)",
            "ACCENT_MUTED": f"rgba({r},{g},{b},18)",
            "ACCENT_SOLID": f"rgba({r},{g},{b},180)",
            "ACCENT_SOLID_PRESS": f"rgba({r},{g},{b},140)",
            "ACCENT_DARK": f"rgba({dr},{dg},{db},80)",
            "ACCENT_DARK_DIM": f"rgba({dr},{dg},{db},40)",
            "BORDER_FOCUS": f"rgba({r},{g},{b},130)",
            "SELECTION": f"rgba({r},{g},{b},70)",
            "TEXT_ON_ACCENT": text_on,
        }


def _parse_color(css: str) -> QColor:
    """Parse a CSS color string (hex or ``rgba(r,g,b,a)``) into a QColor."""
    c = QColor(css)
    if c.isValid():
        return c
    import re
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)', css.strip())
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = int(m.group(4)) if m.group(4) else 255
        return QColor(r, g, b, a)
    return QColor("white" if Colors._active_mode == "dark" else "black")


def build_palette() -> QPalette:
    """Build a QPalette from the current Colors state (call after apply_theme)."""
    pal = QPalette()
    bg = QColor(Colors.BG_DARK)
    base = QColor(Colors.BG_DARK).darker(110) if Colors._active_mode == "dark" else QColor(Colors.BG_DARK).lighter(105)
    alt = QColor(Colors.BG_MID)
    text = _parse_color(Colors.TEXT_PRIMARY)
    accent = QColor(Colors.ACCENT)
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, alt)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, alt)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(Colors.TEXT_ON_ACCENT))
    pal.setColor(QPalette.ColorRole.Mid, alt)
    pal.setColor(QPalette.ColorRole.Dark, bg.darker(130))
    pal.setColor(QPalette.ColorRole.Midlight, alt.lighter(120))
    pal.setColor(QPalette.ColorRole.Shadow, QColor(Colors.SHADOW_DEEP))
    pal.setColor(QPalette.ColorRole.Light, alt.lighter(140))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(Colors.TOOLTIP_BG))
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    return pal


class Metrics:
    """Shared dimension constants ( in-place by ``apply_scaling``)."""
    BORDER_RADIUS = 10
    BORDER_RADIUS_SM = 8
    BORDER_RADIUS_MD = 10
    BORDER_RADIUS_LG = 12
    BORDER_RADIUS_XL = 16

    # Library grid cards are explicit; artwork is inset by the shared margin
    # on both sides so the card surface remains visible around the artwork.
    GRID_ITEM_W = 180
    GRID_ITEM_H = 228
    GRID_CARD_MARGIN = 5
    GRID_ART_SIZE = GRID_ITEM_W - (GRID_CARD_MARGIN * 2)
    GRID_SPACING = 18
    GRID_MARGIN_X = 28
    GRID_MARGIN_Y = 12
    GRID_CARD_SPACING = 6
    GRID_TEXT_HEIGHT = 22
    GRID_SUBTITLE_HEIGHT = 20
    GRID_CARD_RADIUS = 8
    GRID_ART_RADIUS = 6

    GRID_ITEM_PRESET_LARGE = "large"
    GRID_ITEM_PRESET_SMALL = "small"

    _GRID_ITEM_BASES = {
        "GRID_ITEM_W": 180,
        "GRID_ITEM_H": 228,
        "GRID_CARD_MARGIN": 5,
        "GRID_SPACING": 18,
        "GRID_MARGIN_X": 28,
        "GRID_MARGIN_Y": 12,
        "GRID_CARD_SPACING": 6,
        "GRID_CARD_RADIUS": 8,
        "GRID_ART_RADIUS": 6,
    }

    _GRID_ITEM_PRESET_FACTORS = {
        GRID_ITEM_PRESET_LARGE: 1.0,
        GRID_ITEM_PRESET_SMALL: 0.84,
    }

    SIDEBAR_WIDTH = 288
    SCROLLBAR_W = 10
    SCROLLBAR_MIN_H = 44

    BTN_PADDING_V = 8
    BTN_PADDING_H = 16

    # ── Font size scale (pt) ─────────────────────────────────
    # 100% is the comfortable, everyday desktop baseline. Smaller choices are
    # intentionally opt-in; users should not need 125% just to read the app.
    FONT_XS = 9        # Tech details, section headers, fine print
    FONT_SM = 10       # Descriptions, secondary labels, small buttons
    FONT_MD = 11       # Body text, toolbar buttons, controls
    FONT_LG = 12       # Table headers and setting titles
    FONT_XL = 12       # Card titles, title bar text
    FONT_XXL = 14      # Device name, stat values
    FONT_TITLE = 16    # Dialog titles, page section titles
    FONT_PAGE_TITLE = 18  # Large page headings (Sync Review, empty states)
    FONT_HERO = 22     # Settings / backup page title

    # macOS source-list/sidebar typography.  These are intentionally separate
    # from the general control scale: sidebar rows are navigation, not large
    # command buttons, and use the 13 pt macOS body baseline.
    FONT_SIDEBAR = 13
    FONT_SIDEBAR_SECTION = 11
    FONT_GRID_TITLE = 13
    FONT_GRID_SUBTITLE = 12
    FONT_BROWSER_TITLE = 15
    FONT_BROWSER_SEARCH = 13

    # ── Icon / glyph sizes (pt) — for large decorative text ──
    FONT_ICON_SM = 16   # Small icon labels in cards
    FONT_ICON_MD = 24   # Badge / backup list icons
    FONT_ICON_LG = 42   # Grid item placeholder glyphs
    FONT_ICON_XL = 52   # Empty-state decorative glyphs

    # Base values (100%) — used by apply_font_scale to recompute
    _FONT_BASES = {
        "FONT_XS": 9, "FONT_SM": 10, "FONT_MD": 11, "FONT_LG": 12,
        "FONT_XL": 12, "FONT_XXL": 14, "FONT_TITLE": 16,
        "FONT_PAGE_TITLE": 18, "FONT_HERO": 22,
        "FONT_SIDEBAR": 13, "FONT_SIDEBAR_SECTION": 11,
        "FONT_GRID_TITLE": 13, "FONT_GRID_SUBTITLE": 12,
        "FONT_BROWSER_TITLE": 15, "FONT_BROWSER_SEARCH": 13,
        "FONT_ICON_SM": 16, "FONT_ICON_MD": 24,
        "FONT_ICON_LG": 42, "FONT_ICON_XL": 52,
    }

    @classmethod
    def apply_font_scale(cls, scale_label: str = "100%") -> None:
        """Scale all FONT_* attributes by the given percentage label."""
        try:
            factor = int(scale_label.replace("%", "")) / 100.0
        except (ValueError, AttributeError):
            factor = 1.0
        factor = max(0.5, min(factor, 2.0))
        for attr, base in cls._FONT_BASES.items():
            setattr(cls, attr, max(6, round(base * factor)))
        # Grid captions have explicit line boxes so pooled cards retain stable
        # geometry. Scale those boxes with their fonts to avoid clipping at
        # accessibility sizes; apply_grid_item_scale() then derives card height.
        cls.GRID_TEXT_HEIGHT = max(12, round(22 * factor))
        cls.GRID_SUBTITLE_HEIGHT = max(12, round(20 * factor))

    @classmethod
    def apply_grid_item_scale(cls, preset: str = GRID_ITEM_PRESET_LARGE) -> None:
        """Scale grid card dimensions for the chosen size preset."""

        normalized = str(preset).strip().lower().replace("-", "_").replace(" ", "_")
        factor = cls._GRID_ITEM_PRESET_FACTORS.get(normalized, 1.0)

        for attr, base in cls._GRID_ITEM_BASES.items():
            value = 0 if base == 0 else max(1, round(base * factor))
            setattr(cls, attr, value)

        cls.GRID_ART_SIZE = max(1, cls.GRID_ITEM_W - (cls.GRID_CARD_MARGIN * 2))
        cls.GRID_ITEM_H = max(
            cls.GRID_ITEM_H,
            (cls.GRID_CARD_MARGIN * 2)
            + cls.GRID_ART_SIZE
            + cls.GRID_CARD_SPACING
            + cls.GRID_TEXT_HEIGHT
            + cls.GRID_SUBTITLE_HEIGHT,
        )


class Design:
    """iOpenPod design language primitives.

    Desktop-HIG baseline: restrained hierarchy, predictable control sizes,
    visible affordances, consistent state changes, and 4px-grid spacing.
    """

    GRID = 4

    CONTROL_RADIUS = 8
    PANEL_RADIUS = 12
    CHIP_RADIUS = 999

    CONTROL_HEIGHT_SM = 32
    CONTROL_HEIGHT_MD = 36
    CONTROL_HEIGHT_LG = 40
    ICON_BUTTON_SIZE = 32

    FIELD_PADDING_V = 4
    FIELD_PADDING_H = 12
    SPIN_PADDING_H = 8
    FIELD_CONTENT_HEIGHT = 22

    BUTTON_WEIGHT = 500
    BUTTON_WEIGHT_STRONG = 600

    # macOS source-list geometry.
    SIDEBAR_ROW_HEIGHT = 32
    SIDEBAR_ICON_SIZE = 18
    SIDEBAR_OUTER_MARGIN = 10
    SIDEBAR_ROW_PADDING = 12
    SIDEBAR_SECTION_GAP = 8


# ── Custom proxy style for scrollbar painting ───────────────────────────────

class DarkScrollbarStyle(QProxyStyle):
    """Overrides Fusion scrollbar painting with thin, dark, rounded bars.

    Qt stylesheet-based scrollbar styling is unreliable on Windows with
    Fusion (CSS is silently ignored). This proxy style paints scrollbars
    directly via QPainter so they always render correctly.
    """

    @property
    def _min_handle(self):
        return (36)
    _TRACK = QColor(0, 0, 0, 0)           # invisible track

    @property
    def _thumb(self):
        return QColor(255, 255, 255, 70) if Colors._active_mode == "dark" else QColor(0, 0, 0, 55)

    @property
    def _thumb_hover(self):
        return QColor(255, 255, 255, 110) if Colors._active_mode == "dark" else QColor(0, 0, 0, 90)

    @property
    def _thumb_press(self):
        return QColor(255, 255, 255, 140) if Colors._active_mode == "dark" else QColor(0, 0, 0, 120)

    _CLICKABLE_TYPES = (QAbstractButton, QComboBox, QGroupBox, QTabBar)

    def __init__(self, base_key: str = "Fusion"):
        super().__init__(base_key)

    # -- Pointing-hand cursor for clickable widgets --

    def polish(self, arg):  # type: ignore[override]
        if isinstance(arg, QPalette):
            return super().polish(arg)
        if isinstance(arg, self._CLICKABLE_TYPES):
            arg.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # Widget-level stylesheet on the tooltip: highest priority.
        # App-level QToolTip CSS is ignored because QStyleSheetStyle
        # intercepts PE_PanelTipLabel before our proxy-style handler
        # runs, and resolves the palette to black.  A widget-level
        # stylesheet can't be overridden by app-level rules.
        meta = arg.metaObject()
        if meta is not None and meta.className() == "QTipLabel":
            tooltip_style_key = (
                Colors.TOOLTIP_BG,
                Colors.TEXT_PRIMARY,
                Colors.BORDER,
                Metrics.FONT_LG,
            )
            if arg.property("_iop_tooltip_style_key") != tooltip_style_key:
                arg.setProperty("_iop_tooltip_style_key", tooltip_style_key)
                try:
                    arg.setAttribute(
                        Qt.WidgetAttribute.WA_TranslucentBackground, True
                    )
                except TypeError:
                    pass  # Some PyQt6 builds reject the enum via SIP
                arg.setStyleSheet(
                    f"background-color: {Colors.TOOLTIP_BG};"
                    f"color: {Colors.TEXT_PRIMARY};"
                    f"border: 1px solid {Colors.BORDER};"
                    f"border-radius: {(4)}px;"
                    f"padding: {(3)}px {(6)}px;"
                    f"font-family: {_CSS_FONT_STACK};"
                    f"font-size: {Metrics.FONT_LG}pt;"
                )
        super().polish(arg)

    # -- Metrics: make scrollbars thin --

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_ScrollBarExtent,
        ):
            return max(4, (8))
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return (36)
        return super().pixelMetric(metric, option, widget)

    # -- Sub-control rectangles --

    def subControlRect(self, cc, opt, sc, widget=None):
        if cc != QStyle.ComplexControl.CC_ScrollBar or not isinstance(opt, QStyleOptionSlider):
            return super().subControlRect(cc, opt, sc, widget)

        r = opt.rect
        horiz = opt.orientation == Qt.Orientation.Horizontal
        length = r.width() if horiz else r.height()

        # No step buttons
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddLine,
            QStyle.SubControl.SC_ScrollBarSubLine,
        ):
            return QRect()

        # Groove = full rect
        if sc == QStyle.SubControl.SC_ScrollBarGroove:
            return r

        # Slider handle
        if sc == QStyle.SubControl.SC_ScrollBarSlider:
            rng = opt.maximum - opt.minimum
            if rng <= 0:
                return r  # full when no range
            page = max(opt.pageStep, 1)
            handle_len = max(
                int(length * page / (rng + page)),
                self._min_handle,
            )
            available = length - handle_len
            if available <= 0:
                pos = 0
            else:
                pos = int(available * (opt.sliderValue - opt.minimum) / rng)
            if horiz:
                return QRect(r.x() + pos, r.y(), handle_len, r.height())
            else:
                return QRect(r.x(), r.y() + pos, r.width(), handle_len)

        # Page areas
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddPage,
            QStyle.SubControl.SC_ScrollBarSubPage,
        ):
            slider = self.subControlRect(cc, opt, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if sc == QStyle.SubControl.SC_ScrollBarSubPage:
                if horiz:
                    return QRect(r.x(), r.y(), slider.x() - r.x(), r.height())
                else:
                    return QRect(r.x(), r.y(), r.width(), slider.y() - r.y())
            else:
                if horiz:
                    end = slider.x() + slider.width()
                    return QRect(end, r.y(), r.right() - end + 1, r.height())
                else:
                    end = slider.y() + slider.height()
                    return QRect(r.x(), end, r.width(), r.bottom() - end + 1)

        return super().subControlRect(cc, opt, sc, widget)

    # -- Hit testing --

    def hitTestComplexControl(self, control, option, pos, widget=None):
        if control == QStyle.ComplexControl.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if slider.contains(pos):
                return QStyle.SubControl.SC_ScrollBarSlider
            groove = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarGroove, widget)
            if groove.contains(pos):
                horiz = option.orientation == Qt.Orientation.Horizontal
                if (horiz and pos.x() < slider.x()) or (not horiz and pos.y() < slider.y()):
                    return QStyle.SubControl.SC_ScrollBarSubPage
                return QStyle.SubControl.SC_ScrollBarAddPage
            return QStyle.SubControl.SC_None
        return super().hitTestComplexControl(control, option, pos, widget)

    # -- Draw the scrollbar --

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option, QStyleOptionSlider):
            super().drawComplexControl(control, option, painter, widget)
            return

        # Guard against None painter (can happen during widget destruction)
        if painter is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # No track — completely transparent

        # Handle (pill shape)
        slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
        if slider.isValid() and not slider.isEmpty():
            pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
            active_sc = option.activeSubControls if isinstance(option, QStyleOptionComplex) else QStyle.SubControl.SC_None
            hovered = bool(
                (option.state & QStyle.StateFlag.State_MouseOver)
                and (active_sc & QStyle.SubControl.SC_ScrollBarSlider)
            )

            if pressed:
                color = self._thumb_press
            elif hovered:
                color = self._thumb_hover
            else:
                color = self._thumb

            horiz = option.orientation == Qt.Orientation.Horizontal
            # Inset to create a floating pill centered in the track
            pad = 2  # padding from edge of scrollbar track
            if horiz:
                thumb_h = max(slider.height() - pad * 2, 4)
                adj = QRect(
                    slider.x() + 2, slider.y() + pad,
                    slider.width() - 4, thumb_h,
                )
            else:
                thumb_w = max(slider.width() - pad * 2, 4)
                adj = QRect(
                    slider.x() + pad, slider.y() + 2,
                    thumb_w, slider.height() - 4,
                )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            # Fully rounded — radius = half the shorter dimension
            r = min(adj.width(), adj.height()) / 2.0
            painter.drawRoundedRect(adj, r, r)

        painter.restore()

    # -- Suppress default Fusion scrollbar primitives --

    def drawPrimitive(self, element, option, painter, widget=None):
        # Skip the default scrollbar arrow drawing
        if element in (
            QStyle.PrimitiveElement.PE_PanelScrollAreaCorner,
        ):
            return  # paint nothing — transparent corner
        super().drawPrimitive(element, option, painter, widget)


# ── Reusable stylesheet fragments ───────────────────────────────────────────

def scrollbar_css(width: int | None = None, orient: str = "vertical") -> str:
    """Minimal modern scrollbar — thin track, rounded thumb.

    Covers every pseudo-element so that native platform chrome never leaks
    through (especially on Windows where the default blue bar is visible
    if any sub-element is left unstyled).
    """
    if width is None:
        width = Metrics.SCROLLBAR_W
    bar = f"QScrollBar:{orient}"
    r = max(width // 2, 1)
    # Theme-adaptive handle colors
    sb_handle = Colors.BORDER
    sb_hover = Colors.TEXT_DISABLED
    sb_press = Colors.TEXT_TERTIARY
    if orient == "vertical":
        return f"""
            {bar} {{
                background: transparent;
                width: {width}px;
                margin: 0;
                padding: 2px 1px;
                border: none;
            }}
            {bar}::handle {{
                background: {sb_handle};
                border-radius: {r}px;
                min-height: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {sb_hover};
            }}
            {bar}::handle:pressed {{
                background: {sb_press};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::up-arrow, {bar}::down-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """
    else:
        return f"""
            {bar} {{
                background: transparent;
                height: {width}px;
                margin: 0;
                padding: 1px 2px;
                border: none;
            }}
            {bar}::handle {{
                background: {sb_handle};
                border-radius: {r}px;
                min-width: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {sb_hover};
            }}
            {bar}::handle:pressed {{
                background: {sb_press};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::left-arrow, {bar}::right-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """


def scrollbar_corner_css() -> str:
    """Style the corner widget where horizontal & vertical scrollbars meet."""
    return """
        QAbstractScrollArea::corner {
            background: transparent;
            border: none;
        }
    """


def _button_size_tokens(size: str) -> tuple[int, int, str]:
    """Return (min-height, font-size, padding) for a design-system button."""
    if size == "sm":
        return (
            Design.CONTROL_HEIGHT_SM,
            Metrics.FONT_SM,
            f"0px {Design.GRID * 3}px",
        )
    if size == "lg":
        return (
            Design.CONTROL_HEIGHT_LG,
            Metrics.FONT_LG,
            f"0px {Design.GRID * 5}px",
        )
    return (
        Design.CONTROL_HEIGHT_MD,
        Metrics.FONT_MD,
        f"0px {Design.GRID * 4}px",
    )


def btn_css(
    bg: str | None = None,
    bg_hover: str | None = None,
    bg_press: str | None = None,
    fg: str | None = None,
    border: str = "none",
    radius: int | None = None,
    padding: str | None = None,
    bg_disabled: str | None = None,
    fg_disabled: str | None = None,
    extra: str = "",
    min_height: int | None = None,
    min_width: int | None = None,
    font_size: int | None = None,
    font_weight: int | str | None = None,
) -> str:
    """Standard button stylesheet."""
    if bg is None:
        bg = Colors.SURFACE_RAISED
    if bg_hover is None:
        bg_hover = Colors.SURFACE_HOVER
    if bg_press is None:
        bg_press = Colors.SURFACE_ALT
    if fg is None:
        fg = Colors.TEXT_PRIMARY
    if radius is None:
        radius = Metrics.BORDER_RADIUS_SM
    if padding is None:
        padding = f"{Metrics.BTN_PADDING_V}px {Metrics.BTN_PADDING_H}px"
    _d_bg = bg_disabled if bg_disabled is not None else Colors.SURFACE
    _d_fg = fg_disabled if fg_disabled is not None else Colors.TEXT_DISABLED
    min_height_rule = f"min-height: {min_height}px;" if min_height is not None else ""
    min_width_rule = f"min-width: {min_width}px;" if min_width is not None else ""
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    font_weight_rule = f"font-weight: {font_weight};" if font_weight is not None else ""
    return f"""
        QPushButton {{
            background: {bg};
            border: {border};
            border-radius: {radius}px;
            color: {fg};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            {font_weight_rule}
            padding: {padding};
            {min_height_rule}
            {min_width_rule}
            {extra}
        }}
        QPushButton:hover {{
            background: {bg_hover};
        }}
        QPushButton:pressed {{
            background: {bg_press};
        }}
        QPushButton:disabled {{
            background: {_d_bg};
            color: {_d_fg};
            border-color: {Colors.BORDER_SUBTLE};
        }}
    """


def button_css(role: str = "secondary", size: str = "md", *, extra: str = "") -> str:
    """Design-system button stylesheet.

    Roles:
    - ``primary``: one main action per surface.
    - ``secondary``: normal command button.
    - ``quiet``: low-emphasis command.
    - ``danger``: destructive command.
    """
    height, font_size, padding = _button_size_tokens(size)
    radius = Design.CONTROL_RADIUS

    if role == "primary":
        return btn_css(
            bg=Colors.ACCENT,
            bg_hover=Colors.ACCENT_LIGHT,
            bg_press=Colors.ACCENT_SOLID_PRESS,
            fg=Colors.TEXT_ON_ACCENT,
            border="none",
            radius=radius,
            padding=padding,
            bg_disabled=Colors.SURFACE,
            fg_disabled=Colors.TEXT_DISABLED,
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT_STRONG,
            extra=extra,
        )
    if role == "quiet":
        return btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_SECONDARY,
            border="1px solid transparent",
            radius=radius,
            padding=padding,
            bg_disabled="transparent",
            fg_disabled=Colors.TEXT_DISABLED,
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT,
            extra=extra,
        )
    if role == "danger":
        return btn_css(
            bg="transparent",
            bg_hover=Colors.DANGER_DIM,
            bg_press=Colors.DANGER_HOVER,
            fg=Colors.DANGER,
            border=f"1px solid {Colors.DANGER_BORDER}",
            radius=radius,
            padding=padding,
            bg_disabled=Colors.SURFACE,
            fg_disabled=Colors.TEXT_DISABLED,
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT,
            extra=extra,
        )

    return btn_css(
        bg=Colors.SURFACE_RAISED,
        bg_hover=Colors.SURFACE_HOVER,
        bg_press=Colors.SURFACE_ACTIVE,
        fg=Colors.TEXT_PRIMARY,
        border=f"1px solid {Colors.BORDER}",
        radius=radius,
        padding=padding,
        bg_disabled=Colors.SURFACE,
        fg_disabled=Colors.TEXT_DISABLED,
        min_height=height,
        font_size=font_size,
        font_weight=Design.BUTTON_WEIGHT,
        extra=extra,
    )


def accent_btn_css(size: str = "md") -> str:
    """Primary action button."""
    return button_css("primary", size)


def danger_btn_css(size: str = "md") -> str:
    """Destructive action button (red)."""
    return button_css("danger", size)


def icon_btn_css(
    size: int | None = None,
    *,
    bg: str = "transparent",
    bg_hover: str | None = None,
    bg_press: str | None = None,
    fg: str | None = None,
    radius: int | None = None,
) -> str:
    """Square icon/symbol button with stable hit target."""
    if size is None:
        size = Design.ICON_BUTTON_SIZE
    if bg_hover is None:
        bg_hover = Colors.SURFACE_HOVER
    if bg_press is None:
        bg_press = Colors.SURFACE_ACTIVE
    if fg is None:
        fg = Colors.TEXT_SECONDARY
    if radius is None:
        radius = Design.CONTROL_RADIUS
    return btn_css(
        bg=bg,
        bg_hover=bg_hover,
        bg_press=bg_press,
        fg=fg,
        border="none",
        radius=radius,
        padding="0px",
        bg_disabled="transparent",
        fg_disabled=Colors.TEXT_DISABLED,
        font_size=Metrics.FONT_MD,
        font_weight=Design.BUTTON_WEIGHT,
        extra=(
            f"min-width: {size}px; max-width: {size}px; "
            f"min-height: {size}px; max-height: {size}px;"
        ),
    )


def chip_btn_css(size: str = "sm", *, checked_accent: bool = True) -> str:
    """Selectable pill/chip button used for filters, IDs, and segmented bits."""
    height, font_size, padding = _button_size_tokens(size)
    checked_bg = Colors.ACCENT_MUTED if checked_accent else Colors.SURFACE_ACTIVE
    checked_border = Colors.ACCENT_BORDER
    return btn_css(
        bg=Colors.SURFACE_RAISED,
        bg_hover=Colors.SURFACE_HOVER,
        bg_press=Colors.SURFACE_ACTIVE,
        fg=Colors.TEXT_SECONDARY,
        border=f"1px solid {Colors.BORDER_SUBTLE}",
        radius=Design.CHIP_RADIUS,
        padding=padding,
        min_height=height,
        font_size=font_size,
        font_weight=Design.BUTTON_WEIGHT,
    ) + f"""
        QPushButton:hover {{
            color: {Colors.TEXT_PRIMARY};
            border-color: {Colors.BORDER};
        }}
        QPushButton:checked {{
            background: {checked_bg};
            color: {Colors.TEXT_PRIMARY};
            border-color: {checked_border};
            font-weight: {Design.BUTTON_WEIGHT_STRONG};
        }}
    """


def back_btn_css() -> str:
    """Compact arrow-only back button used by full-page app chrome."""
    size = Design.ICON_BUTTON_SIZE
    return btn_css(
        padding="0px",
        radius=Metrics.BORDER_RADIUS_SM,
        extra=(
            f"min-width: {size}px; max-width: {size}px; "
            f"min-height: {size}px; max-height: {size}px;"
        ),
    )


def input_css(
    radius: int | None = None,
    padding: str | None = None,
    *,
    min_height: int | None = None,
    font_size: int | None = None,
    font_weight: int | str | None = None,
) -> str:
    """Standard input field stylesheet for QLineEdit / QTextEdit."""
    if radius is None:
        radius = Design.CONTROL_RADIUS
    if padding is None:
        padding = f"{Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px"
    if min_height is None:
        min_height = Design.FIELD_CONTENT_HEIGHT
    if font_size is None:
        font_size = Metrics.FONT_MD
    min_height_rule = f"min-height: {min_height}px;" if min_height is not None else ""
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    font_weight_rule = f"font-weight: {font_weight};" if font_weight is not None else ""
    return f"""
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background: {Colors.SURFACE_ALT};
            border: 1px solid {Colors.BORDER};
            border-radius: {radius}px;
            color: {Colors.TEXT_PRIMARY};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            {font_weight_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border: 1px solid {Colors.BORDER_FOCUS};
            background: {Colors.SURFACE_RAISED};
        }}
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
            background: {Colors.SURFACE};
            color: {Colors.TEXT_DISABLED};
            border-color: {Colors.BORDER_SUBTLE};
        }}
    """


def combo_css(
    radius: int | None = None,
    padding: str | None = None,
    *,
    min_height: int | None = None,
    font_size: int | None = None,
    font_weight: int | str | None = None,
) -> str:
    """Standard combo box stylesheet for QComboBox."""
    if radius is None:
        radius = Design.CONTROL_RADIUS
    if padding is None:
        padding = f"{Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px"
    if min_height is None:
        min_height = Design.FIELD_CONTENT_HEIGHT
    if font_size is None:
        font_size = Metrics.FONT_MD
    min_height_rule = f"min-height: {min_height}px;" if min_height is not None else ""
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    font_weight_rule = f"font-weight: {font_weight};" if font_weight is not None else ""
    return f"""
        QComboBox, QDateEdit {{
            background: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: {radius}px;
            color: {Colors.TEXT_PRIMARY};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            {font_weight_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QComboBox:hover, QDateEdit:hover {{
            border: 1px solid {Colors.BORDER_FOCUS};
        }}
        QComboBox:focus, QDateEdit:focus {{
            border: 1px solid {Colors.BORDER_FOCUS};
        }}
        QComboBox::drop-down, QDateEdit::drop-down {{
            border: none;
            width: {(22)}px;
        }}
        QComboBox::down-arrow, QDateEdit::down-arrow {{
            image: none;
            border: none;
        }}
        QComboBox QAbstractItemView, QDateEdit QAbstractItemView {{
            background: {Colors.DROPDOWN_BG};
            color: {Colors.TEXT_PRIMARY};
            selection-background-color: {Colors.ACCENT_DIM};
            selection-color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            border-radius: 4px;
            padding: 2px;
            outline: none;
        }}
        QComboBox:disabled, QDateEdit:disabled {{
            background: {Colors.SURFACE};
            color: {Colors.TEXT_DISABLED};
            border-color: {Colors.BORDER_SUBTLE};
        }}
    """


def spin_css(
    radius: int | None = None,
    padding: str | None = None,
    *,
    min_height: int | None = None,
    font_size: int | None = None,
) -> str:
    """Standard spin box stylesheet."""
    if radius is None:
        radius = Design.CONTROL_RADIUS
    if padding is None:
        padding = f"{Design.FIELD_PADDING_V}px {Design.SPIN_PADDING_H}px"
    if min_height is None:
        min_height = Design.FIELD_CONTENT_HEIGHT
    if font_size is None:
        font_size = Metrics.FONT_MD
    min_height_rule = f"min-height: {min_height}px;" if min_height is not None else ""
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    return f"""
        QSpinBox, QDoubleSpinBox {{
            background: {Colors.SURFACE_ALT};
            border: 1px solid {Colors.BORDER};
            border-radius: {radius}px;
            color: {Colors.TEXT_PRIMARY};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QSpinBox:hover, QDoubleSpinBox:hover {{
            border-color: {Colors.BORDER_FOCUS};
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {Colors.BORDER_FOCUS};
            background: {Colors.SURFACE_RAISED};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            border: none;
            background: transparent;
            width: {(16)}px;
        }}
        QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background: {Colors.SURFACE};
            color: {Colors.TEXT_DISABLED};
            border-color: {Colors.BORDER_SUBTLE};
        }}
    """


def checkbox_css(font_size: int | None = None) -> str:
    """Standard checkbox stylesheet."""
    if font_size is None:
        font_size = Metrics.FONT_MD
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    return f"""
        QCheckBox {{
            color: {Colors.TEXT_PRIMARY};
            background: transparent;
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: {(18)}px;
            height: {(18)}px;
            border-radius: {(4)}px;
            border: 1px solid {Colors.BORDER};
            background: {Colors.SURFACE_ALT};
        }}
        QCheckBox::indicator:hover {{
            border-color: {Colors.BORDER_FOCUS};
            background: {Colors.SURFACE_HOVER};
        }}
        QCheckBox::indicator:checked {{
            background: {Colors.ACCENT};
            border-color: {Colors.ACCENT};
        }}
        QCheckBox::indicator:checked:hover {{
            background: {Colors.ACCENT_HOVER};
            border-color: {Colors.ACCENT_HOVER};
        }}
        QCheckBox::indicator:disabled {{
            background: {Colors.SURFACE};
            border-color: {Colors.BORDER_SUBTLE};
        }}
    """


def title_input_css() -> str:
    """Borderless title-edit field used in editor headers."""
    return f"""
        QLineEdit {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            color: {Colors.TEXT_PRIMARY};
            font-family: {_CSS_FONT_STACK};
            font-size: {Metrics.FONT_PAGE_TITLE}pt;
            font-weight: {Design.BUTTON_WEIGHT_STRONG};
            padding: 0px 0px 2px 0px;
        }}
        QLineEdit:hover {{
            border-bottom-color: {Colors.BORDER};
        }}
        QLineEdit:focus {{
            border-bottom-color: {Colors.BORDER_FOCUS};
        }}
    """


def link_btn_css() -> str:
    """Transparent text-link button (no background, accent-colored text)."""
    return f"""
        QPushButton {{
            background: transparent;
            border: none;
            color: {Colors.ACCENT};
            padding: 0;
            text-align: left;
        }}
        QPushButton:hover {{
            color: {Colors.ACCENT_LIGHT};
            text-decoration: underline;
        }}
        QPushButton:pressed {{
            color: {Colors.ACCENT};
        }}
    """


# ── Button style presets (functions — resolved at call time so scaling applies)


@dataclass(frozen=True)
class SidebarNavState:
    """Canonical visual state shared by every sidebar navigation adapter."""

    background: str
    hover_background: str
    pressed_background: str
    text: str
    icon: str
    weight: int


def sidebar_nav_state(
    selected: bool,
    *,
    enabled: bool = True,
    dimmed: bool = False,
) -> SidebarNavState:
    """Resolve sidebar colors and weight from semantic navigation state."""

    if not enabled:
        return SidebarNavState(
            background="transparent",
            hover_background=Colors.SURFACE_HOVER,
            pressed_background=Colors.SURFACE,
            text=Colors.TEXT_DISABLED,
            icon=Colors.TEXT_DISABLED,
            weight=400,
        )
    if selected:
        return SidebarNavState(
            background=Colors.SURFACE_ACTIVE,
            hover_background=Colors.SURFACE_ACTIVE,
            pressed_background=Colors.SURFACE_RAISED,
            text=Colors.TEXT_PRIMARY,
            icon=Colors.ACCENT,
            weight=Design.BUTTON_WEIGHT_STRONG,
        )
    if dimmed:
        return SidebarNavState(
            background="transparent",
            hover_background=Colors.SURFACE_HOVER,
            pressed_background=Colors.SURFACE,
            text=Colors.TEXT_DISABLED,
            icon=Colors.TEXT_DISABLED,
            weight=400,
        )
    return SidebarNavState(
        background="transparent",
        hover_background=Colors.SURFACE_HOVER,
        pressed_background=Colors.SURFACE,
        text=Colors.TEXT_PRIMARY,
        icon=Colors.TEXT_SECONDARY,
        weight=400,
    )


def sidebar_panel_css(object_name: str) -> str:
    """Canonical sidebar panel surface and trailing seam."""

    return f"""
        QFrame#{object_name} {{
            background: {Colors.SURFACE};
            border: none;
            border-right: 1px solid {Colors.BORDER_SUBTLE};
        }}
    """


def sidebar_item_view_css(
    selector: str = "QListWidget",
    *,
    background: str | None = None,
) -> str:
    """Canonical source-list styling for QListWidget-based sidebars.

    ``background="transparent"`` lets an embedded list inherit its host
    panel's surface without painting a second rectangular layer.
    """

    normal = sidebar_nav_state(False)
    selected = sidebar_nav_state(True)
    viewport_background = Colors.SURFACE if background is None else background
    return f"""
        {selector} {{
            background: {viewport_background};
            border: none;
            outline: none;
            padding: {Design.SIDEBAR_OUTER_MARGIN}px;
        }}
        {selector}::viewport {{
            background: {viewport_background};
        }}
        {selector}::item {{
            min-height: {Design.SIDEBAR_ROW_HEIGHT}px;
            padding: 0px {Design.SIDEBAR_ROW_PADDING}px;
            margin: 0px;
            border: none;
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
            color: {normal.text};
            font-size: {Metrics.FONT_SIDEBAR}pt;
            font-weight: {normal.weight};
        }}
        {selector}::item:selected {{
            background: {selected.background};
            color: {selected.text};
            font-weight: {selected.weight};
        }}
        {selector}::item:hover:!selected {{
            background: {normal.hover_background};
            color: {normal.text};
        }}
    """


def sidebar_nav_css(
    *,
    selected: bool = False,
    enabled: bool = True,
    dimmed: bool = False,
) -> str:
    state = sidebar_nav_state(selected, enabled=enabled, dimmed=dimmed)
    return btn_css(
        bg=state.background,
        bg_hover=state.hover_background,
        bg_press=state.pressed_background,
        fg=state.text,
        bg_disabled="transparent",
        radius=Metrics.BORDER_RADIUS_SM,
        padding=f"0px {Design.SIDEBAR_ROW_PADDING}px",
        min_height=Design.SIDEBAR_ROW_HEIGHT,
        font_size=Metrics.FONT_SIDEBAR,
        font_weight=state.weight,
        extra="text-align: left;",
    )


def sidebar_nav_selected_css() -> str:
    """Compatibility wrapper for callers not yet migrated to semantic state."""

    return sidebar_nav_css(selected=True)


def toolbar_btn_css() -> str:
    return button_css(
        "secondary",
        "md",
        extra=(
            f"min-width: {Design.CONTROL_HEIGHT_MD}px; "
            f"padding-left: {Design.GRID * 2}px; "
            f"padding-right: {Design.GRID * 2}px;"
        ),
    )


def table_css() -> str:
    """Shared table + header stylesheet for QTableWidget instances."""
    return f"""
        QTableWidget {{
            background-color: {Colors.SHADOW_LIGHT};
            alternate-background-color: {Colors.SURFACE};
            border: none;
            color: {Colors.TEXT_PRIMARY};
            gridline-color: {Colors.GRIDLINE};
            selection-background-color: {Colors.SELECTION};
            outline: none;
            font-size: {Metrics.FONT_MD}pt;
        }}
        QTableWidget::item {{
            padding: 8px 10px;
            border-bottom: 1px solid {Colors.BORDER_SUBTLE};
        }}
        QTableWidget::item:selected {{
            background-color: {Colors.SELECTION};
        }}
        QTableWidget::item:hover {{
            background-color: {Colors.SURFACE};
        }}
        QTableView::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {Colors.BORDER};
            background: {Colors.SURFACE_ALT};
        }}
        QTableView::indicator:hover {{
            border-color: {Colors.BORDER_FOCUS};
            background: {Colors.SURFACE_HOVER};
        }}
        QTableView::indicator:checked {{
            background: {Colors.ACCENT};
            border-color: {Colors.ACCENT};
        }}
        QTableView::indicator:checked:hover {{
            background: {Colors.ACCENT_HOVER};
            border-color: {Colors.ACCENT_HOVER};
        }}
        QTableView::indicator:disabled {{
            background: {Colors.SURFACE};
            border-color: {Colors.BORDER_SUBTLE};
        }}
        QHeaderView::section {{
            background-color: {Colors.SURFACE_ALT};
            color: {Colors.TEXT_SECONDARY};
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid {Colors.BORDER};
            font-weight: 600;
            font-size: {Metrics.FONT_LG}pt;
        }}
        QHeaderView::section:hover {{
            background-color: {Colors.SURFACE_RAISED};
            color: {Colors.TEXT_PRIMARY};
        }}
        QHeaderView::section:pressed {{
            background-color: {Colors.SURFACE_ACTIVE};
        }}
        QTableCornerButton::section {{
            background-color: {Colors.SURFACE_ALT};
            border: none;
            border-bottom: 1px solid {Colors.BORDER};
        }}
    """


def context_menu_css() -> str:
    """Shared stylesheet for right-click context menus."""
    return f"""
        QMenu {{
            background: {Colors.MENU_BG};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            padding: 6px;
            font-size: {Metrics.FONT_MD}pt;
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
        }}
        QMenu::item {{
            padding: 8px 28px 8px 12px;
        }}
        QMenu::item:selected {{
            background: {Colors.ACCENT_DIM};
        }}
        QMenu::item:disabled {{
            color: {Colors.TEXT_DISABLED};
            background: transparent;
        }}
        QMenu::item:disabled:selected {{
            color: {Colors.TEXT_DISABLED};
            background: {Colors.SURFACE};
        }}
        QMenu::separator {{
            height: 1px;
            background: {Colors.BORDER_SUBTLE};
            margin: 4px 8px;
        }}
    """

# ── Shared label style strings ───────────────────────────────────────────────


def LABEL_PRIMARY() -> str:
    return f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"


def LABEL_SECONDARY() -> str:
    return f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"


def LABEL_TERTIARY() -> str:
    return f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;"


def LABEL_DISABLED() -> str:
    return f"color: {Colors.TEXT_DISABLED}; background: transparent; border: none;"


def SEPARATOR_CSS() -> str:
    return f"background-color: {Colors.BORDER_SUBTLE}; border: none;"


# ── Widget factory helpers ───────────────────────────────────────────────────

def make_label(
    text: str = "",
    size: int = Metrics.FONT_MD,
    weight: int = -1,
    style: str | None = None,
    *,
    wrap: bool = False,
    mono: bool = False,
    selectable: bool = False,
) -> QLabel:
    """Create a styled QLabel. Import-safe (uses late import)."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QLabel as _QLabel

    if style is None:
        style = LABEL_PRIMARY()
    lbl = _QLabel(text)
    family = MONO_FONT_FAMILY if mono else FONT_FAMILY
    if weight >= 0:
        lbl.setFont(_QFont(family, size, weight))
    else:
        lbl.setFont(_QFont(family, size))
    lbl.setStyleSheet(style)
    if wrap:
        lbl.setWordWrap(True)
    if selectable:
        lbl.setTextInteractionFlags(_Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def make_separator() -> QFrame:
    """Create a 1px horizontal separator line."""
    from PyQt6.QtWidgets import QFrame as _QFrame

    sep = _QFrame()
    sep.setFixedHeight(1)
    sep.setStyleSheet(SEPARATOR_CSS())
    return sep


def make_section_header(text: str) -> QLabel:
    """Create a small uppercase section header label."""
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QLabel as _QLabel

    lbl = _QLabel(text.upper())
    lbl.setFont(_QFont(FONT_FAMILY, Metrics.FONT_XS, _QFont.Weight.Bold))
    lbl.setStyleSheet(
        f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
        f" border: none; padding-top: {(6)}px;"
        f" letter-spacing: 1.2px;"
    )
    return lbl


def make_sidebar_section_header(text: str) -> QLabel:
    """Create the canonical title-case heading used within source lists."""

    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QLabel as _QLabel

    label = _QLabel(text)
    label.setObjectName("sidebarSectionLabel")
    label.setFont(
        _QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR_SECTION, _QFont.Weight.DemiBold)
    )
    label.setStyleSheet(
        f"color: {Colors.TEXT_SECONDARY}; background: transparent; "
        "border: none; padding: 0 4px 2px 4px;"
    )
    return label


def make_detail_row(label: str, value: str) -> QWidget:
    """Create a key–value row: left-aligned label, right-aligned mono value."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QHBoxLayout as _QHBox
    from PyQt6.QtWidgets import QLabel as _QLabel
    from PyQt6.QtWidgets import QWidget as _QWidget

    row = _QWidget()
    row.setStyleSheet("background: transparent; border: none;")
    hl = _QHBox(row)
    hl.setContentsMargins(0, (3), 0, (3))
    hl.setSpacing(8)

    lbl = _QLabel(label)
    lbl.setFont(_QFont(FONT_FAMILY, Metrics.FONT_SM))
    lbl.setStyleSheet(LABEL_TERTIARY())
    hl.addWidget(lbl)

    hl.addStretch()

    val = _QLabel(value)
    val.setFont(_QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
    val.setStyleSheet(LABEL_SECONDARY())
    val.setTextInteractionFlags(_Qt.TextInteractionFlag.TextSelectableByMouse)
    hl.addWidget(val)

    return row


def make_scroll_area(
    *,
    horizontal_off: bool = True,
    vertical: str = "as_needed",
    transparent: bool = True,
    extra_css: str = "",
) -> QScrollArea:
    """Create a standard QScrollArea with consistent styling.

    Parameters
    ----------
    horizontal_off : bool
        Disable horizontal scrollbar (default True).
    vertical : str
        ``"as_needed"`` (default), ``"always_on"``, or ``"always_off"``.
    transparent : bool
        Use transparent background with no border.
    extra_css : str
        Additional CSS to append.
    """
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QColor as _QColor
    from PyQt6.QtGui import QPalette as _QPalette
    from PyQt6.QtWidgets import QFrame as _QFrame
    from PyQt6.QtWidgets import QScrollArea as _QScrollArea

    scroll = _QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(_QFrame.Shape.NoFrame)

    if horizontal_off:
        scroll.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    vp = {
        "always_on": _Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
        "always_off": _Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
    }.get(vertical)
    if vp is not None:
        scroll.setVerticalScrollBarPolicy(vp)

    if transparent:
        pal = scroll.palette()
        pal.setColor(_QPalette.ColorRole.Window, _QColor(0, 0, 0, 0))
        pal.setColor(_QPalette.ColorRole.Base, _QColor(0, 0, 0, 0))
        scroll.setPalette(pal)
        vpw = scroll.viewport()
        if vpw is not None:
            vpw.setPalette(pal)
            vpw.setAutoFillBackground(False)

    css = ""
    if extra_css:
        css = f"{css}\n{extra_css}" if css else extra_css
    if css:
        scroll.setStyleSheet(css)

    return scroll


def card_css(
    bg: str | None = None,
    border: str | None = None,
    radius: int | None = None,
    padding: str | None = None,
    extra: str = "",
) -> str:
    """Generate stylesheet for a card / raised panel.

    All parameters have sensible defaults based on the current theme.
    """
    if bg is None:
        bg = Colors.SURFACE
    if border is None:
        border = f"1px solid {Colors.BORDER_SUBTLE}"
    if radius is None:
        radius = Metrics.BORDER_RADIUS
    if padding is None:
        padding = f"{(10)}px"
    return (
        f"background: {bg}; border: {border};"
        f" border-radius: {radius}px; padding: {padding};"
        f" {extra}"
    )


def panel_css(
    object_name: str,
    *,
    bg: str | None = None,
    border: str | None = None,
    radius: int | None = None,
    extra: str = "",
) -> str:
    """Object-scoped QFrame panel style."""
    if bg is None:
        bg = Colors.SURFACE
    if border is None:
        border = f"1px solid {Colors.BORDER_SUBTLE}"
    if radius is None:
        radius = Design.PANEL_RADIUS
    return f"""
        QFrame#{object_name} {{
            background: {bg};
            border: {border};
            border-radius: {radius}px;
            {extra}
        }}
    """


def progress_bar_css(
    *,
    height: int = 8,
    radius: int | None = None,
    bg: str | None = None,
    chunk: str | None = None,
) -> str:
    """Standard horizontal QProgressBar style."""
    if radius is None:
        radius = max(1, height // 2)
    if bg is None:
        bg = Colors.SURFACE_ALT
    if chunk is None:
        chunk = Colors.ACCENT
    return f"""
        QProgressBar {{
            background: {bg};
            border: none;
            border-radius: {radius}px;
            height: {height}px;
        }}
        QProgressBar::chunk {{
            background: {chunk};
            border-radius: {radius}px;
        }}
    """


BROWSER_SEARCH_CONTROL_SIZE = 34
BROWSER_SEARCH_FIELD_WIDTH = 190


def browser_search_field_css() -> str:
    """Shared styling for compact search fields in browser filter headers."""
    return input_css(
        radius=BROWSER_SEARCH_CONTROL_SIZE // 2,
        padding="0px 12px",
        min_height=BROWSER_SEARCH_CONTROL_SIZE - 2,
        font_size=Metrics.FONT_BROWSER_SEARCH,
    )


# ── Application-level stylesheet ────────────────────────────────────────────

def app_stylesheet() -> str:
    """Build the global stylesheet with current (possibly ) metrics."""
    return f"""
    /* ── Base ──────────────────────────────────────────────────── */
    QMainWindow {{
        background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1,
            stop:0 {Colors.BG_DARK}, stop:1 {Colors.BG_MID});
    }}
    QWidget {{
        font-family: {_CSS_FONT_STACK};
    }}
    QStackedWidget {{
        background: transparent;
    }}
    /* Scope to QMainWindow descendants so top-level popups like
       QToolTip (which inherits QFrame) aren't made transparent. */
    QMainWindow QFrame {{
        background: transparent;
        border: none;
    }}
    QDialog QFrame {{
        background: transparent;
        border: none;
    }}

    /* ── Tooltips ──────────────────────────────────────────────── */
    /* Tooltip styling is applied as a widget-level stylesheet in
       DarkScrollbarStyle.polish() so it cannot be overridden by
       app-level rules.  No QToolTip CSS needed here.             */

    /* ── Splitter handle ───────────────────────────────────────── */
    QSplitter::handle {{
        background: {Colors.BORDER_SUBTLE};
    }}
    QSplitter::handle:hover {{
        background: {Colors.ACCENT};
    }}
    QSplitter::handle:pressed {{
        background: {Colors.ACCENT_LIGHT};
    }}

    /* ── Message boxes ─────────────────────────────────────────── */
    QMessageBox {{
        background: {Colors.DIALOG_BG};
        color: {Colors.TEXT_PRIMARY};
    }}
    QMessageBox QFrame {{
        background: transparent;
        border: none;
    }}
    QMessageBox QLabel {{
        color: {Colors.TEXT_PRIMARY};
        background: transparent;
        border: none;
    }}
    QMessageBox QPushButton {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: 0px {(20)}px;
        min-height: {Design.CONTROL_HEIGHT_LG}px;
        min-width: {(80)}px;
    }}
    QMessageBox QPushButton:hover {{
        background: {Colors.SURFACE_HOVER};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: {Colors.DIALOG_BG};
        color: {Colors.TEXT_PRIMARY};
    }}

    /* ── Input fields ───────────────────────────────────────────── */
    QLineEdit {{
        background: {Colors.SURFACE_ALT};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
        selection-background-color: {Colors.ACCENT_DIM};
    }}
    QLineEdit:focus {{
        border: 1px solid {Colors.BORDER_FOCUS};
        background: {Colors.SURFACE_RAISED};
    }}
    QLineEdit:disabled {{
        background: {Colors.SURFACE};
        color: {Colors.TEXT_DISABLED};
        border-color: {Colors.BORDER_SUBTLE};
    }}

    /* ── Combo box ──────────────────────────────────────────────── */
    QComboBox {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
    }}
    QComboBox:hover {{
        border: 1px solid {Colors.BORDER_FOCUS};
    }}
    QComboBox:focus {{
        border: 1px solid {Colors.BORDER_FOCUS};
    }}
    QComboBox::drop-down {{
        border: none;
        width: {(22)}px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background: {Colors.DROPDOWN_BG};
        color: {Colors.TEXT_PRIMARY};
        selection-background-color: {Colors.ACCENT_DIM};
        selection-color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        padding: 2px;
        outline: none;
    }}
    QComboBox:disabled {{
        background: {Colors.SURFACE};
        color: {Colors.TEXT_DISABLED};
        border-color: {Colors.BORDER_SUBTLE};
    }}

    /* ── Spin box ───────────────────────────────────────────────── */
    QSpinBox, QDoubleSpinBox {{
        background: {Colors.SURFACE_ALT};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {Design.FIELD_PADDING_V}px {Design.SPIN_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {Colors.BORDER_FOCUS};
        background: {Colors.SURFACE_RAISED};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        border: none;
        background: transparent;
        width: {(16)}px;
    }}

    /* ── Checkbox ───────────────────────────────────────────────── */
    QCheckBox {{
        color: {Colors.TEXT_PRIMARY};
        background: transparent;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: {(18)}px;
        height: {(18)}px;
        border-radius: {(4)}px;
        border: 1px solid {Colors.BORDER};
        background: {Colors.SURFACE_ALT};
    }}
    QCheckBox::indicator:hover {{
        border-color: {Colors.BORDER_FOCUS};
        background: {Colors.SURFACE_HOVER};
    }}
    QCheckBox::indicator:checked {{
        background: {Colors.ACCENT};
        border-color: {Colors.ACCENT};
    }}
    QCheckBox::indicator:checked:hover {{
        background: {Colors.ACCENT_HOVER};
        border-color: {Colors.ACCENT_HOVER};
    }}
    QCheckBox::indicator:disabled {{
        background: {Colors.SURFACE};
        border-color: {Colors.BORDER_SUBTLE};
    }}
"""
