import logging
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QLabel, QFrame, QVBoxLayout
from PyQt6.QtGui import QFont, QPixmap, QCursor, QImage
from ..imgMaker import find_image_by_imgId, get_artworkdb_cached
from ..styles import Colors, FONT_FAMILY, Metrics, scaled, font_scaled
from ..glyphs import glyph_pixmap
from .scrollingLabel import ScrollingLabel

log = logging.getLogger(__name__)


class MusicBrowserGridItem(QFrame):
    """A clickable grid item that displays album art, title, and subtitle."""
    clicked = pyqtSignal(dict)  # Emits item data when clicked

    def __init__(self, title: str, subtitle: str, mhiiLink, item_data: dict | None = None):
        super().__init__()
        self.title_text = title
        self.subtitle_text = subtitle
        self.mhiiLink = mhiiLink
        self.item_data = item_data or {"title": title, "subtitle": subtitle, "artwork_id_ref": mhiiLink}
        self._destroyed = False  # Track if widget is being destroyed

        self.setFixedSize(QSize(Metrics.GRID_ITEM_W, Metrics.GRID_ITEM_H))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._setupStyle()

        self.gridItemLayout = QVBoxLayout(self)
        self.gridItemLayout.setContentsMargins(scaled(10), scaled(10), scaled(10), scaled(8))
        self.gridItemLayout.setSpacing(scaled(6))

        self.worker = None
        self._cancellation_token = None

        # Album art
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(QSize(Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE))
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {Colors.SHADOW_LIGHT};
            border-radius: {Metrics.BORDER_RADIUS}px;
        """)
        self.gridItemLayout.addWidget(self.img_label)

        if mhiiLink is not None:
            self.loadImage()
        else:
            self._setPlaceholderImage()

        # Title
        self.title_label = ScrollingLabel(title)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_PRIMARY};")
        self.title_label.setFixedHeight(scaled(20))
        self.gridItemLayout.addWidget(self.title_label)

        # Subtitle
        self.subtitle_label = ScrollingLabel(subtitle)
        self.subtitle_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_SECONDARY};")
        self.subtitle_label.setFixedHeight(scaled(18))
        self.gridItemLayout.addWidget(self.subtitle_label)

    def _setupStyle(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_XL}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame:hover {{
                background-color: {Colors.SURFACE_HOVER};
                border: 1px solid {Colors.BORDER};
            }}
        """)

    def _setPlaceholderImage(self):
        """Set a placeholder when no artwork is available."""
        px = glyph_pixmap("music", font_scaled(40), Colors.TEXT_TERTIARY)
        if px:
            self.img_label.setPixmap(px)
        else:
            self.img_label.setText("♪")
            self.img_label.setFont(QFont(FONT_FAMILY, font_scaled(40)))
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {Colors.ACCENT_MUTED};
            border-radius: {Metrics.BORDER_RADIUS}px;
            color: {Colors.TEXT_TERTIARY};
        """)

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_data)
        super().mousePressEvent(a0)

    def cleanup(self):
        """Mark widget as destroyed and cancel any pending work."""
        self._destroyed = True
        if self.worker:
            self.worker.cancel()
            try:
                self.worker.signals.result.disconnect(self._applyImage)
            except (TypeError, RuntimeError):
                pass
            self.worker = None

    def loadImage(self):
        from ..app import Worker, ThreadPoolSingleton, DeviceManager

        if self.worker:
            self.worker.cancel()

        self._cancellation_token = DeviceManager.get_instance().cancellation_token

        self.worker = Worker(self._loadImageData, self.mhiiLink)
        self.worker.signals.result.connect(self._applyImage)
        ThreadPoolSingleton.get_instance().start(self.worker)

    def _loadImageData(self, mhiiLink):
        """Load image data in worker thread."""
        from ..app import DeviceManager
        import os

        device = DeviceManager.get_instance()

        if device.cancellation_token.is_cancelled():
            return None

        if not device.device_path:
            return None

        artworkdb_path = device.artworkdb_path
        artwork_folder = device.artwork_folder_path

        if not artworkdb_path or not os.path.exists(artworkdb_path):
            return None

        if device.cancellation_token.is_cancelled():
            return None

        artworkdb_data, imgid_index = get_artworkdb_cached(artworkdb_path)

        if device.cancellation_token.is_cancelled():
            return None

        result = find_image_by_imgId(artworkdb_data, artwork_folder, mhiiLink, imgid_index)

        if result is None:
            return {"error": True, "artwork_id_ref": mhiiLink}

        pil_image, dcol, album_colors = result
        return {"pil_image": pil_image, "dcol": dcol, "album_colors": album_colors}

    def _applyImage(self, result):
        """Apply loaded image data on main thread."""
        if self._destroyed:
            return

        try:
            if not self.isVisible() and not self.parent():
                return
        except RuntimeError:
            return

        from ..app import DeviceManager

        current_token = DeviceManager.get_instance().cancellation_token
        if self._cancellation_token is not current_token:
            return

        if result is None or result.get("error"):
            self._setPlaceholderImage()
            return

        pil_image = result.get("pil_image")
        dcol = result.get("dcol")

        if pil_image is not None:
            # Convert PIL image to QPixmap safely by copying the data
            # ImageQt can cause crashes if PIL image goes out of scope
            pil_image = pil_image.convert("RGBA")
            data = pil_image.tobytes("raw", "RGBA")
            qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
            # Copy the QImage to own the data (prevents crash when data goes out of scope)
            qimage = qimage.copy()
            pixmap = QPixmap.fromImage(qimage)
            pixmap = pixmap.scaled(
                Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(pixmap)
            self.img_label.setStyleSheet(f"""
                border: none;
                background: transparent;
                border-radius: {Metrics.BORDER_RADIUS}px;
            """)

            # Store dominant color and album colors for downstream use
            if dcol:
                self.item_data["dominant_color"] = dcol
            album_colors = result.get("album_colors")
            if album_colors:
                self.item_data["album_colors"] = album_colors

            # Tint background with dominant color
            if dcol:
                r, g, b = dcol
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
