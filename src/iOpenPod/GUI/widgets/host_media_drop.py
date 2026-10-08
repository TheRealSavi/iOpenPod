"""External Host file drops over the main Library browser only."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from iOpenPod.app.host_media_library import classify_host_media_file


def dropped_host_paths(mime: QMimeData | None) -> tuple[Path, ...]:
    """Accept local media and explicit links for validation by the scan worker."""

    if mime is None or not mime.hasUrls():
        return ()
    paths: list[Path] = []
    for url in mime.urls():
        if not url.isLocalFile():
            return ()
        path = Path(url.toLocalFile())
        try:
            supported = path.is_absolute() and (
                path.is_dir()
                or (path.is_file() and classify_host_media_file(path) is not None)
                # A file alias need not share its target's suffix. Broken links
                # also need a scan diagnostic rather than an unexplained no-op.
                or path.is_symlink()
            )
        except OSError:
            return ()
        if not supported:
            return ()
        if path not in paths:
            paths.append(path)
    return tuple(paths)


class HostMediaDropTarget(QObject):
    """Intercept external URL drops, leaving internal Library drags untouched."""

    pathsDropped = Signal(object)

    def __init__(self, surface: QWidget, available: Callable[[], bool]) -> None:
        super().__init__(surface)
        self._surface = surface
        self._available = available
        self._pending = False
        self._closed = False
        self._overlay = QLabel(surface)
        self._overlay.setObjectName("hostMediaDropOverlay")
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay.setTextFormat(Qt.TextFormat.PlainText)
        self._overlay.setWordWrap(True)
        self._overlay.setStyleSheet(
            "QLabel#hostMediaDropOverlay { background: palette(base);"
            " color: palette(highlight); border: 3px dashed palette(highlight);"
            " border-radius: 12px; padding: 24px; font-size: 22px; }"
        )
        self.clear()
        surface.setAcceptDrops(True)
        # Item views may accept drops themselves. Filter their viewports too,
        # including children created later, without changing internal drag modes.
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        surface.destroyed.connect(self.shutdown)

    def shutdown(self) -> None:
        """Detach the application filter before the Library widgets are destroyed."""

        if self._closed:
            return
        self._closed = True
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

    def clear(self) -> None:
        self._overlay.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() not in (
            QEvent.Type.Resize,
            QEvent.Type.Hide,
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.DragLeave,
            QEvent.Type.Drop,
        ):
            return False
        if watched is self._surface:
            if event.type() == QEvent.Type.Resize:
                self._overlay.setGeometry(
                    self._surface.rect().adjusted(12, 12, -12, -12)
                )
            elif event.type() == QEvent.Type.Hide:
                self.clear()
        if not isinstance(watched, QWidget) or not (
            watched is self._surface or self._surface.isAncestorOf(watched)
        ):
            return False
        if event.type() == QEvent.Type.DragLeave:
            self.clear()
            return False
        if not isinstance(event, (QDragEnterEvent, QDragMoveEvent, QDropEvent)):
            return False
        # Qt can return null here (notably for external drag sources), despite
        # the non-nullable PySide signatures. Preserve that runtime contract.
        mime = cast("QMimeData | None", event.mimeData())
        source = cast("QObject | None", event.source())
        if source is not None or mime is None or not mime.hasUrls():
            return False
        paths = (
            dropped_host_paths(mime)
            if not self._pending and self._surface.isVisible() and self._available()
            else ()
        )
        if not paths or not event.possibleActions() & Qt.DropAction.CopyAction:
            self.clear()
            event.ignore()
            return True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            self.clear()
            self._pending = True
            # Finish the native drag before opening the modal recursion question.
            QTimer.singleShot(0, lambda: self._deliver(paths))
        else:
            self._overlay.setText(
                self.tr("Drop to Sync with Host")
                + "\n\n"
                + self.tr("Folders, audio, video, photos, and playlists")
            )
            self._overlay.setGeometry(self._surface.rect().adjusted(12, 12, -12, -12))
            self._overlay.show()
            self._overlay.raise_()
        return True

    def _deliver(self, paths: tuple[Path, ...]) -> None:
        self._pending = False
        if not self._closed and self._surface.isVisible() and self._available():
            self.pathsDropped.emit(paths)
