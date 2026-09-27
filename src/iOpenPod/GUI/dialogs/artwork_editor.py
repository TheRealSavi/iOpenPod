"""Bounded artwork selection and square cropping for Track metadata editing."""

from __future__ import annotations

import hashlib
from collections import Counter
from math import floor
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QCoreApplication,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.artwork_import import ArtworkImportController
from iOpenPod.app.library_workspace import TrackArtworkEdit
from iOpenPod.GUI.presentation.i18n.text import english_count_fallback
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
)
from iPodDB.library import ArtworkAsset, ArtworkPixels, Track
from storage import HostPath

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider

_MAX_DIMENSION = 8192
_MAX_PIXEL_AREA = 32 * 1024 * 1024
_OUTPUT_EDGE = 1200
_PREVIEW_EDGE = 256
_COMPARE_EDGE = 4096
_CHOICE_ICON_EDGE = 132


def artwork_pixels_from_image(image: QImage) -> ArtworkPixels:
    """Copy a QImage into the GUI-free, tightly packed RGB888 edit contract."""

    if image.isNull():
        raise ValueError("Artwork cannot be empty.")
    _validate_dimensions(image.width(), image.height())
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    raw = bytes(rgb.constBits())
    row_size = rgb.width() * 3
    stride = rgb.bytesPerLine()
    packed = b"".join(
        raw[offset : offset + row_size]
        for offset in range(0, stride * rgb.height(), stride)
    )
    return ArtworkPixels(rgb.width(), rgb.height(), packed)


def _validate_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > _MAX_DIMENSION
        or height > _MAX_DIMENSION
        or width * height > _MAX_PIXEL_AREA
    ):
        raise ValueError(
            "Artwork must be at most 8192 pixels per side and 32 megapixels."
        )


def _image_from_pixels(pixels: ArtworkPixels) -> QImage:
    return QImage(
        pixels.rgb888,
        pixels.width,
        pixels.height,
        pixels.width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


class _SquareCropCanvas(QWidget):
    """Pan-and-zoom canvas whose visible center square is the chosen crop."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image.copy()
        self._zoom = 1.0
        self._offset = QPointF()
        self._drag_origin: QPoint | None = None
        self.setObjectName("artworkCropCanvas")
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(1.0, min(4.0, zoom))
        self._constrain_offset()
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._offset = QPointF()
        self.update()

    def cropped_image(self) -> QImage:
        crop, displayed, scale = self._geometry()
        source = QRectF(
            (crop.left() - displayed.left()) / scale,
            (crop.top() - displayed.top()) / scale,
            crop.width() / scale,
            crop.height() / scale,
        ).intersected(QRectF(self._image.rect()))
        side = max(1, floor(min(source.width(), source.height())))
        left = max(0, round(source.center().x() - side / 2))
        top = max(0, round(source.center().y() - side / 2))
        left = min(left, self._image.width() - side)
        top = min(top, self._image.height() - side)
        cropped = self._image.copy(left, top, side, side)
        target = min(_OUTPUT_EDGE, side)
        if target != side:
            cropped = cropped.scaled(
                target,
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return cropped

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        crop, displayed, _scale = self._geometry()
        painter.drawImage(displayed, self._image)

        shade = QColor(0, 0, 0, 150)
        painter.fillRect(QRectF(0, 0, self.width(), crop.top()), shade)
        painter.fillRect(
            QRectF(0, crop.bottom(), self.width(), self.height() - crop.bottom()),
            shade,
        )
        painter.fillRect(QRectF(0, crop.top(), crop.left(), crop.height()), shade)
        painter.fillRect(
            QRectF(
                crop.right(), crop.top(), self.width() - crop.right(), crop.height()
            ),
            shade,
        )
        painter.setPen(QPen(self.palette().highlight().color(), 2))
        painter.drawRect(crop)
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        for fraction in (1 / 3, 2 / 3):
            x = crop.left() + crop.width() * fraction
            y = crop.top() + crop.height() * fraction
            painter.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
            painter.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            point = event.position().toPoint()
            delta = point - self._drag_origin
            self._drag_origin = point
            self._offset += QPointF(delta)
            self._constrain_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and self._drag_origin is not None
        ):
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._constrain_offset()
        super().resizeEvent(event)

    def _crop_rect(self) -> QRectF:
        side = max(1.0, min(self.width(), self.height()) - 32.0)
        return QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )

    def _geometry(self) -> tuple[QRectF, QRectF, float]:
        crop = self._crop_rect()
        base_scale = max(
            crop.width() / self._image.width(),
            crop.height() / self._image.height(),
        )
        scale = base_scale * self._zoom
        width = self._image.width() * scale
        height = self._image.height() * scale
        displayed = QRectF(
            crop.center().x() - width / 2 + self._offset.x(),
            crop.center().y() - height / 2 + self._offset.y(),
            width,
            height,
        )
        return crop, displayed, scale

    def _constrain_offset(self) -> None:
        crop = self._crop_rect()
        base_scale = max(
            crop.width() / self._image.width(),
            crop.height() / self._image.height(),
        )
        width = self._image.width() * base_scale * self._zoom
        height = self._image.height() * base_scale * self._zoom
        x_limit = max(0.0, (width - crop.width()) / 2)
        y_limit = max(0.0, (height - crop.height()) / 2)
        self._offset.setX(max(-x_limit, min(x_limit, self._offset.x())))
        self._offset.setY(max(-y_limit, min(y_limit, self._offset.y())))


class ArtworkCropDialog(QDialog):
    """Collect one square crop without creating a temporary host file."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("artworkCropDialog")
        self.setWindowTitle(self.tr("Crop Artwork"))
        self.resize(620, 690)
        self.setMinimumSize(500, 570)
        layout = QVBoxLayout(self)
        message = QLabel(
            self.tr("Drag to position the image, then use the slider to zoom."), self
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        self._canvas = _SquareCropCanvas(image, self)
        layout.addWidget(self._canvas, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel(self.tr("Zoom"), self))
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setObjectName("artworkCropZoom")
        slider.setRange(100, 400)
        slider.setValue(100)
        slider.valueChanged.connect(self._zoom_changed)
        controls.addWidget(slider, 1)
        reset = ActionButton(self.tr("Reset View"), self)

        def reset_crop() -> None:
            slider.setValue(100)
            self._canvas.reset_view()

        reset.clicked.connect(reset_crop)
        controls.addWidget(reset)
        layout.addLayout(controls)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ActionButton(
            QCoreApplication.translate("CommonActions", "Cancel"), self
        )
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        use = ActionButton(self.tr("Use Artwork"), self, kind=ActionButtonKind.PRIMARY)
        use.setDefault(True)
        use.clicked.connect(self.accept)
        footer.addWidget(use)
        layout.addLayout(footer)

    def pixels(self) -> ArtworkPixels:
        return artwork_pixels_from_image(self._canvas.cropped_image())

    @Slot(int)
    def _zoom_changed(self, value: int) -> None:
        self._canvas.set_zoom(value / 100)


class ConsolidateArtworkDialog(QDialog):
    """Choose one unique selected cover for every selected Track."""

    def __init__(
        self,
        artwork_ids: tuple[int, ...],
        assets: tuple[ArtworkAsset, ...],
        provider: ArtworkPixmapProvider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("consolidateArtworkDialog")
        self.setWindowTitle(
            QCoreApplication.translate("CommonActions", "Consolidate Artwork")
        )
        self.resize(720, 560)
        self.setMinimumSize(520, 420)
        self._artwork_ids = artwork_ids
        self._assets = {asset.artwork_id: asset for asset in assets}
        self._provider = provider
        self._selected_artwork_id: int | None = None
        self._fingerprints: dict[int, tuple[int, int, bytes]] = {}
        self._icons: dict[tuple[int, int, bytes], QIcon] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel(
            QCoreApplication.translate("CommonActions", "Consolidate Artwork"), self
        )
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        explanation = QLabel(
            self.tr(
                "Choose one of the selected covers to assign to every selected "
                "Track. Exactly identical images appear only once."
            ),
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self._grid = QListWidget(self)
        self._grid.setObjectName("artworkConsolidationGrid")
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setWrapping(True)
        self._grid.setSpacing(8)
        self._grid.setIconSize(QSize(_CHOICE_ICON_EDGE, _CHOICE_ICON_EDGE))
        self._grid.setGridSize(QSize(168, 184))
        self._grid.itemClicked.connect(self._choose_item)
        self._grid.itemActivated.connect(self._choose_item)
        layout.addWidget(self._grid, 1)

        self._status = QLabel(self)
        self._status.setObjectName("artworkConsolidationStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ActionButton(
            QCoreApplication.translate("CommonActions", "Cancel"), self
        )
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        layout.addLayout(footer)

        if provider is not None:
            provider.artworkChanged.connect(self._artwork_changed)
            provider.cleared.connect(self._artwork_cleared)
        self._refresh()

    @property
    def selected_artwork_id(self) -> int | None:
        return self._selected_artwork_id

    def _refresh(self) -> None:
        counts = Counter(self._artwork_ids)
        groups: dict[tuple[str, object], tuple[int, QIcon | None, int]] = {}
        for artwork_id in dict.fromkeys(self._artwork_ids):
            if artwork_id == 0:
                continue
            fingerprint = self._fingerprint(artwork_id)
            if fingerprint is None:
                key: tuple[str, object] = ("identity", artwork_id)
                icon = None
            else:
                key = ("pixels", fingerprint)
                icon = self._icons[fingerprint]
            retained = groups.get(key)
            if retained is None:
                groups[key] = (artwork_id, icon, counts[artwork_id])
            else:
                groups[key] = (
                    retained[0],
                    retained[1],
                    retained[2] + counts[artwork_id],
                )

        self._grid.clear()
        for artwork_id, icon, use_count in groups.values():
            label = english_count_fallback(
                "Used by %n Track(s)",
                self.tr("Used by %n Track(s)", "", use_count),
                use_count,
            )
            if icon is None:
                label = f"{self.tr('Preview unavailable')}\n{label}"
            item = QListWidgetItem(label)
            if icon is not None:
                item.setIcon(icon)
            item.setData(Qt.ItemDataRole.UserRole, artwork_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(self.tr("Use this artwork for every selected Track"))
            self._grid.addItem(item)

        unique_count = len(groups)
        selected_count = len(self._artwork_ids)
        self._status.setText(
            self.tr("Unique artwork: %1 · Selected Tracks: %2")
            .replace("%1", str(unique_count))
            .replace("%2", str(selected_count))
        )

    def _fingerprint(self, artwork_id: int) -> tuple[int, int, bytes] | None:
        retained = self._fingerprints.get(artwork_id)
        if retained is not None:
            return retained
        asset = self._assets.get(artwork_id)
        pixels = asset.pixels if asset is not None else None
        if pixels is None and self._provider is not None:
            pixels = self._provider.pixels(
                artwork_id,
                _COMPARE_EDGE,
                self.devicePixelRatioF(),
            )
        if pixels is None:
            return None
        fingerprint = (
            pixels.width,
            pixels.height,
            hashlib.sha256(pixels.rgb888).digest(),
        )
        self._fingerprints[artwork_id] = fingerprint
        if fingerprint not in self._icons:
            image = _image_from_pixels(pixels).scaled(
                _CHOICE_ICON_EDGE,
                _CHOICE_ICON_EDGE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icons[fingerprint] = QIcon(QPixmap.fromImage(image))
        return fingerprint

    @Slot(QListWidgetItem)
    def _choose_item(self, item: QListWidgetItem) -> None:
        artwork_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(artwork_id, int) or artwork_id == 0:
            return
        self._selected_artwork_id = artwork_id
        self.accept()

    @Slot(object)
    def _artwork_changed(self, artwork_id: object) -> None:
        if isinstance(artwork_id, int) and artwork_id in self._artwork_ids:
            self._refresh()

    @Slot()
    def _artwork_cleared(self) -> None:
        self._fingerprints.clear()
        self._icons.clear()
        self._refresh()

    def done(self, result: int) -> None:
        provider = self._provider
        self._provider = None
        if provider is not None:
            provider.artworkChanged.disconnect(self._artwork_changed)
            provider.cleared.disconnect(self._artwork_cleared)
        super().done(result)


class ArtworkEditor(QWidget):
    """Edit one shared artwork value for the metadata dialog's Track selection."""

    modifiedChanged = Signal()

    def __init__(
        self,
        tracks: tuple[Track, ...],
        assets: tuple[ArtworkAsset, ...],
        provider: ArtworkPixmapProvider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._artwork_ids = tuple(track.artwork_id for track in tracks)
        self._assets = {asset.artwork_id: asset for asset in assets}
        self._provider = provider
        self._pending: TrackArtworkEdit | None = None
        self._source_label = ""
        self._importer = ArtworkImportController(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._preview = QLabel(self)
        self._preview.setObjectName("metadataArtworkImage")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(_PREVIEW_EDGE, _PREVIEW_EDGE)
        layout.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignHCenter)

        self._status = QLabel(self)
        self._status.setObjectName("metadataArtworkStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setFixedWidth(520)
        layout.addWidget(self._status, 0, Qt.AlignmentFlag.AlignHCenter)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._choose_button = ActionButton(
            self.tr("Choose Artwork…"), self, kind=ActionButtonKind.PRIMARY
        )
        self._choose_button.setObjectName("chooseTrackArtwork")
        self._choose_button.clicked.connect(self._choose)
        buttons.addWidget(self._choose_button)
        self._clear_button = ActionButton(
            self.tr("Clear Artwork"), self, kind=ActionButtonKind.DANGER
        )
        self._clear_button.setObjectName("clearTrackArtwork")
        self._clear_button.clicked.connect(self.clear_artwork)
        buttons.addWidget(self._clear_button)
        self._consolidate_button = ActionButton(self.tr("Consolidate Artwork…"), self)
        self._consolidate_button.setObjectName("consolidateTrackArtwork")
        self._consolidate_button.hide()
        self._consolidate_button.clicked.connect(self._consolidate)
        buttons.addWidget(self._consolidate_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addStretch(1)

        if provider is not None:
            provider.artworkChanged.connect(self._artwork_changed)
            provider.cleared.connect(self._refresh)
        self._importer.busyChanged.connect(self._import_busy_changed)
        self._importer.finished.connect(self._import_finished)
        self._importer.failed.connect(self._import_failed)
        self._refresh()

    @property
    def busy(self) -> bool:
        return self._importer.busy

    def is_modified(self) -> bool:
        return self._pending is not None

    def edit(self) -> TrackArtworkEdit | None:
        return self._pending

    def reset(self) -> None:
        self._importer.cancel()
        if self._pending is None:
            return
        self._pending = None
        self._source_label = ""
        self._refresh()
        self.modifiedChanged.emit()

    def set_pending_artwork(
        self, pixels: ArtworkPixels, source_label: str = ""
    ) -> None:
        """Stage owned pixels; also supports paste/drop and deterministic tests."""

        self._pending = TrackArtworkEdit(pixels)
        self._source_label = source_label
        self._refresh()
        self.modifiedChanged.emit()

    def set_pending_artwork_id(self, artwork_id: int) -> None:
        """Stage one existing selected cover for the complete Track selection."""

        if artwork_id == 0 or artwork_id not in self._artwork_ids:
            raise ValueError("Choose artwork from the current Track selection.")
        self._pending = TrackArtworkEdit(None, source_artwork_id=artwork_id)
        self._source_label = ""
        self._refresh()
        self.modifiedChanged.emit()

    def clear_artwork(self) -> None:
        self._importer.cancel()
        self._pending = (
            None if set(self._artwork_ids) == {0} else TrackArtworkEdit(None)
        )
        self._source_label = ""
        self._refresh()
        self.modifiedChanged.emit()

    def _choose(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose Track Artwork"),
            "",
            self.tr(
                "Images (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tif *.tiff);;"
                "All Files (*)"
            ),
        )
        if not path:
            return
        self._importer.start(HostPath(Path(path)))

    def _consolidate(self) -> None:
        dialog = ConsolidateArtworkDialog(
            self._artwork_ids,
            tuple(self._assets.values()),
            self._provider,
            self,
        )
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.selected_artwork_id is not None
        ):
            self.set_pending_artwork_id(dialog.selected_artwork_id)

    def _import_finished(self, value: object, source_name: str) -> None:
        if not isinstance(value, ArtworkPixels):
            return
        crop = ArtworkCropDialog(_image_from_pixels(value), self)
        if crop.exec() == QDialog.DialogCode.Accepted:
            self.set_pending_artwork(crop.pixels(), source_name)

    def _import_failed(self, detail: str) -> None:
        self._refresh()
        QMessageBox.warning(self, self.tr("Artwork unavailable"), detail)

    def _import_busy_changed(self, busy: bool) -> None:
        self._choose_button.setEnabled(not busy)
        self._clear_button.setEnabled(not busy)
        self._consolidate_button.setEnabled(not busy)
        if busy:
            self._show_placeholder(self.tr("Reading artwork…"))
            self._status.setText(
                self.tr("Capturing and decoding the selected Host image.")
            )
        else:
            self._refresh()

    def shutdown(self) -> None:
        self._importer.shutdown()

    def _refresh(self) -> None:
        self._consolidate_button.setVisible(self._has_multiple_unique_artworks())
        if self._pending is not None:
            pixels = self._pending.pixels
            if self._pending.source_artwork_id is not None:
                artwork_id = self._pending.source_artwork_id
                pixels = self._pixels_for_id(artwork_id, _PREVIEW_EDGE)
                if pixels is None:
                    self._show_placeholder(self.tr("Artwork preview unavailable"))
                else:
                    self._show_image(_image_from_pixels(pixels))
                self._status.setText(
                    self.tr(
                        "Selected artwork will be assigned to every selected Track."
                    )
                )
                return
            if pixels is None:
                self._show_placeholder(self.tr("No artwork"))
                self._status.setText(self.tr("Artwork will be cleared when applied."))
                return
            self._show_image(_image_from_pixels(pixels))
            detail = (
                self.tr("New crop — %1 x %2 px")
                .replace("%1", str(pixels.width))
                .replace("%2", str(pixels.height))
            )
            if self._source_label:
                detail = f"{self._source_label} • {detail}"
            self._status.setText(detail)
            return

        unique = tuple(dict.fromkeys(self._artwork_ids))
        if len(unique) != 1:
            common = self._common_pixels(unique)
            if common is not None:
                self._show_image(_image_from_pixels(common))
                self._status.setText(
                    self.tr("Current artwork shared by all selected Tracks.")
                )
                return
            self._show_placeholder(self.tr("Multiple artwork values"))
            self._status.setText(
                self.tr("Choose one image to assign it to every selected Track.")
            )
            return
        artwork_id = next(iter(unique), 0)
        if artwork_id == 0:
            self._show_placeholder(self.tr("No artwork"))
            self._status.setText(self.tr("The selected Track has no assigned artwork."))
            return
        asset = self._assets.get(artwork_id)
        if asset is not None:
            self._show_image(_image_from_pixels(asset.pixels))
            self._status.setText(
                self.tr("Artwork — %1 x %2 px")
                .replace("%1", str(asset.pixels.width))
                .replace("%2", str(asset.pixels.height))
            )
            return
        provider = self._provider
        pixmap = (
            None
            if provider is None
            else provider.pixmap(artwork_id, _PREVIEW_EDGE, self.devicePixelRatioF())
        )
        if pixmap is None:
            self._show_placeholder(self.tr("Artwork preview unavailable"))
        else:
            self._show_pixmap(pixmap)
        self._status.setText(
            self.tr("Current iPod artwork • reference %1").replace(
                "%1", str(artwork_id)
            )
        )

    def _common_pixels(self, artwork_ids: tuple[int, ...]) -> ArtworkPixels | None:
        """Return one image only when every distinct relationship matches exactly."""

        resolved: list[ArtworkPixels] = []
        complete = True
        for artwork_id in artwork_ids:
            if artwork_id == 0:
                complete = False
                continue
            pixels = self._pixels_for_id(artwork_id, _PREVIEW_EDGE)
            if pixels is None:
                complete = False
            else:
                resolved.append(pixels)
        if not complete or not resolved:
            return None
        first = resolved[0]
        return first if all(pixels == first for pixels in resolved[1:]) else None

    def _has_multiple_unique_artworks(self) -> bool:
        """Show consolidation only after distinct selected pixels are known."""

        artwork_ids = tuple(dict.fromkeys(self._artwork_ids))
        if len(artwork_ids) <= 1:
            return False
        if 0 in artwork_ids:
            return any(artwork_id != 0 for artwork_id in artwork_ids)

        unique_pixels: list[ArtworkPixels] = []
        for artwork_id in artwork_ids:
            pixels = self._pixels_for_id(artwork_id, _COMPARE_EDGE)
            if pixels is None:
                continue
            if all(pixels != retained for retained in unique_pixels):
                unique_pixels.append(pixels)
                if len(unique_pixels) > 1:
                    return True
        return False

    def _pixels_for_id(
        self, artwork_id: int, logical_size: int
    ) -> ArtworkPixels | None:
        asset = self._assets.get(artwork_id)
        if asset is not None:
            return asset.pixels
        if self._provider is None:
            return None
        return self._provider.pixels(
            artwork_id,
            logical_size,
            self.devicePixelRatioF(),
        )

    def _show_image(self, image: QImage) -> None:
        self._show_pixmap(QPixmap.fromImage(image))

    def _show_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setText("")
        self._preview.setPixmap(scaled)

    def _show_placeholder(self, text: str) -> None:
        self._preview.setPixmap(QPixmap())
        self._preview.setText(text)

    def _artwork_changed(self, artwork_id: int) -> None:
        if self._pending is None and artwork_id in self._artwork_ids:
            self._refresh()
