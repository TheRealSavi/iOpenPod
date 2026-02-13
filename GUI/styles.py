"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOptionComplex,
    QStyleOptionSlider,
)

# ── Color palette ────────────────────────────────────────────────────────────


class Colors:
    """Named colors used throughout the app."""
    # Primary accent
    ACCENT = "#409cff"
    ACCENT_LIGHT = "#60b0ff"
    ACCENT_DIM = "rgba(64,156,255,80)"
    ACCENT_HOVER = "rgba(64,156,255,120)"
    ACCENT_PRESS = "rgba(64,156,255,60)"
    ACCENT_BORDER = "rgba(64,156,255,100)"

    # Surfaces
    BG_DARK = "#1a1a2e"
    BG_MID = "#1e1e32"
    SURFACE = "rgba(255,255,255,8)"
    SURFACE_ALT = "rgba(255,255,255,12)"
    SURFACE_RAISED = "rgba(255,255,255,18)"
    SURFACE_HOVER = "rgba(255,255,255,25)"
    SURFACE_ACTIVE = "rgba(255,255,255,35)"

    # Text
    TEXT_PRIMARY = "rgba(255,255,255,230)"
    TEXT_SECONDARY = "rgba(255,255,255,150)"
    TEXT_TERTIARY = "rgba(255,255,255,100)"
    TEXT_DISABLED = "rgba(255,255,255,60)"

    # Borders
    BORDER = "rgba(255,255,255,30)"
    BORDER_SUBTLE = "rgba(255,255,255,15)"
    BORDER_FOCUS = "rgba(64,156,255,150)"

    # Misc
    GRIDLINE = "rgba(255,255,255,12)"
    SELECTION = "rgba(64,156,255,90)"
    STAR = "#ffc857"
    DANGER = "#ff6b6b"
    SUCCESS = "#51cf66"
    WARNING = "#fcc419"


class Metrics:
    """Shared dimension constants."""
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


# ── Custom proxy style for scrollbar painting ───────────────────────────────

class DarkScrollbarStyle(QProxyStyle):
    """Overrides Fusion scrollbar painting with thin, dark, rounded bars.

    Qt stylesheet-based scrollbar styling is unreliable on Windows with
    Fusion (CSS is silently ignored). This proxy style paints scrollbars
    directly via QPainter so they always render correctly.
    """

    _THICKNESS = 8                         # thin like macOS/VS Code
    _MIN_HANDLE = 36                       # minimum thumb length
    _TRACK = QColor(0, 0, 0, 0)           # invisible track
    _THUMB = QColor(255, 255, 255, 70)
    _THUMB_HOVER = QColor(255, 255, 255, 110)
    _THUMB_PRESS = QColor(255, 255, 255, 140)

    def __init__(self, base_key: str = "Fusion"):
        super().__init__(base_key)

    # -- Metrics: make scrollbars thin --

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_ScrollBarExtent,
        ):
            return self._THICKNESS
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return self._MIN_HANDLE
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

def scrollbar_css(width: int = Metrics.SCROLLBAR_W, orient: str = "vertical") -> str:
    """Minimal modern scrollbar — thin track, rounded thumb.

    Covers every pseudo-element so that native platform chrome never leaks
    through (especially on Windows where the default blue bar is visible
    if any sub-element is left unstyled).
    """
    bar = f"QScrollBar:{orient}"
    r = max(width // 2, 1)
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
                background: rgba(255,255,255,30);
                border-radius: {r}px;
                min-height: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: rgba(255,255,255,50);
            }}
            {bar}::handle:pressed {{
                background: rgba(255,255,255,65);
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
                background: rgba(255,255,255,30);
                border-radius: {r}px;
                min-width: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: rgba(255,255,255,50);
            }}
            {bar}::handle:pressed {{
                background: rgba(255,255,255,65);
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
    bg: str = Colors.SURFACE_RAISED,
    bg_hover: str = Colors.SURFACE_HOVER,
    bg_press: str = Colors.SURFACE_ALT,
    fg: str = "white",
    border: str = "none",
    radius: int = Metrics.BORDER_RADIUS_SM,
    padding: str = f"{Metrics.BTN_PADDING_V}px {Metrics.BTN_PADDING_H}px",
    extra: str = "",
) -> str:
    """Standard button stylesheet."""
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
        border=f"1px solid {Colors.ACCENT_BORDER}",
    )


# ── Application-level stylesheet ────────────────────────────────────────────

APP_STYLESHEET = f"""
    /* ── Base ──────────────────────────────────────────────────── */
    QMainWindow {{
        background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1,
            stop:0 {Colors.BG_DARK}, stop:1 {Colors.BG_MID});
    }}
    QWidget {{
        font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    }}
    QStackedWidget {{
        background: transparent;
    }}
    QFrame {{
        background: transparent;
        border: none;
    }}

    /* ── Tooltips ──────────────────────────────────────────────── */
    QToolTip {{
        background: #2a2d3a;
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
    }}

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
        background: #222233;
        color: white;
    }}
    QMessageBox QLabel {{
        color: white;
    }}
    QMessageBox QPushButton {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: white;
        padding: 6px 20px;
        min-width: 70px;
    }}
    QMessageBox QPushButton:hover {{
        background: {Colors.SURFACE_HOVER};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: #222233;
        color: white;
    }}
"""
