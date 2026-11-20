"""Shared presentation for firmware setup; no device access or workflow decisions.

Hallmark · component: firmware setup · genre: modern-minimal
Theme: existing iOpenPod tokens. Macrostructure: not applicable to dialogs.
Pre-emit critique: Philosophy 5, Hierarchy 5, Execution 4, Specificity 5,
Restraint 5, Variety 4. Native controls supply hover/focus/pressed/disabled;
the setup status supplies loading/error/success without decorative animation.
"""

from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_DFU_IMAGE = Path(__file__).parents[2] / "assets" / "firmware_setup" / "classic-dfu.png"


def _label(name: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class DfuDiagram(QWidget):
    """Bundled Classic product image with highlighted Menu and Select buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dfuDiagram")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(LAYOUT.firmware_diagram_height)
        self._image = QPixmap(str(_DFU_IMAGE))
        self._retranslate()

    def _retranslate(self) -> None:
        self.setAccessibleName(self.tr("iPod Classic button guide"))
        self.setAccessibleDescription(
            self.tr(
                "Menu is at the top of the clickwheel. Select is the round button in the middle. Hold both together."
            )
        )

    def sizeHint(self) -> QSize:
        return QSize(LAYOUT.firmware_diagram_width, LAYOUT.firmware_diagram_height)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = min(self.width() / 224, self.height() / 280)
        painter.translate(
            (self.width() - 224 * scale) / 2, (self.height() - 280 * scale) / 2
        )
        painter.scale(scale, scale)
        palette = self.palette()
        # Preserve the source aspect ratio at any window size or display scale.
        size = self._image.size().scaled(176, 246, Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((224 - size.width()) / 2, 0, size.width(), size.height())
        painter.drawPixmap(target, self._image, QRectF(self._image.rect()))
        font = self.font()
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.WindowText))
        painter.drawText(
            QRectF(0, 256, 224, 24),
            Qt.AlignmentFlag.AlignCenter,
            self.tr("Menu + Select"),
        )
        painter.end()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LanguageChange):
            self.update()
        super().changeEvent(event)


class DfuGuide(QWidget):
    """Two observable steps; never a guessed countdown or detection signal."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dfuGuide")
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(LAYOUT.space_lg)
        self._diagram = DfuDiagram(self)
        self._layout.addWidget(self._diagram, 2)
        steps = QWidget(self)
        self._steps = steps
        rows = QVBoxLayout(steps)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(LAYOUT.space_lg)
        self._titles: list[QLabel] = []
        self._details: list[QLabel] = []
        for _ in range(2):
            row = QVBoxLayout()
            row.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.setSpacing(LAYOUT.space_2xs)
            title = _label("firmwareStepTitle", steps)
            detail = _label("firmwareStepDetail", steps)
            row.addWidget(title)
            row.addWidget(detail)
            rows.addLayout(row)
            self._titles.append(title)
            self._details.append(detail)
        self._layout.addWidget(steps, 3, Qt.AlignmentFlag.AlignVCenter)
        self.retranslate()

    def retranslate(self) -> None:
        steps = (
            (
                self.tr("1. Hold Menu + Select"),
                self.tr(
                    "Select is the center button. The screen goes black, then shows the Apple logo. Keep holding both buttons."
                ),
            ),
            (
                self.tr("2. Release when it goes black again"),
                self.tr(
                    "Let go of both buttons at the second black screen. Leave your iPod connected with its screen black."
                ),
            ),
        )
        for index, (title, detail, (heading, body)) in enumerate(
            zip(self._titles, self._details, steps, strict=True), start=1
        ):
            title.setAccessibleName(self.tr("Step {number}").format(number=index))
            title.setText(heading)
            detail.setText(body)

    def resizeEvent(self, event: QResizeEvent) -> None:
        stacked = event.size().width() < LAYOUT.firmware_stacked_breakpoint
        self._layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if stacked
            else QBoxLayout.Direction.LeftToRight
        )
        # At narrow widths, show the actionable steps before the illustration.
        first = self._steps if stacked else self._diagram
        if self._layout.indexOf(first) != 0:
            self._layout.removeWidget(first)
            self._layout.insertWidget(0, first, 3 if stacked else 2)
        super().resizeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)


class FirmwareSetupView(QWidget):
    """Dialog content and responsive footer; controllers retain action ownership."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("firmwareSetupView")
        root = QVBoxLayout(self)
        root.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        root.setSpacing(LAYOUT.space_md)
        self.eyebrow = _label("firmwareEyebrow", self)
        self.heading = _label("dialogTitle", self)
        self.identity = _label("firmwareIdentity", self)
        root.addWidget(self.eyebrow)
        root.addWidget(self.heading)
        root.addWidget(self.identity)
        scroll = QScrollArea(self)
        scroll.setObjectName("firmwareContentScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body.setObjectName("firmwareContent")
        body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(
            0, LAYOUT.space_xs, LAYOUT.space_xs, LAYOUT.space_xs
        )
        self.body.setSpacing(LAYOUT.space_lg)
        self.detail = _label("firmwareDetail", body)
        self.body.addWidget(self.detail)
        self.body.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.notice = _label("firmwareNotice", self)
        root.addWidget(self.notice)
        self.status = _label("firmwareStatus", self)
        root.addWidget(self.status)
        self.progress = QProgressBar(self)
        self.progress.setObjectName("firmwareProgress")
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(self.tr("Installation progress"))
        root.addWidget(self.progress)
        footer = QFrame(self)
        footer.setObjectName("firmwareFooter")
        self.buttons = QBoxLayout(QBoxLayout.Direction.LeftToRight, footer)
        self.buttons.setContentsMargins(0, LAYOUT.space_md, 0, 0)
        self.buttons.setSpacing(LAYOUT.space_xs)
        self.buttons.addStretch()
        root.addWidget(footer)

    def set_status(self, text: str, *, tone: str = "default") -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if self.status.property("tone") != tone:
            self.status.setProperty("tone", tone)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.buttons.setDirection(
            QBoxLayout.Direction.TopToBottom
            if event.size().width() < LAYOUT.firmware_stacked_breakpoint
            else QBoxLayout.Direction.LeftToRight
        )
        super().resizeEvent(event)


class FirmwareVersions(QFrame):
    """The two independent version fields users will confirm on the iPod."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("firmwareVersions")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout = layout
        layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_md, LAYOUT.space_md, LAYOUT.space_md
        )
        layout.setSpacing(LAYOUT.space_lg)
        self._apple_title = _label("firmwareVersionCaption", self)
        self._mod_title = _label("firmwareVersionCaption", self)
        self._mod = _label("firmwareVersionValue", self)
        apple = _label("firmwareVersionValue", self)
        apple.setText("2.0.5")
        for title, value in ((self._apple_title, apple), (self._mod_title, self._mod)):
            column = QVBoxLayout()
            column.setSpacing(LAYOUT.space_xs)
            column.addWidget(title)
            column.addWidget(value)
            layout.addLayout(column, 1)
        self._retranslate()

    def set_version(self, version: str) -> None:
        self._mod.setText(version)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if event.size().width() < LAYOUT.firmware_stacked_breakpoint
            else QBoxLayout.Direction.LeftToRight
        )
        super().resizeEvent(event)

    def _retranslate(self) -> None:
        self._apple_title.setText(self.tr("Apple firmware"))
        self._mod_title.setText(self.tr("Mod version"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)
