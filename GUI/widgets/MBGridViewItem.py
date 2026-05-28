from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..artwork_rendering import (
    nested_artwork_radius,
    rounded_artwork_pixmap,
)
from ..glyphs import glyph_pixmap
from ..hidpi import scale_pixmap_for_display
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    current_accent_rgb,
    display_accent_rgb,
    text_rgb_for_background,
)
from .scrollingLabel import ScrollingLabel


@dataclass(frozen=True)
class GridItemModel:
    """Immutable view model for a grid card.

    Attributes:
        title: Primary display text.
        subtitle: Secondary display text.
        artwork_id: Artwork identifier used by the active artwork pipeline.
        payload: Event payload emitted to consumers when the card is clicked.
        image: Artwork image if already available.
        dominant_color: Dominant artwork color.
        album_colors: Derived artwork palette.
    """
    title: str
    subtitle: str
    artwork_id: int | None
    payload: Mapping[str, Any] | None = None
    image: Image.Image | None = None
    dominant_color: tuple[int, int, int] | None = None
    album_colors: dict[str, Any] | None = None


@dataclass
class GridItemRenderState:
    """Computed styling state derived from the current model."""
    display_dominant_color: tuple[int, int, int] | None = None
    display_album_colors: dict[str, Any] | None = None


class MusicBrowserGridItem(QFrame):
    """Reusable, clickable grid card for albums, artists, and genres."""
    clicked = pyqtSignal(dict)
    context_requested = pyqtSignal(dict, QPoint)

    def __init__(self):
        """Initialize an empty widget that can be populated and recycled."""
        super().__init__()

        self._model: GridItemModel | None = None
        self._base_item_data: dict[str, Any] = {}
        self.item_data: dict[str, Any] = {}
        self.artwork_id: int | None = None

        self._image: Image.Image | None = None
        self._dominant_color: tuple[int, int, int] | None = None
        self._album_colors: dict[str, Any] | None = None
        self._render_state: GridItemRenderState | None = None
        self._applied_artwork_id: int | None = None
        self._rounded_artwork = False
        self._selected = False

        self.setFixedSize(QSize(Metrics.GRID_ITEM_W, Metrics.GRID_ITEM_H))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._setupStyle()

        self.gridItemLayout = QVBoxLayout(self)
        self.gridItemLayout.setContentsMargins((10), (10), (10), (10))
        self.gridItemLayout.setSpacing(6)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(QSize(Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE))
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {Colors.SURFACE_ALT};
            border-radius: {Metrics.BORDER_RADIUS}px;
        """)
        self.gridItemLayout.addWidget(self.img_label)

        self.title_label = ScrollingLabel("")
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_PRIMARY};")
        self.title_label.setFixedHeight(20)
        self.gridItemLayout.addWidget(self.title_label)

        self.subtitle_label = ScrollingLabel("")
        self.subtitle_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_SECONDARY};")
        self.subtitle_label.setFixedHeight(18)
        self.gridItemLayout.addWidget(self.subtitle_label)

        self._render_placeholder()

    def set_model(self, model: GridItemModel) -> None:
        """Apply a new view model to the widget."""
        keep_existing_art = (
            model.image is None
            and model.artwork_id is not None
            and model.artwork_id == self._applied_artwork_id
            and self._image is not None
        )

        self._model = model
        self.artwork_id = model.artwork_id
        self._base_item_data = self._build_item_data(model)
        self.item_data = dict(self._base_item_data)

        if model.image is not None:
            self._image = model.image
            self._dominant_color = model.dominant_color
            self._album_colors = model.album_colors
            self._applied_artwork_id = model.artwork_id
        elif not keep_existing_art:
            self._clear_art_state()

        self._render_state = None
        self._render_model()

    def _build_item_data(self, model: GridItemModel) -> dict[str, Any]:
        payload = dict(model.payload or {})
        payload.setdefault("title", model.title)
        payload.setdefault("subtitle", model.subtitle)
        payload.setdefault("artwork_id_ref", model.artwork_id)
        return payload

    def _clear_art_state(self) -> None:
        self._image = None
        self._dominant_color = None
        self._album_colors = None
        self._applied_artwork_id = None

    def _setupStyle(self) -> None:
        if self._selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {Colors.ACCENT_MUTED};
                    border: 2px solid {Colors.ACCENT_BORDER};
                    border-radius: {Metrics.BORDER_RADIUS_XL}px;
                    color: {Colors.TEXT_PRIMARY};
                }}
                QFrame:hover {{
                    background-color: {Colors.ACCENT_DIM};
                    border: 2px solid {Colors.ACCENT_BORDER};
                }}
            """)
            return

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_XL}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame:hover {{
                background-color: {Colors.SURFACE_ACTIVE};
                border: 1px solid {Colors.BORDER};
            }}
        """)

    def _render_placeholder(self) -> None:
        """Render the default empty-art state."""
        r, g, b = display_accent_rgb(
            current_accent_rgb(),
            background=Colors.BG_DARK,
            target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
        )
        bg = f"rgba({r}, {g}, {b}, 14)"

        px = glyph_pixmap("music", Metrics.FONT_ICON_LG, Colors.TEXT_TERTIARY)
        if px:
            self.img_label.setPixmap(px)
        else:
            self.img_label.setText("\u266a")
            self.img_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_LG))
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {bg};
            border-radius: {Metrics.BORDER_RADIUS}px;
            color: {Colors.TEXT_TERTIARY};
        """)

    def _render_image(self, pil_image: Image.Image) -> None:
        """Render a PIL image into the artwork label."""
        data = pil_image.tobytes("raw", "RGBA")
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
        qimage = qimage.copy()
        pixmap = scale_pixmap_for_display(
            QPixmap.fromImage(qimage),
            Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE,
            widget=self.img_label,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        if self._rounded_artwork:
            pixmap = rounded_artwork_pixmap(
                pixmap,
                nested_artwork_radius(Metrics.BORDER_RADIUS_XL, 10),
            )
        self.img_label.setPixmap(pixmap)
        self.img_label.setStyleSheet(f"""
            border: none;
            background: transparent;
            border-radius: {Metrics.BORDER_RADIUS}px;
        """)

    def _apply_color_theme(self, render_state: GridItemRenderState) -> None:
        """Apply theme styling derived from the artwork."""
        if self._selected:
            self._setupStyle()
            return

        if not render_state.display_dominant_color:
            return

        r, g, b = render_state.display_dominant_color
        self.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({r}, {g}, {b}, 30);
                border: 1px solid rgba({r}, {g}, {b}, 25);
                border-radius: {Metrics.BORDER_RADIUS_XL}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame:hover {{
                background-color: rgba({r}, {g}, {b}, 55);
                border: 1px solid rgba({r}, {g}, {b}, 45);
            }}
        """)

    def _render_model(self) -> None:
        """Render the current model state to the widget."""
        if self._model is None:
            self.title_label.setText("")
            self.subtitle_label.setText("")
            self._setupStyle()
            self.item_data = {}
            self._render_placeholder()
            return

        self.title_label.setText(self._model.title)
        self.subtitle_label.setText(self._model.subtitle)
        self.item_data = dict(self._base_item_data)
        self._setupStyle()

        if self._image is not None:
            self._render_image(self._image.convert("RGBA"))
            self._render_state = self._compute_render_state(
                self._dominant_color,
                self._album_colors,
            )

            if self._dominant_color:
                self.item_data["dominant_color"] = self._dominant_color
            if self._render_state.display_dominant_color:
                self.item_data["display_dominant_color"] = self._render_state.display_dominant_color
            if self._album_colors:
                self.item_data["album_colors"] = self._album_colors
            if self._render_state.display_album_colors:
                self.item_data["display_album_colors"] = self._render_state.display_album_colors

            self._apply_color_theme(self._render_state)
        else:
            self._render_state = GridItemRenderState()
            self._render_placeholder()

    def _compute_render_state(
        self,
        dcol: tuple[int, int, int] | None,
        album_colors: dict[str, Any] | None,
    ) -> GridItemRenderState:
        """Compute theme colors used for rendering."""
        if not dcol:
            return GridItemRenderState()

        display_color = display_accent_rgb(
            dcol,
            background=Colors.BG_DARK,
            target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
        )

        display_album = None
        if album_colors and display_color:
            text = text_rgb_for_background(display_color)
            secondary = (
                (225, 230, 238)
                if text == (255, 255, 255)
                else (45, 50, 60)
            )
            display_album = dict(album_colors)
            display_album.update({
                "bg": display_color,
                "text": text,
                "text_secondary": secondary,
            })

        return GridItemRenderState(
            display_dominant_color=display_color,
            display_album_colors=display_album,
        )

    def apply_image_result(
        self,
        pil_image: Image.Image | None,
        dominant_color: tuple[int, int, int] | None = None,
        album_colors: dict[str, Any] | None = None,
    ) -> None:
        """Apply artwork loaded asynchronously for the current model."""
        try:
            if not self.isVisible() and not self.parent():
                return
        except RuntimeError:
            return

        if pil_image is not None:
            self._image = pil_image
            self._dominant_color = dominant_color
            self._album_colors = album_colors
            self._applied_artwork_id = self.artwork_id
        else:
            self._clear_art_state()

        self._render_model()

    def set_rounded_artwork(self, enabled: bool) -> None:
        """Update whether artwork pixmaps should render with rounded corners."""
        enabled = bool(enabled)
        if self._rounded_artwork == enabled:
            return
        self._rounded_artwork = enabled
        if self._model is not None:
            self._render_model()

    def setSelected(self, selected: bool) -> None:
        """Update the visual selected state for file-browser style grids."""
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        if self._model is not None:
            self._render_model()
        else:
            self._setupStyle()

    def isSelected(self) -> bool:
        return self._selected

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_data)
        super().mousePressEvent(a0)

    def contextMenuEvent(self, a0):
        if a0:
            self.context_requested.emit(self.item_data, a0.globalPos())
            a0.accept()
            return
        super().contextMenuEvent(a0)
