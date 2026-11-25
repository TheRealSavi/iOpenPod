"""The first visible window while the desktop session is being composed."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from iOpenPod.GUI.presentation.application_icon import application_pixmap


class _StartupProgress(QProgressBar):
    """Show one dot per startup stage while retaining native progress accessibility."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setRange(0, 3)
        self.setTextVisible(False)
        self.setValue(0)
        self.setFixedSize(32, 8)
        self._ink = self.palette().windowText().color()

    def paintEvent(self, event: QPaintEvent) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._ink)
            for stage in range(self.maximum()):
                painter.setOpacity(1.0 if stage < self.value() else 0.45)
                painter.drawEllipse(1 + stage * 12, 1, 6, 6)


class StartupWindow(QWidget):
    firstPaint = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("startupWindow")
        self.setWindowTitle("iOpenPod")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        self.setScreen(screen)
        self._painted = False
        # Desktop composition replaces the application palette, font and stylesheet.
        # Capture the Host appearance before the first paint.
        palette = self.palette()
        font = self.font()
        font_size = (
            f"{font.pixelSize()}px"
            if font.pixelSize() > 0
            else f"{font.pointSizeF():g}pt"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"""
            QWidget#startupWindow {{ background-color: {palette.window().color().name()}; }}
            QLabel {{
                background: transparent;
                color: {palette.windowText().color().name()};
                font-family: "{font.family()}";
                font-size: {font_size};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(12)
        logo = QLabel(self)
        logo.setPixmap(application_pixmap(64, screen.devicePixelRatio()))
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Reserve a line for the saved language before its translator is installed.
        self._label.setMinimumWidth(
            max(228, 28 * self._label.fontMetrics().averageCharWidth())
        )
        layout.addWidget(self._label)
        self.progress = _StartupProgress(self)
        layout.addWidget(self.progress, alignment=Qt.AlignmentFlag.AlignCenter)
        self._retranslate()
        self.setFixedSize(self.sizeHint())
        # Place the client on the chosen screen before Qt creates its native frame.
        self.move(screen.geometry().center() - self.rect().center())

    def show_centered(self) -> None:
        """Center the decorated frame before the window becomes visible."""
        self.create()
        center = self.screen().geometry().center()
        frame = self.frameGeometry()
        self.move(frame.topLeft() + (center - frame.center()))
        self.show()
        # Some platforms report their final decoration margins only after mapping.
        handle = self.windowHandle()
        frame = handle.frameGeometry()
        handle.setFramePosition(frame.topLeft() + (center - frame.center()))

    def _retranslate(self) -> None:
        text = self.tr("Starting iOpenPod…")
        self._label.setText(text)
        self.progress.setAccessibleName(text)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._painted:
            self._painted = True
            self.firstPaint.emit()
