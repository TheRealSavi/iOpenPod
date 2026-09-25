"""Reusable QWidget surface for placeholder or eventual real artwork."""

from PySide6.QtCore import QEvent, QRectF
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_collage,
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class ArtworkView(QWidget):
    """Paint a lazy single cover or collection collage in logical coordinates."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        seed: int = 0,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._seed = seed
        self._artwork_id = 0
        self._artwork_ids: tuple[int, int, int, int] | None = None
        self.setAccessibleName(self.tr("Placeholder artwork"))
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self.update)

    def set_seed(self, seed: int) -> None:
        if seed == self._seed:
            return
        self._seed = seed
        self.update()

    def set_artwork_id(self, artwork_id: int) -> None:
        normalized = max(0, artwork_id)
        if normalized == self._artwork_id and self._artwork_ids is None:
            return
        self._artwork_id = normalized
        self._artwork_ids = None
        self._refresh_accessible_name()
        self.update()

    def set_artwork_ids(self, artwork_ids: tuple[int, int, int, int]) -> None:
        """Retain all four collection tiles, including empty artwork slots."""

        if artwork_ids == self._artwork_ids:
            return
        self._artwork_ids = artwork_ids
        self._artwork_id = 0
        self._refresh_accessible_name()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._artwork_ids is not None:
            paint_artwork_collage(
                painter,
                rect,
                self._artwork_ids,
                self._seed,
                self._theme_manager.tokens,
                self._artwork_provider,
                self.devicePixelRatioF(),
            )
            return
        pixmap = self._artwork_provider.pixmap(
            self._artwork_id,
            max(1, min(self.width(), self.height())),
            self.devicePixelRatioF(),
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                self._seed,
                self._theme_manager.tokens,
                float(LAYOUT.radius_control),
            )
        else:
            paint_artwork_pixmap(
                painter,
                rect,
                pixmap,
                self._theme_manager.tokens,
                float(LAYOUT.radius_control),
            )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh_accessible_name()
        super().changeEvent(event)

    def _refresh_accessible_name(self) -> None:
        self.setAccessibleName(
            self.tr("Collection artwork")
            if self._artwork_ids is not None
            else self.tr("Album artwork")
            if self._artwork_id > 0
            else self.tr("Placeholder artwork")
        )

    def _theme_changed(self, _theme: str) -> None:
        self.update()

    def _artwork_changed(self, artwork_id: int) -> None:
        if (
            artwork_id in self._artwork_ids
            if self._artwork_ids is not None
            else artwork_id == self._artwork_id
        ):
            self.update()
