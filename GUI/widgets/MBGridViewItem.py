import logging
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QLabel, QFrame, QVBoxLayout
from PyQt6.QtGui import QFont, QPixmap, QCursor, QImage
from ..imgMaker import find_image_by_imgId, get_artworkdb_cached
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
        self.item_data = item_data or {"title": title, "subtitle": subtitle, "mhiiLink": mhiiLink}
        self._destroyed = False  # Track if widget is being destroyed

        self.setFixedSize(QSize(180, 240))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._setupStyle()

        self.gridItemLayout = QVBoxLayout(self)
        self.gridItemLayout.setContentsMargins(8, 8, 8, 8)
        self.gridItemLayout.setSpacing(4)

        self.worker = None
        self._cancellation_token = None

        # Album art
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(QSize(164, 164))
        self.img_label.setStyleSheet("""
            border: none;
            background: rgba(0,0,0,30);
            border-radius: 8px;
        """)
        self.gridItemLayout.addWidget(self.img_label)

        if mhiiLink is not None:
            self.loadImage()
        else:
            self._setPlaceholderImage()

        # Title
        self.title_label = ScrollingLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setStyleSheet("border: none; background: transparent; color: white;")
        self.title_label.setFixedHeight(20)
        self.gridItemLayout.addWidget(self.title_label)

        # Subtitle
        self.subtitle_label = ScrollingLabel(subtitle)
        self.subtitle_label.setFont(QFont("Segoe UI", 10))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setStyleSheet("border: none; background: transparent; color: rgba(255,255,255,180);")
        self.subtitle_label.setFixedHeight(18)
        self.gridItemLayout.addWidget(self.subtitle_label)

    def _setupStyle(self):
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,15);
                border: none;
                border-radius: 12px;
                color: white;
            }
            QFrame:hover {
                background-color: rgba(255,255,255,30);
            }
        """)

    def _setPlaceholderImage(self):
        """Set a placeholder when no artwork is available."""
        self.img_label.setText("🎵")
        self.img_label.setFont(QFont("Segoe UI", 48))
        self.img_label.setStyleSheet("""
            border: none;
            background: rgba(64,156,255,50);
            border-radius: 8px;
            color: rgba(255,255,255,100);
        """)

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_data)
        super().mousePressEvent(a0)

    def cleanup(self):
        """Mark widget as destroyed and cancel any pending work."""
        log.debug(f"cleanup() called for item: {self.title_text}")
        self._destroyed = True
        if self.worker:
            log.debug(f"  Cancelling worker for: {self.title_text}")
            self.worker.cancel()
            try:
                self.worker.signals.result.disconnect(self._applyImage)
                log.debug(f"  Disconnected signal for: {self.title_text}")
            except (TypeError, RuntimeError) as e:
                log.debug(f"  Signal disconnect failed: {e}")
            self.worker = None

    def loadImage(self):
        from ..app import Worker, ThreadPoolSingleton, DeviceManager
        log.debug(f"loadImage() called for: {self.title_text}, mhiiLink={self.mhiiLink}")

        if self.worker:
            log.debug(f"  Cancelling previous worker for: {self.title_text}")
            self.worker.cancel()

        self._cancellation_token = DeviceManager.get_instance().cancellation_token

        self.worker = Worker(self._loadImageData, self.mhiiLink)
        self.worker.signals.result.connect(self._applyImage)
        ThreadPoolSingleton.get_instance().start(self.worker)
        log.debug(f"  Worker started for: {self.title_text}")

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
            return {"error": True, "mhiiLink": mhiiLink}

        pil_image, dcol = result
        return {"pil_image": pil_image, "dcol": dcol}

    def _applyImage(self, result):
        """Apply loaded image data on main thread."""
        log.debug(f"_applyImage() called for: {self.title_text}, destroyed={self._destroyed}")

        # Check if widget was destroyed while loading
        if self._destroyed:
            log.debug(f"  Widget destroyed, skipping: {self.title_text}")
            return

        try:
            # Additional safety check
            if not self.isVisible() and not self.parent():
                log.debug(f"  Widget not visible/no parent, skipping: {self.title_text}")
                return
        except RuntimeError as e:
            log.debug(f"  RuntimeError checking visibility: {e}")
            return

        from ..app import DeviceManager

        current_token = DeviceManager.get_instance().cancellation_token
        if self._cancellation_token is not current_token:
            log.debug(f"  Cancellation token mismatch, skipping: {self.title_text}")
            return

        log.debug(f"  Applying image for: {self.title_text}, result={result is not None}")

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
                164, 164,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(pixmap)
            self.img_label.setStyleSheet("""
                border: none;
                background: transparent;
                border-radius: 8px;
            """)

            # Tint background with dominant color
            if dcol:
                r, g, b = dcol
                self.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba({r}, {g}, {b}, 40);
                        border: none;
                        border-radius: 12px;
                        color: white;
                    }}
                    QFrame:hover {{
                        background-color: rgba({r}, {g}, {b}, 70);
                    }}
                """)
