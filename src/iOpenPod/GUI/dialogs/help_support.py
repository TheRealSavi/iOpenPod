"""Shared help resources for onboarding and the standalone About dialog."""

from functools import partial

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.application_icon import application_pixmap
from iOpenPod.GUI.presentation.desktop_services import open_desktop_url
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


def _label(text: str, name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class _HelpIcon(QWidget):
    """Decorative glyph that follows the current palette and display scale."""

    def __init__(self, glyph: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self.setFixedSize(32, 32)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        glyph_icon(
            self._glyph,
            28,
            self.palette().highlight().color(),
            self.devicePixelRatioF(),
        ).paint(painter, self.rect().adjusted(2, 2, -2, -2))


class HelpSupportPage(QWidget):
    """Help, issue reporting, and optional project support links."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        page = self
        self._actions: list[QBoxLayout] = []
        content = QVBoxLayout(page)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(LAYOUT.space_md)
        heading = QHBoxLayout()
        heading.setSpacing(LAYOUT.space_md)
        logo = QLabel(page)
        logo.setPixmap(application_pixmap(80, self.devicePixelRatioF()))
        logo.setFixedSize(80, 80)
        heading.addWidget(logo)
        heading.addWidget(_label(self.tr("Help and support"), "dialogTitle", page), 1)
        content.addLayout(heading)
        sections = (
            (
                "help",
                self.tr("Have a question?"),
                self.tr("Find guides on the website or ask the community on Discord."),
                (
                    ("Website", self.tr("Visit the website"), "https://iopenpod.com"),
                    (
                        "Discord",
                        self.tr("Join Discord"),
                        "https://discord.gg/9Yy499Tf5d",
                    ),
                ),
            ),
            (
                "alert",
                self.tr("Something not working?"),
                self.tr(
                    "Report issues on GitHub. Include what happened and how to reproduce it."
                ),
                (
                    (
                        "Issues",
                        self.tr("Report an issue"),
                        "https://github.com/TheRealSavi/iOpenPod/issues",
                    ),
                ),
            ),
            (
                "heart",
                self.tr("Enjoying iOpenPod?"),
                self.tr(
                    "Support development on Ko-fi, or give the project a star on GitHub. Thank you!"
                ),
                (
                    (
                        "Kofi",
                        self.tr("Support on Ko-fi"),
                        "https://ko-fi.com/johngibbons",
                    ),
                    (
                        "Star",
                        self.tr("Star on GitHub"),
                        "https://github.com/TheRealSavi/iOpenPod",
                    ),
                ),
            ),
        )
        for index, (glyph, title, description, links) in enumerate(sections):
            if index:
                divider = QFrame(page)
                divider.setObjectName("onboardingHelpDivider")
                divider.setFixedHeight(1)
                content.addWidget(divider)
            panel = QFrame(page)
            row = QHBoxLayout(panel)
            row.setContentsMargins(0, LAYOUT.space_xs, 0, LAYOUT.space_xs)
            row.setSpacing(LAYOUT.space_md)
            row.addWidget(_HelpIcon(glyph, panel), 0, Qt.AlignmentFlag.AlignVCenter)
            details = QVBoxLayout()
            details.setSpacing(LAYOUT.space_sm)
            details.addStretch()
            details.addWidget(_label(title, "sectionTitle", panel))
            details.addWidget(_label(description, "onboardingDescription", panel))
            actions = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            actions.setSpacing(LAYOUT.space_xs)
            for name, text, url in links:
                button = ActionButton(text, panel, kind=ActionButtonKind.QUIET)
                button.setObjectName(f"onboarding{name}")
                button.setToolTip(url)
                button.clicked.connect(partial(open_desktop_url, QUrl(url)))
                actions.addWidget(button)
            actions.addStretch()
            self._actions.append(actions)
            details.addLayout(actions)
            details.addStretch()
            row.addLayout(details, 1)
            content.addWidget(panel, 1)

    def fit_actions(self, available: int) -> None:
        for actions in self._actions:
            buttons = [
                item.widget()
                for index in range(actions.count())
                if (item := actions.itemAt(index)) is not None
                and item.widget() is not None
            ]
            required = 0
            for button in buttons:
                if button is not None:
                    button.ensurePolished()
                    required += button.sizeHint().width()
            required += actions.spacing() * (len(buttons) - 1)
            actions.setDirection(
                QBoxLayout.Direction.TopToBottom
                if required > available - 32 - LAYOUT.space_md
                else QBoxLayout.Direction.LeftToRight
            )
            # Hidden onboarding pages still contribute to the stack's minimum
            # size; refresh each section before the page measures itself.
            if isinstance(details := actions.parent(), QVBoxLayout):
                details.invalidate()
            panel = actions.parentWidget()
            if panel is not None and (row := panel.layout()) is not None:
                row.invalidate()
                panel.updateGeometry()
        if (layout := self.layout()) is not None:
            layout.invalidate()
        self.updateGeometry()


class HelpSupportDialog(QDialog):
    """Show help resources without onboarding or settings persistence."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("helpSupportDialog")
        self.setWindowTitle(
            QCoreApplication.translate("HelpSupportPage", "Help and support")
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(560, 440)
        screen = self.screen().availableGeometry()
        self.resize(min(840, screen.width() - 48), min(720, screen.height() - 48))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([LAYOUT.space_lg] * 4))
        layout.setSpacing(LAYOUT.space_md)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._help = HelpSupportPage(scroll)
        scroll.setWidget(self._help)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = ActionButton(
            QCoreApplication.translate("CommonActions", "Close"),
            self,
            kind=ActionButtonKind.PRIMARY,
        )
        close.setObjectName("helpSupportClose")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._help.fit_actions(
            self.width() - 2 * LAYOUT.space_lg - LAYOUT.scrollbar_extent
        )
