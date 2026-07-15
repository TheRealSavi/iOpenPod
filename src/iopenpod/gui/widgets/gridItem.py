from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QCursor, QFont, QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..artwork_rendering import nested_artwork_radius, rounded_artwork_pixmap
from ..glyphs import glyph_pixmap
from ..hidpi import scale_pixmap_for_display
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    checkbox_css,
    current_accent_rgb,
    display_accent_rgb,
    text_rgb_for_background,
)
from .scrollingLabel import ScrollingLabel

GridImage = Image.Image | QPixmap


@dataclass
class GridItemModel:
    """Everything the shared grid card needs to render one record."""

    title: str
    subtitle: str = ""
    artwork_id: int | None = None
    payload: Mapping[str, Any] | None = None
    image: GridImage | None = None
    dominant_color: tuple[int, int, int] | None = None
    album_colors: dict[str, Any] | None = None
    key: Hashable | None = None
    checked: bool = False
    placeholder_glyph: str = "music"


@dataclass
class GridItemRenderState:
    """Computed styling state derived from the current model."""

    display_dominant_color: tuple[int, int, int] | None = None
    display_album_colors: dict[str, Any] | None = None


_GRID_CARD_TINT_DARK = (30, 25, 55, 45)
_GRID_CARD_TINT_LIGHT = (48, 40, 82, 68)


def _grid_metric(name: str, fallback: int) -> int:
    """Read current grid tokens while remaining compatible with older themes."""

    return int(getattr(Metrics, name, fallback))


def _grid_card_tint_alphas() -> tuple[int, int | None, int, int | None]:
    values = (
        _GRID_CARD_TINT_LIGHT
        if getattr(Colors, "_active_mode", "dark") == "light"
        else _GRID_CARD_TINT_DARK
    )
    if hasattr(Metrics, "GRID_CARD_RADIUS"):
        return values[0], None, values[2], None
    return values


class GridItem(QFrame):
    """Pooled grid card shared by music, selective-sync, and photo browsers."""

    clicked = pyqtSignal()
    context_requested = pyqtSignal(QPoint)
    checked_changed = pyqtSignal(bool)

    def __init__(
        self,
        title: str = "",
        *,
        checkable: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("unifiedGridItem")
        self._model: GridItemModel | None = None
        self._image: GridImage | None = None
        self._dominant_color: tuple[int, int, int] | None = None
        self._album_colors: dict[str, Any] | None = None
        self._render_state = GridItemRenderState()
        self._applied_artwork_id: int | None = None
        self._selected = False
        self._checked = False
        self._rounded_artwork = False
        self._suspend_checkbox_signal = False
        self.item_data: dict[str, Any] = {}
        self.artwork_id: int | None = None

        self.setFixedSize(QSize(Metrics.GRID_ITEM_W, Metrics.GRID_ITEM_H))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QVBoxLayout(self)
        margin = _grid_metric("GRID_CARD_MARGIN", 10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(_grid_metric("GRID_CARD_SPACING", 6))

        self.image_frame = QFrame(self)
        self.image_frame.setObjectName("unifiedGridItemImageFrame")
        self.image_frame.setFixedSize(
            QSize(Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE)
        )
        image_layout = QVBoxLayout(self.image_frame)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)

        self.image_label = QLabel(self.image_frame)
        self.img_label = self.image_label
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(QSize(Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE))
        image_layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_frame)

        self.caption_frame = QFrame(self)
        self.caption_frame.setObjectName("unifiedGridItemCaptionFrame")
        caption_layout = QHBoxLayout(self.caption_frame)
        caption_layout.setContentsMargins(0, 0, 0, 0)
        caption_layout.setSpacing(6)

        self.checkbox: QCheckBox | None = None
        if checkable:
            self.checkbox = QCheckBox(self.caption_frame)
            self.checkbox.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.checkbox.toggled.connect(self._on_checkbox_toggled)
            caption_layout.addWidget(
                self.checkbox,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.title_label = ScrollingLabel("", self.caption_frame)
        self.title_label.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_GRID_TITLE, QFont.Weight.Medium)
        )
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_label.setFixedHeight(_grid_metric("GRID_TEXT_HEIGHT", 22))
        text_layout.addWidget(self.title_label)

        self.subtitle_label = ScrollingLabel("", self.caption_frame)
        self.subtitle_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_GRID_SUBTITLE))
        self.subtitle_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.subtitle_label.setFixedHeight(_grid_metric("GRID_SUBTITLE_HEIGHT", 20))
        text_layout.addWidget(self.subtitle_label)
        caption_layout.addLayout(text_layout, 1)
        layout.addWidget(self.caption_frame)

        if title:
            self.setModel(GridItemModel(title=title))
        else:
            self._render_model()

    def setModel(self, model: GridItemModel) -> None:
        keep_existing_art = (
            model.image is None
            and model.artwork_id is not None
            and model.artwork_id == self._applied_artwork_id
            and self._image is not None
        )
        self._model = model
        self.artwork_id = model.artwork_id
        self.item_data = self._build_item_data(model)
        self._checked = bool(model.checked)
        model_image = model.image
        if isinstance(model_image, QPixmap) and model_image.isNull():
            model_image = None
            model.image = None
        if model_image is not None:
            self._image = model_image
            self._dominant_color = model.dominant_color
            self._album_colors = model.album_colors
            self._applied_artwork_id = model.artwork_id
        elif not keep_existing_art:
            self._clear_art_state()
        self._sync_checkbox()
        self._render_model()

    def set_model(self, model: GridItemModel) -> None:
        """Compatibility alias for the former music-only card interface."""

        self.setModel(model)

    @staticmethod
    def _build_item_data(model: GridItemModel) -> dict[str, Any]:
        payload = dict(model.payload or {})
        payload.setdefault("title", model.title)
        payload.setdefault("subtitle", model.subtitle)
        payload.setdefault("artwork_id_ref", model.artwork_id)
        return payload

    def setTitle(self, title: str) -> None:
        if self._model is None:
            self.setModel(GridItemModel(title=title))
            return
        self._model.title = title
        self.item_data = self._build_item_data(self._model)
        self.title_label.setText(title)

    def setChecked(self, checked: bool) -> None:
        self._checked = bool(checked)
        if self._model is not None:
            self._model.checked = self._checked
        self._sync_checkbox()
        self._apply_style()

    def isChecked(self) -> bool:
        return self._checked

    def _sync_checkbox(self) -> None:
        if self.checkbox is None or self.checkbox.isChecked() == self._checked:
            return
        self._suspend_checkbox_signal = True
        self.checkbox.setChecked(self._checked)
        self._suspend_checkbox_signal = False

    def setPixmap(self, pixmap: QPixmap | None) -> None:
        self.applyImageResult(
            pixmap,
            self._dominant_color,
            self._album_colors,
        )

    def setDominantColor(self, color: tuple[int, int, int] | None) -> None:
        self._dominant_color = color
        if self._model is not None:
            self._model.dominant_color = color
        self._render_model()

    def applyImageResult(
        self,
        image: GridImage | None,
        dominant_color: tuple[int, int, int] | None = None,
        album_colors: dict[str, Any] | None = None,
    ) -> None:
        try:
            if not self.isVisible() and not self.parent():
                return
        except RuntimeError:
            return
        if image is None or (isinstance(image, QPixmap) and image.isNull()):
            self._clear_art_state()
        else:
            self._image = image
            self._dominant_color = dominant_color
            self._album_colors = album_colors
            self._applied_artwork_id = self.artwork_id
        if self._model is not None:
            self._model.image = self._image
            self._model.dominant_color = self._dominant_color
            self._model.album_colors = self._album_colors
        self._render_model()

    def apply_image_result(
        self,
        image: GridImage | None,
        dominant_color: tuple[int, int, int] | None = None,
        album_colors: dict[str, Any] | None = None,
    ) -> None:
        """Compatibility alias for the former music-only card interface."""

        self.applyImageResult(image, dominant_color, album_colors)

    def _clear_art_state(self) -> None:
        self._image = None
        self._dominant_color = None
        self._album_colors = None
        self._applied_artwork_id = None

    def _render_model(self) -> None:
        model = self._model
        if model is None:
            self.title_label.setText("")
            self.subtitle_label.setText("")
            self.subtitle_label.hide()
            self.item_data = {}
            self._render_placeholder("music")
            self._apply_style()
            return

        self.title_label.setText(model.title)
        self.subtitle_label.setText(model.subtitle)
        self.subtitle_label.setVisible(bool(model.subtitle))
        self.item_data = self._build_item_data(model)
        if self._image is None:
            self._render_state = GridItemRenderState()
            self._render_placeholder(model.placeholder_glyph)
        else:
            self._render_image(self._image)
            self._render_state = self._compute_render_state(
                self._dominant_color,
                self._album_colors,
            )
            if self._dominant_color:
                self.item_data["dominant_color"] = self._dominant_color
            if self._render_state.display_dominant_color:
                self.item_data["display_dominant_color"] = (
                    self._render_state.display_dominant_color
                )
            if self._album_colors:
                self.item_data["album_colors"] = self._album_colors
            if self._render_state.display_album_colors:
                self.item_data["display_album_colors"] = (
                    self._render_state.display_album_colors
                )
        self._apply_style()

    def _render_placeholder(self, glyph_name: str) -> None:
        r, g, b = display_accent_rgb(
            current_accent_rgb(),
            background=Colors.BG_DARK,
            target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
        )
        pixmap = glyph_pixmap(glyph_name, Metrics.FONT_ICON_LG, Colors.TEXT_TERTIARY)
        if pixmap:
            self.image_label.setPixmap(pixmap)
            self.image_label.setText("")
        else:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(glyph_name.title())
            self.image_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.image_label.setStyleSheet(f"""
            background: rgba({r}, {g}, {b}, 14);
            border: none;
            border-radius: {_grid_metric("GRID_ART_RADIUS", Metrics.BORDER_RADIUS)}px;
            color: {Colors.TEXT_TERTIARY};
        """)

    def _render_image(self, image: GridImage) -> None:
        if isinstance(image, Image.Image):
            rgba_image = image.convert("RGBA")
            data = rgba_image.tobytes("raw", "RGBA")
            qimage = QImage(
                data,
                rgba_image.width,
                rgba_image.height,
                QImage.Format.Format_RGBA8888,
            ).copy()
            pixmap = QPixmap.fromImage(qimage)
        else:
            pixmap = image
        scaled = scale_pixmap_for_display(
            pixmap,
            Metrics.GRID_ART_SIZE,
            Metrics.GRID_ART_SIZE,
            widget=self.image_label,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        if self._rounded_artwork:
            scaled = rounded_artwork_pixmap(
                scaled,
                nested_artwork_radius(
                    _grid_metric("GRID_CARD_RADIUS", Metrics.BORDER_RADIUS_XL),
                    10,
                ),
            )
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")
        self.image_label.setStyleSheet(
            "background: transparent; border: none; "
            f"border-radius: {_grid_metric('GRID_ART_RADIUS', Metrics.BORDER_RADIUS)}px;"
        )

    @staticmethod
    def _compute_render_state(
        dominant_color: tuple[int, int, int] | None,
        album_colors: dict[str, Any] | None,
    ) -> GridItemRenderState:
        if not dominant_color:
            return GridItemRenderState()
        display_color = display_accent_rgb(
            dominant_color,
            background=Colors.BG_DARK,
            target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
        )
        display_album = None
        if album_colors:
            text = text_rgb_for_background(display_color)
            secondary = (225, 230, 238) if text == (255, 255, 255) else (45, 50, 60)
            display_album = dict(album_colors)
            display_album.update(
                {
                    "bg": display_color,
                    "text": text,
                    "text_secondary": secondary,
                }
            )
        return GridItemRenderState(display_color, display_album)

    def _apply_color_theme(self, render_state: GridItemRenderState) -> None:
        """Compatibility entry point retained for focused style tests."""

        self._render_state = render_state
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            background = Colors.ACCENT_MUTED
            hover = Colors.ACCENT_DIM
            border = f"2px solid {Colors.ACCENT_BORDER}"
            hover_border = border
            title_color = Colors.TEXT_PRIMARY
        elif self._render_state.display_dominant_color:
            r, g, b = self._render_state.display_dominant_color
            normal_alpha, border_alpha, hover_alpha, hover_border_alpha = (
                _grid_card_tint_alphas()
            )
            background = f"rgba({r}, {g}, {b}, {normal_alpha})"
            hover = f"rgba({r}, {g}, {b}, {hover_alpha})"
            border = (
                "none"
                if border_alpha is None
                else f"1px solid rgba({r}, {g}, {b}, {border_alpha})"
            )
            hover_border = (
                "none"
                if hover_border_alpha is None
                else f"1px solid rgba({r}, {g}, {b}, {hover_border_alpha})"
            )
            title_color = Colors.TEXT_PRIMARY
        else:
            background = Colors.SURFACE_RAISED
            hover = Colors.SURFACE_ACTIVE
            border = f"1px solid {Colors.BORDER_SUBTLE}"
            hover_border = border
            title_color = Colors.TEXT_PRIMARY

        if self._selected:
            hover_border = border

        self.setStyleSheet(f"""
            QFrame#unifiedGridItem {{
                background-color: {background};
                border: {border};
                border-radius: {_grid_metric("GRID_CARD_RADIUS", Metrics.BORDER_RADIUS_XL)}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame#unifiedGridItem:hover {{
                background-color: {hover};
                border: {hover_border};
            }}
        """)
        self.image_frame.setStyleSheet(f"""
            QFrame#unifiedGridItemImageFrame {{
                background: {Colors.SURFACE_ALT};
                border: none;
                border-radius: {_grid_metric("GRID_ART_RADIUS", Metrics.BORDER_RADIUS)}px;
            }}
        """)
        self.caption_frame.setStyleSheet("""
            QFrame#unifiedGridItemCaptionFrame {
                background: transparent;
                border: none;
                border-radius: 0px;
            }
        """)
        self.title_label.setStyleSheet(
            f"border: none; background: transparent; color: {title_color};"
        )
        self.subtitle_label.setStyleSheet(
            f"border: none; background: transparent; color: {Colors.TEXT_SECONDARY};"
        )
        if self.checkbox is not None:
            self.checkbox.setStyleSheet(checkbox_css())

    def set_rounded_artwork(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._rounded_artwork == enabled:
            return
        self._rounded_artwork = enabled
        if self._image is not None:
            self._render_image(self._image)

    def setSelected(self, selected: bool) -> None:
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def isSelected(self) -> bool:
        return self._selected

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._checked = checked
        if self._model is not None:
            self._model.checked = checked
        self._apply_style()
        if not self._suspend_checkbox_signal:
            self.checked_changed.emit(checked)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(a0)

    def contextMenuEvent(self, a0: QContextMenuEvent | None) -> None:
        if a0:
            self.context_requested.emit(a0.globalPos())
            a0.accept()
            return
        super().contextMenuEvent(a0)
