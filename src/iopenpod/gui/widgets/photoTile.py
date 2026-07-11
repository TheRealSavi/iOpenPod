from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QPixmap
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..artwork_rendering import nested_artwork_radius, rounded_artwork_pixmap
from ..glyphs import glyph_pixmap
from ..hidpi import scale_pixmap_for_display
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    display_accent_rgb,
    text_rgb_for_background,
)
from .scrollingLabel import ScrollingLabel

_PHOTO_TILE_W = Metrics.GRID_ITEM_W
_PHOTO_TILE_H = Metrics.GRID_ITEM_H
_PHOTO_IMAGE_BOX = Metrics.GRID_ART_SIZE
_PHOTO_IMAGE_SIZE = Metrics.GRID_ART_SIZE


def _css_hex_rgb(color: str) -> tuple[int, int, int] | None:
    value = color.strip()
    if len(value) != 7 or not value.startswith("#"):
        return None
    try:
        return (
            int(value[1:3], 16),
            int(value[3:5], 16),
            int(value[5:7], 16),
        )
    except ValueError:
        return None


def _blend_rgb(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    alpha: float,
) -> tuple[int, int, int]:
    return (
        int(round((foreground[0] * alpha) + (background[0] * (1.0 - alpha)))),
        int(round((foreground[1] * alpha) + (background[1] * (1.0 - alpha)))),
        int(round((foreground[2] * alpha) + (background[2] * (1.0 - alpha)))),
    )


class PhotoGridTile(QFrame):
    """Photo tile styled to match the music browser's card treatment."""

    clicked = pyqtSignal()
    context_requested = pyqtSignal(QPoint)
    checked_changed = pyqtSignal(bool)

    def __init__(self, title: str, *, checkable: bool = False, parent=None):
        super().__init__(parent)
        self._selected = False
        self._checked = False
        self._suspend_checkbox_signal = False
        self._rounded_artwork = False
        self._source_pixmap = QPixmap()
        self._dominant_color: tuple[int, int, int] | None = None
        self.setObjectName("photoTile")
        self.setFixedSize(QSize(_PHOTO_TILE_W, _PHOTO_TILE_H))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._has_image = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.image_frame = QFrame(self)
        self.image_frame.setObjectName("photoTileImageFrame")
        self.image_frame.setFixedHeight(_PHOTO_IMAGE_BOX)
        image_layout = QVBoxLayout(self.image_frame)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)

        self.image_label = QLabel(self.image_frame)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(QSize(_PHOTO_IMAGE_BOX, _PHOTO_IMAGE_BOX))
        image_layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_frame)

        self.caption_frame = QFrame(self)
        self.caption_frame.setObjectName("photoTileCaptionFrame")
        caption_layout = QHBoxLayout(self.caption_frame)
        caption_layout.setContentsMargins(2, 0, 2, 0)
        caption_layout.setSpacing(6)

        self.checkbox: QCheckBox | None = None
        if checkable:
            self.checkbox = QCheckBox(self.caption_frame)
            self.checkbox.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.checkbox.toggled.connect(self._on_checkbox_toggled)
            caption_layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.title_label = ScrollingLabel(title, self.caption_frame)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setFixedHeight(20)
        caption_layout.addWidget(self.title_label, 1)

        layout.addWidget(self.caption_frame)
        self._set_placeholder()
        self._apply_style()

    def setPixmap(self, pixmap: QPixmap | None) -> None:
        self._source_pixmap = pixmap if pixmap and not pixmap.isNull() else QPixmap()
        self._render_pixmap()
        self._apply_style()

    def setDominantColor(self, color: tuple[int, int, int] | None) -> None:
        self._dominant_color = color
        self._apply_style()

    def set_rounded_artwork(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._rounded_artwork == enabled:
            return
        self._rounded_artwork = enabled
        self._render_pixmap()

    def setTitle(self, title: str) -> None:
        self.title_label.setText(title)

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def setChecked(self, checked: bool) -> None:
        self._checked = checked
        if self.checkbox is not None and self.checkbox.isChecked() != checked:
            self._suspend_checkbox_signal = True
            self.checkbox.setChecked(checked)
            self._suspend_checkbox_signal = False
        self._apply_style()

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(a0)

    def contextMenuEvent(self, a0):
        if a0:
            self.context_requested.emit(a0.globalPos())
            a0.accept()
            return
        super().contextMenuEvent(a0)

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._checked = checked
        self._apply_style()
        if not self._suspend_checkbox_signal:
            self.checked_changed.emit(checked)

    def _render_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            self._set_placeholder()
            return

        self._has_image = True
        scaled = scale_pixmap_for_display(
            self._source_pixmap,
            _PHOTO_IMAGE_SIZE,
            _PHOTO_IMAGE_SIZE,
            widget=self.image_label,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        if self._rounded_artwork:
            scaled = rounded_artwork_pixmap(
                scaled,
                nested_artwork_radius(Metrics.BORDER_RADIUS_XL, 10),
            )
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")
        self.image_label.setStyleSheet(
            f"background: transparent; border: none; border-radius: {Metrics.BORDER_RADIUS}px;"
        )

    def _set_placeholder(self) -> None:
        self._has_image = False
        px = glyph_pixmap("photo", 40, Colors.TEXT_TERTIARY)
        if px:
            self.image_label.setPixmap(px)
            self.image_label.setText("")
        else:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Photo")
            self.image_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.image_label.setStyleSheet(f"""
            background: {Colors.ACCENT_MUTED};
            border: none;
            border-radius: {Metrics.BORDER_RADIUS}px;
            color: {Colors.TEXT_TERTIARY};
        """)

    def _apply_style(self) -> None:
        border = Colors.ACCENT_BORDER if self._selected else Colors.BORDER_SUBTLE
        bg = Colors.ACCENT_MUTED if self._selected else Colors.SURFACE_RAISED
        hover_bg = Colors.ACCENT_DIM if self._selected else Colors.SURFACE_ACTIVE
        image_bg = Colors.SURFACE_ALT
        title_color = Colors.TEXT_PRIMARY

        if not self._selected and self._has_image and self._dominant_color:
            r, g, b = display_accent_rgb(
                self._dominant_color,
                background=Colors.BG_DARK,
                target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
            )
            bg = f"rgba({r}, {g}, {b}, 30)"
            hover_bg = f"rgba({r}, {g}, {b}, 55)"
            border = f"rgba({r}, {g}, {b}, 25)"
            surface_rgb = _blend_rgb(
                (r, g, b),
                _css_hex_rgb(Colors.BG_DARK) or (26, 26, 46),
                30 / 255,
            )
            tr, tg, tb = text_rgb_for_background(surface_rgb)
            title_color = f"rgb({tr}, {tg}, {tb})"

        self.setStyleSheet(f"""
            QFrame#photoTile {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {Metrics.BORDER_RADIUS_XL}px;
            }}
            QFrame#photoTile:hover {{
                background: {hover_bg};
                border: 1px solid {border};
            }}
        """)
        self.image_frame.setStyleSheet(f"""
            QFrame#photoTileImageFrame {{
                background: {image_bg};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS}px;
            }}
        """)
        self.caption_frame.setStyleSheet("""
            QFrame#photoTileCaptionFrame {
                background: transparent;
                border: none;
                border-radius: 0px;
            }
        """)
        self.title_label.setStyleSheet(
            f"border: none; background: transparent; color: {title_color};"
        )
        if self.checkbox is not None:
            self.checkbox.setStyleSheet(f"""
                QCheckBox {{
                    background: transparent;
                    spacing: 0px;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                    border-radius: 5px;
                    border: 1px solid {Colors.BORDER};
                    background: {Colors.SURFACE_ALT};
                }}
                QCheckBox::indicator:checked {{
                    border: 1px solid {Colors.ACCENT_BORDER};
                    background: {Colors.ACCENT};
                }}
            """)
