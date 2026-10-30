"""The Original iOpenPod application icon, retained as packaged assets."""

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, qVersion
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QImage, QPainter, QPixmap

# Only compensate versions whose xdg-toplevel-icon implementation was inspected.
# Recheck before extending; see docs/research/window-icon-wayland-alpha.md (#289).
_STRAIGHT_ALPHA_WAYLAND_VERSIONS = frozenset({"6.11.2", "6.12.0"})


class _WaylandWindowIconEngine(QIconEngine):
    """Compensate native icon buffers while retaining ordinary Qt painting."""

    def __init__(self, source: QIcon) -> None:
        super().__init__()
        self._source = QIcon(source)

    def clone(self) -> QIconEngine:
        return _WaylandWindowIconEngine(self._source)

    def isNull(self) -> bool:
        return self._source.isNull()

    def availableSizes(
        self,
        mode: QIcon.Mode = QIcon.Mode.Normal,
        state: QIcon.State = QIcon.State.Off,
    ) -> list[QSize]:
        return self._source.availableSizes(mode, state)

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return self._source.actualSize(size, mode, state)

    def paint(
        self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State
    ) -> None:
        # Client decorations paint directly, without the broken native handoff.
        self._source.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode, state)

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        image = self._source.pixmap(size, 1.0, mode, state).toImage()
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        # Qt paints into straight ARGB32, then sends those bytes as premultiplied
        # wl_shm ARGB8888. Supply already-premultiplied bytes in the same straight
        # format so its native-size copy preserves the intended buffer exactly.
        image.reinterpretAsFormat(QImage.Format.Format_ARGB32)
        return QPixmap.fromImage(image, Qt.ImageConversionFlag.NoFormatConversion)


def application_icon() -> QIcon:
    """Return the native window icon, including the known Qt Wayland workaround."""

    directory = Path(__file__).parents[2] / "assets" / "icons"
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(str(directory / f"icon-{size}.png"))
    if (
        QGuiApplication.platformName().startswith("wayland")
        and qVersion() in _STRAIGHT_ALPHA_WAYLAND_VERSIONS
    ):
        return QIcon(_WaylandWindowIconEngine(icon))
    return icon
