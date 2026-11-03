"""Clickable rating stars that retain exact imported 0-100 values until edited."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class StarRating(QLabel):
    """Use the Player's whole-star selection and click-again-to-clear interaction."""

    def __init__(self, rating: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rating = rating
        self._hover_stars: int | None = None
        self.setObjectName("starRating")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setProperty("ratingHover", False)
        self.setToolTip(
            self.tr("Click a star to set the rating; click the selected star to clear")
        )
        self._refresh()

    @property
    def rating(self) -> int:
        """Return the exact shared rating, including untouched fractional stars."""
        return self._rating

    def _refresh(self) -> None:
        stars = (
            round(self._rating / 20) if self._hover_stars is None else self._hover_stars
        )
        self.setText(("★" * stars) + ("☆" * (5 - stars)))
        self.setAccessibleDescription(
            self.tr("%1 of 5 stars").replace("%1", f"{self._rating / 20:g}")
        )

    def _set_hover(self, stars: int | None) -> None:
        if stars == self._hover_stars:
            return
        self._hover_stars = stars
        self.setProperty("ratingHover", stars is not None)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self._refresh()

    def _stars_at(self, pointer_x: float) -> int | None:
        metrics = self.fontMetrics()
        widths = tuple(
            metrics.horizontalAdvance(character) for character in self.text()
        )
        left = (self.width() - sum(widths)) / 2
        if not left <= pointer_x < left + sum(widths):
            return None
        for stars, width in enumerate(widths, start=1):
            left += width
            if pointer_x < left:
                return stars
        return None

    def _select(self, stars: int) -> None:
        self._rating = 0 if stars == round(self._rating / 20) else stars * 20
        self._set_hover(None)
        self._refresh()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._set_hover(self._stars_at(event.position().x()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._set_hover(None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            stars = self._stars_at(event.position().x())
            if stars is not None:
                self._select(stars)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        current = round(self._rating / 20)
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_5:
            stars = key - Qt.Key.Key_0
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            stars = min(5, max(0, current + (1 if key == Qt.Key.Key_Right else -1)))
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            stars = 0 if key == Qt.Key.Key_Home else 5
        else:
            super().keyPressEvent(event)
            return
        self._select(stars)
        event.accept()
