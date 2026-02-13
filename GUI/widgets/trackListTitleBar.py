from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QFrame, QLabel, QPushButton, QWidget
from PyQt6.QtGui import QFont


def _title_bar_css(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> str:
    """Generate the title bar stylesheet for given gradient colors."""
    return f"""
        QFrame {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba({r1},{g1},{b1},220), stop:1 rgba({r2},{g2},{b2},220));
            border: none;
            border-radius: 0px;
        }}
        QLabel {{
            font-weight: 600;
            font-size: 12px;
            color: white;
            background: transparent;
        }}
        QPushButton {{
            background-color: transparent;
            border: none;
            color: rgba(255,255,255,180);
            font-size: 14px;
            font-weight: bold;
            width: 26px;
            height: 26px;
            border-radius: 4px;
        }}
        QPushButton:hover {{
            background-color: rgba(255,255,255,25);
            color: white;
        }}
        QPushButton:pressed {{
            background-color: rgba(0,0,0,25);
        }}
    """


# Default blue gradient
_DEFAULT_CSS = _title_bar_css(64, 156, 255, 40, 110, 200)


class TrackListTitleBar(QFrame):
    """Draggable title bar for the track list panel."""

    def __init__(self, splitterToControl):
        super().__init__()
        self.splitter = splitterToControl
        self.dragging = False
        self.dragStartPos = QPoint()
        self.setMouseTracking(True)
        self.titleBarLayout = QHBoxLayout(self)
        self.titleBarLayout.setContentsMargins(12, 0, 8, 0)
        self.splitter.splitterMoved.connect(self.enforceMinHeight)

        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setFixedHeight(34)

        self.setStyleSheet(_DEFAULT_CSS)

        self.title = QLabel("Tracks")
        self.title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))

        self.button1 = QPushButton("▼")
        self.button1.setToolTip("Minimize")
        self.button1.clicked.connect(self._toggleMinimize)

        self.button2 = QPushButton("▲")
        self.button2.setToolTip("Maximize")
        self.button2.clicked.connect(self._toggleMaximize)

        self.titleBarLayout.addWidget(self.title)
        self.titleBarLayout.addStretch()
        self.titleBarLayout.addWidget(self.button1)
        self.titleBarLayout.addWidget(self.button2)

    def setTitle(self, title: str):
        """Set the title text."""
        self.title.setText(title)

    def setColor(self, r: int, g: int, b: int):
        """Set the title bar gradient to the given RGB color."""
        r2 = min(255, r + 25)
        g2 = min(255, g + 25)
        b2 = min(255, b + 25)
        r3 = max(0, r - 25)
        g3 = max(0, g - 25)
        b3 = max(0, b - 25)
        self.setStyleSheet(_title_bar_css(r2, g2, b2, r3, g3, b3))

    def resetColor(self):
        """Reset to the default blue gradient."""
        self.setStyleSheet(_DEFAULT_CSS)

    def _toggleMinimize(self):
        """Minimize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to minimum (just title bar)
        self.splitter.setSizes([total - 40, 40])

    def _toggleMaximize(self):
        """Maximize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to 80% of space
        self.splitter.setSizes([int(total * 0.2), int(total * 0.8)])

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            if self.childAt(a0.pos()) is None:
                self.dragging = True
                self.dragStartPos = a0.globalPosition().toPoint()
                a0.accept()
            else:
                a0.ignore()

    def mouseMoveEvent(self, a0):
        if self.dragging and a0:
            _ = a0.globalPosition().toPoint().y() - self.dragStartPos.y()  # delta
            self.dragStartPos = a0.globalPosition().toPoint()

            _ = self.splitter.handle(1).y() if self.splitter.handle(1) else 0  # current_pos
            new_pos = self.splitter.mapFromGlobal(
                a0.globalPosition().toPoint()).y()

            parent = self.splitter.parent()
            max_pos = parent.height() - self.splitter.handleWidth() if parent else 0

            new_pos = max(0, min(new_pos, max_pos))

            # move the splitter handle
            self.splitter.moveSplitter(new_pos, 1)
            a0.accept()
        elif a0:
            a0.ignore()

    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            a0.accept()

    def enterEvent(self, event):  # type: ignore[override]
        if event:
            pos = event.position().toPoint()
            if self.childAt(pos) is None:
                QApplication.setOverrideCursor(Qt.CursorShape.SizeVerCursor)
            else:
                QApplication.restoreOverrideCursor()

    def leaveEvent(self, a0):
        QApplication.restoreOverrideCursor()
        super().leaveEvent(a0)

    def enforceMinHeight(self):
        sizes = self.splitter.sizes()
        min_height = self.minimumHeight()
        parent = self.parent()
        if sizes[1] <= min_height:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget) and child != self:
                        child.hide()
        else:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget):
                        child.show()

        if sizes[1] < min_height:
            sizes[1] = min_height
            sizes[0] = max(sizes[0] - sizes[1], 0)
            self.splitter.setSizes(sizes)
