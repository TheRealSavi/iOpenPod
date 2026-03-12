"""
Drop overlay widget — shows a translucent overlay with centered text
when files are dragged over the main window.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QFont, QColor, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget

from GUI.styles import Colors, FONT_FAMILY
from GUI.glyphs import glyph_pixmap


def _qcolor(css: str) -> QColor:
    """Parse a CSS color (hex or rgba(...)) into a QColor."""
    if css.startswith("rgba("):
        parts = css[5:-1].split(",")
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = float(parts[3].strip())
        if a <= 1.0:
            a = int(a * 255)
        return QColor(r, g, b, int(a))
    return QColor(css)


class DropOverlayWidget(QWidget):
    """Translucent overlay shown during drag-and-drop."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAcceptDrops(False)  # Parent handles drop events
        self.hide()

    def show_overlay(self):
        """Resize to parent and show."""
        parent = self.parentWidget()
        if parent:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()

    def hide_overlay(self):
        self.hide()

    def paintEvent(self, a0):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # ── Background: theme-aware translucent fill ────────────────
        painter.fillRect(self.rect(), _qcolor(Colors.OVERLAY))

        # ── Inner rounded rectangle with dashed accent border ───────
        margin = (40)
        inner = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        radius = (20)

        # Subtle accent-tinted fill inside the border
        accent = _qcolor(Colors.ACCENT)
        inner_fill = QColor(accent)
        inner_fill.setAlpha(18)
        path = QPainterPath()
        path.addRoundedRect(inner, radius, radius)
        painter.fillPath(path, inner_fill)

        # Dashed border
        pen = QPen(_qcolor(Colors.ACCENT_BORDER), (2.5))
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([(8), (5)])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawRoundedRect(inner, radius, radius)

        # ── Centered content ────────────────────────────────────────
        cx = w / 2
        cy = h / 2

        # Icon
        icon_size = (56)
        icon_px = glyph_pixmap("music", icon_size, Colors.ACCENT)
        if icon_px:
            painter.drawPixmap(
                int(cx - icon_size / 2),
                int(cy - icon_size - (16)),
                icon_px,
            )

        # Primary text
        painter.setPen(_qcolor(Colors.TEXT_PRIMARY))
        primary_font = QFont(FONT_FAMILY, (20))
        primary_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(primary_font)
        primary_rect = QRectF(inner.left(), cy + (4), inner.width(), (36))
        painter.drawText(primary_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         "Drop files to add to iPod")

        # Secondary hint text
        painter.setPen(_qcolor(Colors.TEXT_SECONDARY))
        hint_font = QFont(FONT_FAMILY, (12))
        painter.setFont(hint_font)
        hint_rect = QRectF(inner.left(), cy + (42), inner.width(), (24))
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         "Audio files and folders supported")

        painter.end()
