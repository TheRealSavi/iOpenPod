"""Reusable palette-aware button primitives."""

from enum import StrEnum

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QRegion,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QPushButton,
    QToolButton,
    QWidget,
)

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class ActionButtonKind(StrEnum):
    """Semantic text-button treatments owned by the global theme."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    QUIET = "quiet"
    DANGER = "danger"
    INLINE = "inline"


class ActionButtonState(StrEnum):
    """Transient feedback states rendered by the global theme."""

    DEFAULT = "default"
    LOADING = "loading"
    ERROR = "error"
    SUCCESS = "success"


class IconButtonKind(StrEnum):
    """Semantic icon-button treatments owned by the global theme."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    QUIET = "quiet"
    SUBTLE = "subtle"
    DANGER = "danger"


def apply_action_button_kind(
    button: QAbstractButton,
    kind: ActionButtonKind,
) -> None:
    """Apply one global semantic treatment to a Qt-created button."""

    button.setProperty("kind", kind.value)
    button.setCursor(
        Qt.CursorShape.PointingHandCursor
        if button.isEnabled()
        else Qt.CursorShape.ArrowCursor
    )
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()


class ActionButton(QPushButton):
    """A text action with a pointer cursor only while it is actionable."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        kind: ActionButtonKind = ActionButtonKind.SECONDARY,
        state: ActionButtonState = ActionButtonState.DEFAULT,
        glyph: str | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._glyph = glyph
        self.set_kind(kind)
        self.set_state(state)
        self._refresh_cursor()
        self._refresh_icon()

    @property
    def kind(self) -> ActionButtonKind:
        return ActionButtonKind(str(self.property("kind")))

    @property
    def state(self) -> ActionButtonState:
        return ActionButtonState(str(self.property("state")))

    def set_kind(self, kind: ActionButtonKind) -> None:
        apply_action_button_kind(self, kind)
        self._refresh_icon()

    def set_state(self, state: ActionButtonState) -> None:
        self.setProperty("state", state.value)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.EnabledChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_icon()
        if event.type() == QEvent.Type.EnabledChange:
            self._refresh_cursor()
        super().changeEvent(event)

    def _refresh_icon(self) -> None:
        if self._glyph is None:
            return
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if self.kind is ActionButtonKind.PRIMARY
            else QPalette.ColorRole.BrightText
            if self.kind is ActionButtonKind.DANGER
            else QPalette.ColorRole.ButtonText
        )
        self.setIcon(
            glyph_icon(
                self._glyph,
                LAYOUT.icon_size,
                self.palette().color(group, role),
                self.devicePixelRatioF(),
            )
        )
        self.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))

    def _refresh_cursor(self) -> None:
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )


class IconButton(QToolButton):
    """A compact semantic button whose glyph follows its palette state."""

    def __init__(
        self,
        glyph: str,
        accessible_name: str,
        parent: QWidget | None = None,
        *,
        checkable: bool = False,
        kind: IconButtonKind = IconButtonKind.SECONDARY,
        theme_manager: ThemeManager | None = None,
        glyph_size: int | None = None,
    ) -> None:
        super().__init__(parent)
        if kind is IconButtonKind.PRIMARY and theme_manager is None:
            raise ValueError("A primary IconButton requires a ThemeManager")
        self._glyph = glyph
        self._glyph_size = glyph_size if glyph_size is not None else LAYOUT.icon_size
        self._kind = kind
        self._theme_manager = theme_manager
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)
        self.setCheckable(checkable)
        self.setProperty("iconButton", True)
        self.setProperty("kind", kind.value)
        self.setProperty("primary", kind is IconButtonKind.PRIMARY)
        self.setFixedSize(LAYOUT.icon_button_size, LAYOUT.icon_button_size)
        self.toggled.connect(self._refresh_icon)
        self._refresh_cursor()
        self._refresh_icon()

    def set_glyph(self, glyph: str) -> None:
        if glyph == self._glyph:
            return
        self._glyph = glyph
        self._refresh_icon()

    @property
    def kind(self) -> IconButtonKind:
        return self._kind

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.EnabledChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_icon()
        if event.type() == QEvent.Type.EnabledChange:
            self._refresh_cursor()
        super().changeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._kind is IconButtonKind.PRIMARY:
            self.setMask(QRegion(self.rect(), QRegion.RegionType.Ellipse))

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._kind is not IconButtonKind.PRIMARY:
            super().paintEvent(event)
            return
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        theme_manager = self._theme_manager
        if theme_manager is None:
            raise RuntimeError("A primary IconButton requires a ThemeManager")
        tokens = theme_manager.tokens
        color = QColor(tokens.accent)
        if self.isDown():
            color = QColor(tokens.accent_pressed)
        elif self.underMouse():
            color = QColor(tokens.accent_hover)
        if not self.isEnabled():
            color = QColor(tokens.surface_alt)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        circle = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.drawEllipse(circle)
        if self.hasFocus():
            focus_pen = QPen(QColor(tokens.focus))
            focus_pen.setWidthF(2.0)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle)
        icon_mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        icon_state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        self.icon().paint(
            painter,
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            icon_mode,
            icon_state,
        )

    def _refresh_cursor(self) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)

    def _refresh_icon(self) -> None:
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if self._kind is IconButtonKind.PRIMARY
            else QPalette.ColorRole.BrightText
            if self._kind is IconButtonKind.DANGER
            else QPalette.ColorRole.PlaceholderText
            if self._kind is IconButtonKind.SUBTLE
            else QPalette.ColorRole.Accent
            if self.isChecked()
            else QPalette.ColorRole.ButtonText
        )
        palette = (
            QApplication.palette()
            if self._kind is IconButtonKind.SUBTLE
            else self.palette()
        )
        self.setIcon(
            glyph_icon(
                self._glyph,
                self._glyph_size,
                palette.color(group, role),
                self.devicePixelRatioF(),
            )
        )
        self.setIconSize(QSize(self._glyph_size, self._glyph_size))


class NavigationButton(QPushButton):
    """A one-line source-list row with a recolorable glyph."""

    def __init__(
        self,
        text: str,
        glyph: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._glyph = glyph
        self.setCheckable(True)
        self.setProperty("navItem", True)
        self.setMinimumWidth(0)
        self.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
        self.toggled.connect(self._refresh_icon)
        self._refresh_cursor()
        self._refresh_icon()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.EnabledChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_icon()
        if event.type() == QEvent.Type.EnabledChange:
            self._refresh_cursor()
        super().changeEvent(event)

    def _refresh_cursor(self) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)

    def _refresh_icon(self) -> None:
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        role = (
            QPalette.ColorRole.Accent
            if self.isChecked()
            else QPalette.ColorRole.ButtonText
        )
        self.setIcon(
            glyph_icon(
                self._glyph,
                LAYOUT.icon_size,
                self.palette().color(group, role),
                self.devicePixelRatioF(),
            )
        )
