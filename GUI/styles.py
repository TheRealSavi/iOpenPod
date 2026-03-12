"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.
"""

from __future__ import annotations

import sys
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

# ── Color palette ────────────────────────────────────────────────────────────


# ── Theme palettes ───────────────────────────────────────────────────────────
# Each palette is a dict mapping attribute name → color string.
# Colors.apply_theme() copies the selected palette onto class attributes.

_DARK_PALETTE = dict(
    ACCENT="#409cff", ACCENT_LIGHT="#60b0ff",
    ACCENT_DIM="rgba(64,156,255,80)", ACCENT_HOVER="rgba(64,156,255,120)",
    ACCENT_PRESS="rgba(64,156,255,60)", ACCENT_BORDER="rgba(64,156,255,100)",
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
    DANGER="#ff6b6b", DANGER_DIM="rgba(255,100,100,30)",
    DANGER_HOVER="rgba(255,100,100,50)",
    SUCCESS="#51cf66", SUCCESS_DIM="rgba(80,180,80,40)",
    SUCCESS_HOVER="rgba(80,180,80,60)",
    WARNING="#fcc419", INFO="#74c0fc",
    OVERLAY="rgba(30,30,38,220)",
    SHADOW_LIGHT="rgba(0,0,0,25)", SHADOW="rgba(0,0,0,40)",
    SHADOW_DEEP="rgba(0,0,0,60)",
    TEXT_ON_ACCENT="#ffffff",
    ACCENT_MUTED="rgba(64,156,255,35)",
    ACCENT_SOLID="rgba(64,156,255,200)",
    ACCENT_SOLID_PRESS="rgba(64,156,255,160)",
    ACCENT_DARK="rgba(40,100,200,100)", ACCENT_DARK_DIM="rgba(40,100,180,60)",
    DANGER_BORDER="rgba(220,60,60,80)", SUCCESS_BORDER="rgba(80,180,80,80)",
    SYNC_CYAN="#66d9e8", SYNC_PURPLE="#b197fc",
    SYNC_MAGENTA="#f06595", SYNC_ORANGE="#ff922b",
)

_LIGHT_PALETTE = dict(
    ACCENT="#0a6fdb", ACCENT_LIGHT="#3d8de5",
    ACCENT_DIM="rgba(10,111,219,60)", ACCENT_HOVER="rgba(10,111,219,100)",
    ACCENT_PRESS="rgba(10,111,219,45)", ACCENT_BORDER="rgba(10,111,219,80)",
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
    DANGER="#d9363e", DANGER_DIM="rgba(217,54,62,20)",
    DANGER_HOVER="rgba(217,54,62,35)",
    SUCCESS="#2b8a3e", SUCCESS_DIM="rgba(43,138,62,25)",
    SUCCESS_HOVER="rgba(43,138,62,40)",
    WARNING="#e07700", INFO="#1c7ed6",
    OVERLAY="rgba(240,240,245,230)",
    SHADOW_LIGHT="rgba(0,0,0,14)", SHADOW="rgba(0,0,0,22)",
    SHADOW_DEEP="rgba(0,0,0,32)",
    TEXT_ON_ACCENT="#ffffff",
    ACCENT_MUTED="rgba(10,111,219,18)",
    ACCENT_SOLID="rgba(10,111,219,180)",
    ACCENT_SOLID_PRESS="rgba(10,111,219,140)",
    ACCENT_DARK="rgba(10,80,160,80)", ACCENT_DARK_DIM="rgba(10,80,160,40)",
    DANGER_BORDER="rgba(217,54,62,60)", SUCCESS_BORDER="rgba(43,138,62,60)",
    SYNC_CYAN="#0c8599", SYNC_PURPLE="#7048e8",
    SYNC_MAGENTA="#c2255c", SYNC_ORANGE="#d9480f",
)

# High-contrast overlays: merged on top of dark or light palette
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


class Colors:
    """Named colors used throughout the app.

    All attributes start with the dark palette.  Call ``apply_theme()``
    after QApplication is created to switch palettes based on user settings.
    """

    # Current resolved mode (set by apply_theme)
    _active_mode: str = "dark"
    _active_hc: bool = False

    # Initialise with dark palette defaults
    ACCENT = _DARK_PALETTE["ACCENT"]
    ACCENT_LIGHT = _DARK_PALETTE["ACCENT_LIGHT"]
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

    # ── Semantic playlist / category color tuples (r, g, b) ──
    PLAYLIST_SMART: tuple[int, int, int] = (128, 90, 213)
    PLAYLIST_PODCAST: tuple[int, int, int] = (46, 160, 67)
    PLAYLIST_MASTER: tuple[int, int, int] = (100, 100, 120)
    PLAYLIST_REGULAR: tuple[int, int, int] = (64, 156, 255)

    # Sync storage legend color (teal — distinct from SYNC_CYAN)
    SYNC_FREED = "#66d9c2"

    @classmethod
    def _detect_system_dark(cls) -> bool:
        """Return True if the OS is in dark mode."""
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QPalette as _QPalette
            from PyQt6.QtCore import Qt
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
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QPalette as _QPalette
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
    def apply_theme(cls, theme: str = "dark", high_contrast: str = "off") -> None:
        """Resolve theme + contrast settings and update all class attributes.

        Parameters
        ----------
        theme : str
            ``"dark"``, ``"light"``, or ``"system"``
        high_contrast : str
            ``"on"``, ``"off"``, or ``"system"``
        """
        # Resolve mode
        if theme == "system":
            is_dark = cls._detect_system_dark()
        else:
            is_dark = (theme != "light")

        # Resolve contrast
        if high_contrast == "system":
            hc = cls._detect_system_hc()
        else:
            hc = (high_contrast == "on")

        cls._active_mode = "dark" if is_dark else "light"
        cls._active_hc = hc

        # Start with base palette
        palette = dict(_DARK_PALETTE if is_dark else _LIGHT_PALETTE)

        # Merge HC overrides if enabled
        if hc:
            palette.update(_HC_DARK_OVERRIDES if is_dark else _HC_LIGHT_OVERRIDES)

        # Apply all values to class attributes
        for key, value in palette.items():
            setattr(cls, key, value)


# ── DPI-aware scaling ────────────────────────────────────────────────────────

_dpi_scale: float = 1.0
"""Pixel scaling ratio.  Set by ``Metrics.apply_scaling()``."""

_font_scale: float = 1.0
"""Font-pt scaling ratio (floors higher than pixel scale)."""


def build_palette() -> QPalette:
    """Build a QPalette from the current Colors state (call after apply_theme)."""
    pal = QPalette()
    bg = QColor(Colors.BG_DARK)
    base = QColor(Colors.BG_DARK).darker(110) if Colors._active_mode == "dark" else QColor(Colors.BG_DARK).lighter(105)
    alt = QColor(Colors.BG_MID)
    text = QColor("white") if Colors._active_mode == "dark" else QColor("black")
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


def scaled(px: int | float) -> int:
    """Scale a pixel value by the current screen ratio."""
    return max(1, round(px * _dpi_scale))


def font_scaled(pt: int | float) -> int:
    """Scale a font point size by the current screen ratio."""
    return max(6, round(pt * _font_scale))


class Metrics:
    """Shared dimension constants (scaled in-place by ``apply_scaling``)."""
    BORDER_RADIUS = 8
    BORDER_RADIUS_SM = 6
    BORDER_RADIUS_LG = 10
    BORDER_RADIUS_XL = 12

    GRID_ITEM_W = 172
    GRID_ITEM_H = 230
    GRID_ART_SIZE = 152
    GRID_SPACING = 14

    SIDEBAR_WIDTH = 220
    SCROLLBAR_W = 8
    SCROLLBAR_MIN_H = 40

    BTN_PADDING_V = 7
    BTN_PADDING_H = 14

    # ── Font size scale (pt) ─────────────────────────────────
    FONT_XS = 8        # Tech details, section headers, fine print
    FONT_SM = 9        # Descriptions, secondary labels, small buttons
    FONT_MD = 10       # Body text, toolbar buttons, controls
    FONT_LG = 11       # Sidebar nav, table headers, setting titles
    FONT_XL = 12       # Card titles, title bar text
    FONT_XXL = 13      # Device name, stat values
    FONT_TITLE = 14    # Dialog titles, page section titles
    FONT_PAGE_TITLE = 16  # Large page headings (Sync Review, empty states)
    FONT_HERO = 18     # Settings / backup page title

    # ── Icon / glyph sizes (pt) — for large decorative text ──
    FONT_ICON_SM = 15   # Small icon labels in cards
    FONT_ICON_MD = 22   # Badge / backup list icons
    FONT_ICON_LG = 40   # Grid item placeholder glyphs
    FONT_ICON_XL = 48   # Empty-state decorative glyphs

    @classmethod
    def apply_scaling(cls) -> None:
        """Recompute all metrics based on primary screen geometry.

        Call once, after QApplication is created.

        If the user has set a manual UI scale in settings, that value is
        used directly.  Otherwise the scale factor is derived from the
        logical screen height relative to a 1440p reference (27" 1440p
        = 1.0×).  Screens smaller than 1440p scale down; larger screens
        scale up.
        """
        global _dpi_scale, _font_scale

        # Check for a manual override in settings
        override: float | None = None
        try:
            from .settings import get_settings
            raw_val = get_settings().ui_scale
            if raw_val and raw_val != "auto":
                override = float(raw_val)
        except Exception:
            pass

        if override is not None:
            raw = max(0.55, min(2.0, override))
        else:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if not isinstance(app, QApplication):
                return
            screen = app.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            raw = avail.height() / 1440

        _dpi_scale = max(0.55, min(2.0, raw))
        _font_scale = max(0.70, min(1.6, raw))

        s = _dpi_scale
        f = _font_scale

        # Pixel dimensions
        cls.BORDER_RADIUS = round(8 * s)
        cls.BORDER_RADIUS_SM = round(6 * s)
        cls.BORDER_RADIUS_LG = round(10 * s)
        cls.BORDER_RADIUS_XL = round(12 * s)
        cls.GRID_ITEM_W = round(172 * s)
        cls.GRID_ITEM_H = round(230 * s)
        cls.GRID_ART_SIZE = round(152 * s)
        cls.GRID_SPACING = round(14 * s)
        cls.SIDEBAR_WIDTH = round(220 * s)
        cls.SCROLLBAR_W = max(4, round(8 * s))
        cls.SCROLLBAR_MIN_H = round(40 * s)
        cls.BTN_PADDING_V = round(7 * s)
        cls.BTN_PADDING_H = round(14 * s)

        # Font sizes (less aggressive floor so text stays readable)
        cls.FONT_XS = max(6, round(8 * f))
        cls.FONT_SM = max(7, round(9 * f))
        cls.FONT_MD = max(8, round(10 * f))
        cls.FONT_LG = max(8, round(11 * f))
        cls.FONT_XL = max(9, round(12 * f))
        cls.FONT_XXL = max(10, round(13 * f))
        cls.FONT_TITLE = max(10, round(14 * f))
        cls.FONT_PAGE_TITLE = max(12, round(16 * f))
        cls.FONT_HERO = max(14, round(18 * f))

        # Icon / glyph sizes
        cls.FONT_ICON_SM = max(10, round(15 * f))
        cls.FONT_ICON_MD = max(14, round(22 * f))
        cls.FONT_ICON_LG = max(24, round(40 * f))
        cls.FONT_ICON_XL = max(30, round(48 * f))


# ── Custom proxy style for scrollbar painting ───────────────────────────────

class DarkScrollbarStyle(QProxyStyle):
    """Overrides Fusion scrollbar painting with thin, dark, rounded bars.

    Qt stylesheet-based scrollbar styling is unreliable on Windows with
    Fusion (CSS is silently ignored). This proxy style paints scrollbars
    directly via QPainter so they always render correctly.
    """

    @property
    def _THICKNESS(self):  # noqa: N802
        return max(4, scaled(8))

    @property
    def _MIN_HANDLE(self):  # noqa: N802
        return scaled(36)
    _TRACK = QColor(0, 0, 0, 0)           # invisible track

    @property
    def _THUMB(self):  # noqa: N802
        return QColor(255, 255, 255, 70) if Colors._active_mode == "dark" else QColor(0, 0, 0, 55)

    @property
    def _THUMB_HOVER(self):  # noqa: N802
        return QColor(255, 255, 255, 110) if Colors._active_mode == "dark" else QColor(0, 0, 0, 90)

    @property
    def _THUMB_PRESS(self):  # noqa: N802
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
            if not arg.property("_iop_tooltip_styled"):
                arg.setProperty("_iop_tooltip_styled", True)
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
                    f"border-radius: {scaled(4)}px;"
                    f"padding: {scaled(3)}px {scaled(6)}px;"
                    f"font-family: {_CSS_FONT_STACK};"
                    f"font-size: {Metrics.FONT_LG}px;"
                )
        super().polish(arg)

    # -- Metrics: make scrollbars thin --

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_ScrollBarExtent,
        ):
            return max(4, scaled(8))
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return scaled(36)
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
                self._MIN_HANDLE,
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
                and (active_sc & QStyle.SubControl.SC_ScrollBarSlider)  # noqa: W503
            )

            if pressed:
                color = self._THUMB_PRESS
            elif hovered:
                color = self._THUMB_HOVER
            else:
                color = self._THUMB

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


def btn_css(
    bg: str | None = None,
    bg_hover: str | None = None,
    bg_press: str | None = None,
    fg: str | None = None,
    border: str = "none",
    radius: int | None = None,
    padding: str | None = None,
    extra: str = "",
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
    return f"""
        QPushButton {{
            background: {bg};
            border: {border};
            border-radius: {radius}px;
            color: {fg};
            padding: {padding};
            {extra}
        }}
        QPushButton:hover {{
            background: {bg_hover};
        }}
        QPushButton:pressed {{
            background: {bg_press};
        }}
    """


def accent_btn_css() -> str:
    """Primary action button (blue accent)."""
    return btn_css(
        bg=Colors.ACCENT_DIM,
        bg_hover=Colors.ACCENT_HOVER,
        bg_press=Colors.ACCENT_PRESS,
        fg=Colors.TEXT_ON_ACCENT,
        border=f"1px solid {Colors.ACCENT_BORDER}",
        padding=f"{Metrics.BTN_PADDING_V + 1}px {Metrics.BTN_PADDING_H + 2}px",
    )


def danger_btn_css() -> str:
    """Destructive action button (red)."""
    return btn_css(
        bg="transparent",
        bg_hover=Colors.DANGER_DIM,
        bg_press=Colors.DANGER_HOVER,
        fg=Colors.DANGER,
        border=f"1px solid {Colors.DANGER_BORDER}",
    )


# ── Button style presets (functions — resolved at call time so scaling applies)


def sidebar_nav_css() -> str:
    return btn_css(
        bg="transparent",
        bg_hover=Colors.SURFACE_ACTIVE,
        bg_press=Colors.SURFACE,
        radius=Metrics.BORDER_RADIUS_SM,
        padding=f"{scaled(7)}px {scaled(12)}px",
        extra="text-align: left;",
    )


def sidebar_nav_selected_css() -> str:
    return btn_css(
        bg=Colors.ACCENT_MUTED,
        bg_hover=Colors.ACCENT_DIM,
        bg_press=Colors.ACCENT_PRESS,
        fg=Colors.ACCENT,
        radius=Metrics.BORDER_RADIUS_SM,
        padding=f"{scaled(7)}px {scaled(12)}px",
        extra="text-align: left; font-weight: 600;",
    )


def toolbar_btn_css() -> str:
    return btn_css(
        bg=Colors.SURFACE_RAISED,
        bg_hover=Colors.SURFACE_ACTIVE,
        bg_press=Colors.SURFACE_ALT,
        padding=f"{scaled(8)}px 0",
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
        }}
        QTableWidget::item {{
            padding: 6px 8px;
            border-bottom: 1px solid {Colors.BORDER_SUBTLE};
        }}
        QTableWidget::item:selected {{
            background-color: {Colors.SELECTION};
        }}
        QTableWidget::item:hover {{
            background-color: {Colors.SURFACE};
        }}
        QHeaderView::section {{
            background-color: {Colors.SURFACE_ALT};
            color: {Colors.TEXT_SECONDARY};
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid {Colors.BORDER};
            font-weight: 600;
            font-size: 11px;
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
) -> "QLabel":
    """Create a styled QLabel. Import-safe (uses late import)."""
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QLabel as _QLabel
    from PyQt6.QtCore import Qt as _Qt

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


def make_separator() -> "QFrame":
    """Create a 1px horizontal separator line."""
    from PyQt6.QtWidgets import QFrame as _QFrame

    sep = _QFrame()
    sep.setFixedHeight(1)
    sep.setStyleSheet(SEPARATOR_CSS())
    return sep


def make_section_header(text: str) -> "QLabel":
    """Create a small uppercase section header label."""
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtWidgets import QLabel as _QLabel

    lbl = _QLabel(text.upper())
    lbl.setFont(_QFont(FONT_FAMILY, Metrics.FONT_XS, _QFont.Weight.Bold))
    lbl.setStyleSheet(
        f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
        f" border: none; padding-top: {scaled(6)}px;"
        f" letter-spacing: 1.2px;"
    )
    return lbl


def make_detail_row(label: str, value: str) -> "QWidget":
    """Create a key–value row: left-aligned label, right-aligned mono value."""
    from PyQt6.QtGui import QFont as _QFont
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QWidget as _QWidget, QHBoxLayout as _QHBox, QLabel as _QLabel

    row = _QWidget()
    row.setStyleSheet("background: transparent; border: none;")
    hl = _QHBox(row)
    hl.setContentsMargins(0, scaled(3), 0, scaled(3))
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
) -> "QScrollArea":
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
    from PyQt6.QtWidgets import QFrame as _QFrame, QScrollArea as _QScrollArea

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

    css = ""
    if transparent:
        css = "QScrollArea { background: transparent; border: none; }"
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
        padding = f"{scaled(10)}px"
    return (
        f"background: {bg}; border: {border};"
        f" border-radius: {radius}px; padding: {padding};"
        f" {extra}"
    )


# ── Application-level stylesheet ────────────────────────────────────────────

def app_stylesheet() -> str:
    """Build the global stylesheet with current (possibly scaled) metrics."""
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
    QMessageBox QLabel {{
        color: {Colors.TEXT_PRIMARY};
    }}
    QMessageBox QPushButton {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {scaled(6)}px {scaled(20)}px;
        min-width: {scaled(70)}px;
    }}
    QMessageBox QPushButton:hover {{
        background: {Colors.SURFACE_HOVER};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: {Colors.DIALOG_BG};
        color: {Colors.TEXT_PRIMARY};
    }}
"""
