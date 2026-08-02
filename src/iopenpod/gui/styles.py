"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.
"""

from __future__ import annotations

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
from iopenpod.infrastructure.theme_catalog import load_theme_catalog
from iopenpod.infrastructure.theme_renderer import Color, ResolvedTheme, render_theme
from iopenpod.infrastructure.theme_runtime import ThemeRuntime

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

# ── Theme runtime ──────────────────────────────────────────────────────────
#
# The catalog owns authored JSON, the renderer owns all paint recipes, and the
# runtime holds exactly one immutable resolved result for every GUI consumer.
_INITIAL_THEME = render_theme(load_theme_catalog().get("dark"))
_THEME_RUNTIME = ThemeRuntime(_INITIAL_THEME)

# Accent and artwork colors are normalized toward these contrast targets by
# the application. Theme files intentionally never configure these mechanics.
ACCENT_CONTRAST_TARGET = 3.35
GRID_ART_CONTRAST_TARGET = 3.35


def current_theme() -> ResolvedTheme:
    """Return the immutable resolved theme for shared GUI styling helpers."""

    return _THEME_RUNTIME.current


def paint_css(name: str) -> str:
    """Return one documented application paint as a Qt stylesheet color."""

    if "." not in name:
        raise ValueError(f"{name!r} is a legacy token, not an application paint")
    return current_theme().paint(name).css


def paint_qcolor(name: str) -> QColor:
    """Return one documented application paint for imperative Qt painting."""

    color = current_theme().paint(name).color
    return QColor(color.red, color.green, color.blue, color.alpha)


def _detect_system_dark() -> bool:
    """Return whether the current OS appearance is dark, defaulting safely."""

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
            bg = app.palette().color(_QPalette.ColorRole.Window)
            return bg.lightnessF() < 0.5
    except Exception:
        pass
    return True


def _detect_system_high_contrast() -> bool:
    """Return whether the current OS palette indicates increased contrast."""

    try:
        from PyQt6.QtGui import QPalette as _QPalette
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if isinstance(app, QApplication):
            palette = app.palette()
            background = palette.color(_QPalette.ColorRole.Window)
            foreground = palette.color(_QPalette.ColorRole.WindowText)
            return abs(foreground.lightnessF() - background.lightnessF()) > 0.9
    except Exception:
        pass
    return False


def apply_theme(
    theme: str = "dark",
    high_contrast: str = "off",
    accent_color: str = "blue",
) -> ResolvedTheme:
    """Resolve one theme preference set and replace the active runtime theme."""

    effective_theme = (
        "dark" if _detect_system_dark() else "light"
    ) if theme == "system" else theme
    definition = load_theme_catalog().get(effective_theme)
    high_contrast_enabled = (
        _detect_system_high_contrast() if high_contrast == "system" else high_contrast == "on"
    )
    accent_override = None
    if accent_color and accent_color not in ("blue", "match-ipod"):
        accent_override = Color.try_from_hex(accent_color)
    resolved_theme = render_theme(
        definition,
        high_contrast=high_contrast_enabled,
        accent_override=accent_override,
        accent_contrast_target=ACCENT_CONTRAST_TARGET,
    )
    _THEME_RUNTIME.replace(resolved_theme)
    return resolved_theme


def apply_theme_selection(
    mode: str,
    light_theme: str,
    dark_theme: str,
    high_contrast: str = "off",
    accent_color: str = "blue",
) -> bool:
    """Apply a selected theme and report whether its rendered appearance changed.

    The public seam replaces the immutable runtime consumed by all GUI code.
    """

    previous_theme = current_theme()
    if mode == "light":
        theme = light_theme
    elif mode == "dark":
        theme = dark_theme
    else:
        theme = dark_theme if _detect_system_dark() else light_theme
    resolved_theme = apply_theme(theme, high_contrast, accent_color)
    return (
        previous_theme.is_dark != resolved_theme.is_dark
        or previous_theme.high_contrast != resolved_theme.high_contrast
        or previous_theme.paints != resolved_theme.paints
    )


# Named accent color presets (settings value → hex).
ACCENT_PRESETS: dict[str, str] = {
    "blue": "",           # legacy key: use theme default
    "match-ipod": "",     # resolved at runtime from device info
    "preset-blue": "#409cff",
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
    """Delegate RGB luminance to the Theme Renderer color model."""

    return Color(*rgb).relative_luminance()


def _contrast_ratio(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> float:
    return Color(*a).contrast_ratio(Color(*b))


def _normalize_rgb_for_contrast(
    rgb: tuple[int, int, int],
    background: tuple[int, int, int],
    target_ratio: float,
) -> tuple[int, int, int]:
    """Delegate contrast normalization to the Theme Renderer color model."""

    return Color(*rgb).normalized_for_contrast(Color(*background), target_ratio).rgb


def display_accent_rgb(
    rgb: tuple[int, int, int],
    background: str | tuple[int, int, int] | None = None,
    target_ratio: float | None = None,
) -> tuple[int, int, int]:
    """Normalize an accent/artwork RGB color for current app background."""
    if background is None:
        bg_rgb = current_theme().paint("canvas.default").color.rgb
    elif isinstance(background, tuple):
        bg_rgb = background
    else:
        bg_rgb = _css_rgb_tuple(background)

    if bg_rgb is None:
        bg_rgb = current_theme().paint("canvas.default").color.rgb

    target = target_ratio
    if target is None:
        target = GRID_ART_CONTRAST_TARGET
    if current_theme().high_contrast:
        target = max(float(target), 4.5)
    return _normalize_rgb_for_contrast(rgb, bg_rgb, float(target))


def current_accent_rgb() -> tuple[int, int, int]:
    """Return the currently active app accent as an RGB tuple."""
    return current_theme().paint("control.primary.fill").color.rgb


def text_rgb_for_background(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Pick black or white text, whichever contrasts more with ``rgb``."""
    white = (255, 255, 255)
    black = (18, 18, 24)
    return white if _contrast_ratio(white, rgb) >= _contrast_ratio(black, rgb) else black


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
    return QColor("white" if current_theme().is_dark else "black")


def build_palette() -> QPalette:
    """Build a QPalette from the current resolved theme."""
    pal = QPalette()
    theme = current_theme()
    bg = QColor(paint_css("canvas.default"))
    base = bg.darker(110) if theme.is_dark else bg.lighter(105)
    alt = QColor(paint_css("canvas.inset"))
    text = _parse_color(paint_css("text.primary"))
    accent = QColor(paint_css("control.primary.fill"))
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, alt)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, alt)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(paint_css("control.primary.text")))
    pal.setColor(QPalette.ColorRole.Mid, alt)
    pal.setColor(QPalette.ColorRole.Dark, bg.darker(130))
    pal.setColor(QPalette.ColorRole.Midlight, alt.lighter(120))
    pal.setColor(QPalette.ColorRole.Shadow, _parse_color(paint_css("effect.elevation_deep_shadow")))
    pal.setColor(QPalette.ColorRole.Light, alt.lighter(140))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(paint_css("tooltip.background")))
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
    # Grid cards need a clear two-level reading order: the album, artist, or
    # photo name is the primary scan target, while its metadata stays quiet.
    FONT_GRID_TITLE = 14
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
        "FONT_GRID_TITLE": 14, "FONT_GRID_SUBTITLE": 12,
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
        return paint_qcolor("effect.scrollbar.thumb")

    @property
    def _thumb_hover(self):
        return paint_qcolor("effect.scrollbar.thumb_hover")

    @property
    def _thumb_press(self):
        return paint_qcolor("effect.scrollbar.thumb_press")

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
                paint_css("tooltip.background"),
                paint_css("text.primary"),
                paint_css("border.default"),
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
                    f"background-color: {paint_css('tooltip.background')};"
                    f"color: {paint_css('text.primary')};"
                    f"border: 1px solid {paint_css('border.default')};"
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
    sb_handle = paint_css("border.default")
    sb_hover = paint_css("text.disabled")
    sb_press = paint_css("text.tertiary")
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
        bg = paint_css("control.secondary.fill")
    if bg_hover is None:
        bg_hover = paint_css("control.secondary.hover_fill")
    if bg_press is None:
        bg_press = paint_css("control.secondary.pressed_fill")
    if fg is None:
        fg = paint_css("text.primary")
    if radius is None:
        radius = Metrics.BORDER_RADIUS_SM
    if padding is None:
        padding = f"{Metrics.BTN_PADDING_V}px {Metrics.BTN_PADDING_H}px"
    _d_bg = bg_disabled if bg_disabled is not None else paint_css("surface.default")
    _d_fg = fg_disabled if fg_disabled is not None else paint_css("text.disabled")
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
            border-color: {paint_css('border.subtle')};
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
            bg=paint_css("control.primary.fill"),
            bg_hover=paint_css("control.primary.hover_fill"),
            bg_press=paint_css("control.primary.pressed_fill"),
            fg=paint_css("control.primary.text"),
            border="none",
            radius=radius,
            padding=padding,
            bg_disabled=paint_css("surface.default"),
            fg_disabled=paint_css("text.disabled"),
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT_STRONG,
            extra=extra,
        )
    if role == "quiet":
        return btn_css(
            bg="transparent",
            bg_hover=paint_css("control.quiet.hover_fill"),
            bg_press=paint_css("control.quiet.pressed_fill"),
            fg=paint_css("text.secondary"),
            border="1px solid transparent",
            radius=radius,
            padding=padding,
            bg_disabled="transparent",
            fg_disabled=paint_css("text.disabled"),
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT,
            extra=extra,
        )
    if role == "danger":
        return btn_css(
            bg=paint_css("status.danger.subtle_fill"),
            bg_hover=paint_css("status.danger.hover_fill"),
            bg_press=paint_css("status.danger.hover_fill"),
            fg=paint_css("status.danger.text"),
            border=f"1px solid {paint_css('status.danger.border')}",
            radius=radius,
            padding=padding,
            bg_disabled=paint_css("surface.default"),
            fg_disabled=paint_css("text.disabled"),
            min_height=height,
            font_size=font_size,
            font_weight=Design.BUTTON_WEIGHT,
            extra=extra,
        )

    return btn_css(
        bg=paint_css("control.secondary.fill"),
        bg_hover=paint_css("control.secondary.hover_fill"),
        bg_press=paint_css("control.secondary.pressed_fill"),
        fg=paint_css("text.primary"),
        border=f"1px solid {paint_css('border.default')}",
        radius=radius,
        padding=padding,
        bg_disabled=paint_css("surface.default"),
        fg_disabled=paint_css("text.disabled"),
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
        bg_hover = paint_css("control.quiet.hover_fill")
    if bg_press is None:
        bg_press = paint_css("control.quiet.pressed_fill")
    if fg is None:
        fg = paint_css("text.secondary")
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
        fg_disabled=paint_css("text.disabled"),
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
    checked_bg = (
        paint_css("control.toggle.selected_fill")
        if checked_accent
        else paint_css("surface.active")
    )
    checked_border = paint_css("control.toggle.selected_border")
    return btn_css(
        bg=paint_css("surface.raised"),
        bg_hover=paint_css("surface.hover"),
        bg_press=paint_css("surface.active"),
        fg=paint_css("text.secondary"),
        border=f"1px solid {paint_css('border.subtle')}",
        radius=Design.CHIP_RADIUS,
        padding=padding,
        min_height=height,
        font_size=font_size,
        font_weight=Design.BUTTON_WEIGHT,
    ) + f"""
        QPushButton:hover {{
            color: {paint_css("text.primary")};
            border-color: {paint_css("border.default")};
        }}
        QPushButton:checked {{
            background: {checked_bg};
            color: {paint_css("text.primary")};
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
            background: {paint_css('surface.inset')};
            border: 1px solid {paint_css('border.default')};
            border-radius: {radius}px;
            color: {paint_css('text.primary')};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            {font_weight_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border: 1px solid {paint_css('focus.border')};
            background: {paint_css('surface.raised')};
        }}
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
            background: {paint_css('surface.default')};
            color: {paint_css('text.disabled')};
            border-color: {paint_css('border.subtle')};
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
            background: {paint_css('surface.raised')};
            border: 1px solid {paint_css('border.default')};
            border-radius: {radius}px;
            color: {paint_css('text.primary')};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            {font_weight_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QComboBox:hover, QDateEdit:hover {{
            border: 1px solid {paint_css('focus.border')};
        }}
        QComboBox:focus, QDateEdit:focus {{
            border: 1px solid {paint_css('focus.border')};
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
            background: {paint_css('menu.background')};
            color: {paint_css('text.primary')};
            selection-background-color: {paint_css('selection.fill')};
            selection-color: {paint_css('text.primary')};
            border: 1px solid {paint_css('border.default')};
            border-radius: 4px;
            padding: 2px;
            outline: none;
        }}
        QComboBox:disabled, QDateEdit:disabled {{
            background: {paint_css('surface.default')};
            color: {paint_css('text.disabled')};
            border-color: {paint_css('border.subtle')};
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
            background: {paint_css('surface.inset')};
            border: 1px solid {paint_css('border.default')};
            border-radius: {radius}px;
            color: {paint_css('text.primary')};
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            padding: {padding};
            {min_height_rule}
        }}
        QSpinBox:hover, QDoubleSpinBox:hover {{
            border-color: {paint_css('focus.border')};
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {paint_css('focus.border')};
            background: {paint_css('surface.raised')};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            border: none;
            background: transparent;
            width: {(16)}px;
        }}
        QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background: {paint_css('surface.default')};
            color: {paint_css('text.disabled')};
            border-color: {paint_css('border.subtle')};
        }}
    """


def checkbox_css(font_size: int | None = None) -> str:
    """Standard checkbox stylesheet."""
    if font_size is None:
        font_size = Metrics.FONT_MD
    font_size_rule = f"font-size: {font_size}pt;" if font_size is not None else ""
    return f"""
        QCheckBox {{
            color: {paint_css('text.primary')};
            background: transparent;
            font-family: {_CSS_FONT_STACK};
            {font_size_rule}
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: {(18)}px;
            height: {(18)}px;
            border-radius: {(4)}px;
            border: 1px solid {paint_css('border.default')};
            background: {paint_css('surface.inset')};
        }}
        QCheckBox::indicator:hover {{
            border-color: {paint_css('focus.border')};
            background: {paint_css('surface.hover')};
        }}
        QCheckBox::indicator:checked {{
            background: {paint_css('control.primary.fill')};
            border-color: {paint_css('control.primary.fill')};
        }}
        QCheckBox::indicator:checked:hover {{
            background: {paint_css('control.primary.hover_fill')};
            border-color: {paint_css('control.primary.hover_fill')};
        }}
        QCheckBox::indicator:disabled {{
            background: {paint_css('surface.default')};
            border-color: {paint_css('border.subtle')};
        }}
    """


def title_input_css() -> str:
    """Borderless title-edit field used in editor headers."""
    return f"""
        QLineEdit {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {paint_css('border.subtle')};
            color: {paint_css('text.primary')};
            font-family: {_CSS_FONT_STACK};
            font-size: {Metrics.FONT_PAGE_TITLE}pt;
            font-weight: {Design.BUTTON_WEIGHT_STRONG};
            padding: 0px 0px 2px 0px;
        }}
        QLineEdit:hover {{
            border-bottom-color: {paint_css('border.default')};
        }}
        QLineEdit:focus {{
            border-bottom-color: {paint_css('focus.border')};
        }}
    """


def link_btn_css() -> str:
    """Transparent text-link button (no background, accent-colored text)."""
    return f"""
        QPushButton {{
            background: transparent;
            border: none;
            color: {paint_css('control.primary.fill')};
            padding: 0;
            text-align: left;
        }}
        QPushButton:hover {{
            color: {paint_css('control.primary.hover_fill')};
            text-decoration: underline;
        }}
        QPushButton:pressed {{
            color: {paint_css('control.primary.fill')};
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
            hover_background=paint_css("surface.hover"),
            pressed_background=paint_css("surface.default"),
            text=paint_css("text.disabled"),
            icon=paint_css("text.disabled"),
            weight=400,
        )
    if selected:
        return SidebarNavState(
            background=paint_css("surface.active"),
            hover_background=paint_css("surface.active"),
            pressed_background=paint_css("surface.raised"),
            text=paint_css("text.primary"),
            icon=paint_css("control.primary.fill"),
            weight=Design.BUTTON_WEIGHT_STRONG,
        )
    if dimmed:
        return SidebarNavState(
            background="transparent",
            hover_background=paint_css("surface.hover"),
            pressed_background=paint_css("surface.default"),
            text=paint_css("text.disabled"),
            icon=paint_css("text.disabled"),
            weight=400,
        )
    return SidebarNavState(
        background="transparent",
        hover_background=paint_css("surface.hover"),
        pressed_background=paint_css("surface.default"),
        text=paint_css("text.primary"),
        icon=paint_css("text.secondary"),
        weight=400,
    )


def sidebar_panel_css(object_name: str) -> str:
    """Canonical sidebar panel surface and trailing seam."""

    return f"""
        QFrame#{object_name} {{
            background: {paint_css('chrome.sidebar.fill')};
            border: none;
            border-right: 1px solid {paint_css('border.subtle')};
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
    viewport_background = paint_css("chrome.sidebar.fill") if background is None else background
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
            background-color: {paint_css('table.row.fill')};
            alternate-background-color: {paint_css('table.row.alternate_fill')};
            border: none;
            color: {paint_css('text.primary')};
            gridline-color: {paint_css('border.grid')};
            selection-background-color: {paint_css('table.row.selected_fill')};
            outline: none;
            font-size: {Metrics.FONT_MD}pt;
        }}
        QTableWidget::item {{
            padding: 8px 10px;
            border-bottom: 1px solid {paint_css('border.subtle')};
        }}
        QTableWidget::item:selected {{
            background-color: {paint_css('table.row.selected_fill')};
        }}
        QTableWidget::item:hover {{
            background-color: {paint_css('surface.hover')};
        }}
        QTableView::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {paint_css('border.default')};
            background: {paint_css('surface.inset')};
        }}
        QTableView::indicator:hover {{
            border-color: {paint_css('focus.border')};
            background: {paint_css('surface.hover')};
        }}
        QTableView::indicator:checked {{
            background: {paint_css('control.primary.fill')};
            border-color: {paint_css('control.primary.fill')};
        }}
        QTableView::indicator:checked:hover {{
            background: {paint_css('control.primary.hover_fill')};
            border-color: {paint_css('control.primary.hover_fill')};
        }}
        QTableView::indicator:disabled {{
            background: {paint_css('surface.default')};
            border-color: {paint_css('border.subtle')};
        }}
        QHeaderView::section {{
            background-color: {paint_css('surface.inset')};
            color: {paint_css('text.secondary')};
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid {paint_css('border.default')};
            font-weight: 600;
            font-size: {Metrics.FONT_LG}pt;
        }}
        QHeaderView::section:hover {{
            background-color: {paint_css('surface.raised')};
            color: {paint_css('text.primary')};
        }}
        QHeaderView::section:pressed {{
            background-color: {paint_css('surface.active')};
        }}
        QTableCornerButton::section {{
            background-color: {paint_css('surface.inset')};
            border: none;
            border-bottom: 1px solid {paint_css('border.default')};
        }}
    """


def context_menu_css() -> str:
    """Shared stylesheet for right-click context menus."""
    return f"""
        QMenu {{
            background: {paint_css('menu.background')};
            color: {paint_css('text.primary')};
            border: 1px solid {paint_css('border.default')};
            padding: 6px;
            font-size: {Metrics.FONT_MD}pt;
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
        }}
        QMenu::item {{
            padding: 8px 28px 8px 12px;
        }}
        QMenu::item:selected {{
            background: {paint_css('selection.fill')};
        }}
        QMenu::item:disabled {{
            color: {paint_css('text.disabled')};
            background: transparent;
        }}
        QMenu::item:disabled:selected {{
            color: {paint_css('text.disabled')};
            background: {paint_css('surface.default')};
        }}
        QMenu::separator {{
            height: 1px;
            background: {paint_css('border.subtle')};
            margin: 4px 8px;
        }}
    """

# ── Shared label style strings ───────────────────────────────────────────────


def LABEL_PRIMARY() -> str:
    return f"color: {paint_css('text.primary')}; background: transparent; border: none;"


def LABEL_SECONDARY() -> str:
    return f"color: {paint_css('text.secondary')}; background: transparent; border: none;"


def LABEL_TERTIARY() -> str:
    return f"color: {paint_css('text.tertiary')}; background: transparent; border: none;"


def LABEL_DISABLED() -> str:
    return f"color: {paint_css('text.disabled')}; background: transparent; border: none;"


def SEPARATOR_CSS() -> str:
    return f"background-color: {paint_css('border.subtle')}; border: none;"


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
        f"color: {paint_css('text.tertiary')}; background: transparent;"
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
        f"color: {paint_css('text.secondary')}; background: transparent; "
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
        bg = paint_css("surface.default")
    if border is None:
        border = f"1px solid {paint_css('border.subtle')}"
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
        bg = paint_css("surface.default")
    if border is None:
        border = f"1px solid {paint_css('border.subtle')}"
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
        bg = paint_css("surface.inset")
    if chunk is None:
        chunk = paint_css("control.primary.fill")
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
            stop:0 {paint_css("canvas.default")}, stop:1 {paint_css("canvas.inset")});
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
        background: {paint_css("border.subtle")};
    }}
    QSplitter::handle:hover {{
        background: {paint_css("control.primary.fill")};
    }}
    QSplitter::handle:pressed {{
        background: {paint_css("control.primary.hover_fill")};
    }}

    /* ── Message boxes ─────────────────────────────────────────── */
    QMessageBox {{
        background: {paint_css("modal.background")};
        color: {paint_css("text.primary")};
    }}
    QMessageBox QFrame {{
        background: transparent;
        border: none;
    }}
    QMessageBox QLabel {{
        color: {paint_css("text.primary")};
        background: transparent;
        border: none;
    }}
    QMessageBox QPushButton {{
        background: {paint_css("surface.raised")};
        border: 1px solid {paint_css("border.default")};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {paint_css("text.primary")};
        padding: 0px {(20)}px;
        min-height: {Design.CONTROL_HEIGHT_LG}px;
        min-width: {(80)}px;
    }}
    QMessageBox QPushButton:hover {{
        background: {paint_css("surface.hover")};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: {paint_css("modal.background")};
        color: {paint_css("text.primary")};
    }}

    /* ── Input fields ───────────────────────────────────────────── */
    QLineEdit {{
        background: {paint_css("surface.inset")};
        border: 1px solid {paint_css("border.default")};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {paint_css("text.primary")};
        padding: {Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
        selection-background-color: {paint_css("control.primary.fill")};
        selection-color: {paint_css("control.primary.text")};
    }}
    QLineEdit:focus {{
        border: 1px solid {paint_css("focus.border")};
        background: {paint_css("surface.raised")};
    }}
    QLineEdit:disabled {{
        background: {paint_css("surface.default")};
        color: {paint_css("text.disabled")};
        border-color: {paint_css("border.subtle")};
    }}

    /* ── Combo box ──────────────────────────────────────────────── */
    QComboBox {{
        background: {paint_css("surface.raised")};
        border: 1px solid {paint_css("border.default")};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {paint_css("text.primary")};
        padding: {Design.FIELD_PADDING_V}px {Design.FIELD_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
    }}
    QComboBox:hover {{
        border: 1px solid {paint_css("focus.border")};
    }}
    QComboBox:focus {{
        border: 1px solid {paint_css("focus.border")};
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
        background: {paint_css("menu.background")};
        color: {paint_css("text.primary")};
        selection-background-color: {paint_css("control.primary.fill")};
        selection-color: {paint_css("control.primary.text")};
        border: 1px solid {paint_css("border.default")};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        padding: 2px;
        outline: none;
    }}
    QComboBox:disabled {{
        background: {paint_css("surface.default")};
        color: {paint_css("text.disabled")};
        border-color: {paint_css("border.subtle")};
    }}

    /* ── Spin box ───────────────────────────────────────────────── */
    QSpinBox, QDoubleSpinBox {{
        background: {paint_css("surface.inset")};
        border: 1px solid {paint_css("border.default")};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {paint_css("text.primary")};
        padding: {Design.FIELD_PADDING_V}px {Design.SPIN_PADDING_H}px;
        min-height: {Design.FIELD_CONTENT_HEIGHT}px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {paint_css("focus.border")};
        background: {paint_css("surface.raised")};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        border: none;
        background: transparent;
        width: {(16)}px;
    }}

    /* ── Checkbox ───────────────────────────────────────────────── */
    QCheckBox {{
        color: {paint_css("text.primary")};
        background: transparent;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: {(18)}px;
        height: {(18)}px;
        border-radius: {(4)}px;
        border: 1px solid {paint_css("border.default")};
        background: {paint_css("surface.inset")};
    }}
    QCheckBox::indicator:hover {{
        border-color: {paint_css("focus.border")};
        background: {paint_css("surface.hover")};
    }}
    QCheckBox::indicator:checked {{
        background: {paint_css("control.primary.fill")};
        border-color: {paint_css("control.primary.fill")};
    }}
    QCheckBox::indicator:checked:hover {{
        background: {paint_css("control.primary.hover_fill")};
        border-color: {paint_css("control.primary.hover_fill")};
    }}
    QCheckBox::indicator:disabled {{
        background: {paint_css("surface.default")};
        border-color: {paint_css("border.subtle")};
    }}
"""
