"""A short, illustrated first-run tour with staged Host preferences.

Hallmark · component: onboarding dialog · theme: existing desktop tokens
Pre-emit critique: P4 H4 E4 S5 R5 V4. Shared ActionButtons own interaction states.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    ITUNES_107_ARTWORK,
    NAVIGATION_STYLE,
    ONBOARDING_COMPLETE,
    IPodLibraryViewMode,
    NavigationStyle,
    SettingDefinition,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.GUI.dialogs.help_support import HelpSupportPage
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    ActionButtonState,
    IconButton,
    IconButtonKind,
)

logger = logging.getLogger(__name__)
_SCREENSHOTS = Path(__file__).parents[2] / "assets" / "onboarding"


class _Screenshot(QWidget):
    """Fit an actual app capture without imposing its native size on the dialog."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setMinimumSize(1, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, filename: str, description: str) -> None:
        self._pixmap = QPixmap(str(_SCREENSHOTS / filename))
        self.setAccessibleName(description)
        self.setToolTip(description)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 300)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self._pixmap.isNull():
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.tr("Preview unavailable"),
            )
            return
        size = self._pixmap.size().scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        target = self.rect()
        target.setSize(size)
        target.moveCenter(self.rect().center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap)


def _label(text: str, name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class _Page(QWidget):
    def __init__(self, title: str, description: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(LAYOUT.space_md)
        self.content.addWidget(_label(title, "dialogTitle", self))
        self.content.addWidget(_label(description, "onboardingDescription", self))
        self.preview = _Screenshot(self)
        self.content.addWidget(self.preview, 1)
        self.caption = _label("", "onboardingCaption", self)
        self.content.addWidget(self.caption)

    def illustrate(self, filename: str, caption: str) -> None:
        self.preview.set_image(filename, caption)
        self.caption.setText(caption)


@dataclass(frozen=True)
class _Choice[Value]:
    value: Value
    label: str
    image: str
    caption: str


class _ChoiceButton(QRadioButton):
    """A choice tile with native radio semantics and a full-tile hit target."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.setProperty("onboardingChoice", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(LAYOUT.minimum_touch_target)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)


class _ChoicePage[Value](_Page):
    def __init__(
        self,
        title: str,
        description: str,
        definition: SettingDefinition[Value],
        choices: tuple[_Choice[Value], ...],
        settings: SettingsService,
        parent: QWidget,
    ) -> None:
        super().__init__(title, description, parent)
        self.definition = definition
        self._choices = choices
        self._group = QButtonGroup(self)
        self._options = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._options.setSpacing(LAYOUT.space_xs)
        for index, choice in enumerate(choices):
            button = _ChoiceButton(choice.label, self)
            button.setObjectName(f"onboardingChoice{index}")
            button.setToolTip(choice.caption)
            self._group.addButton(button, index)
            self._options.addWidget(button)
            if choice.value == settings.get_global(definition):
                button.setChecked(True)
        self.content.insertLayout(2, self._options)
        self._group.idToggled.connect(self._selected)
        self._selected(self._group.checkedId(), True)

    def _selected(self, index: int, checked: bool) -> None:
        if checked:
            choice = self._choices[index]
            self.illustrate(choice.image, choice.caption)

    def save(self, settings: SettingsService) -> None:
        settings.set_global(self.definition, self.selected_value)

    @property
    def selected_value(self) -> Value:
        return self._choices[self._group.checkedId()].value

    @property
    def selected_index(self) -> int:
        return self._group.checkedId()

    def select_index(self, index: int) -> None:
        self._group.button(index).setChecked(True)

    def fit_options(self, width: int) -> None:
        buttons = self._group.buttons()
        for button in buttons:
            button.ensurePolished()
        required = sum(button.sizeHint().width() for button in buttons)
        required += self._options.spacing() * (len(buttons) - 1)
        self._options.setDirection(
            QBoxLayout.Direction.TopToBottom
            if required > width
            else QBoxLayout.Direction.LeftToRight
        )
        # Hidden pages also contribute to QStackedWidget's minimum size.
        self.content.invalidate()
        self.updateGeometry()


class OnboardingDialog(QDialog):
    """Keep choices local until Finish; dismissal never completes onboarding."""

    def __init__(
        self,
        settings: SettingsService,
        i18n_manager: I18nManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._i18n_manager = i18n_manager
        self.setObjectName("onboardingDialog")
        self.setWindowTitle(self.tr("Welcome to iOpenPod"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(560, 440)
        screen = self.screen().availableGeometry()
        self.resize(min(840, screen.width() - 48), min(720, screen.height() - 48))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)
        self._progress = _label("", "onboardingProgress", self)
        header = QHBoxLayout()
        header.addWidget(self._progress, 1)
        self._language_button = IconButton(
            "language",
            self.tr("Language"),
            self,
            kind=IconButtonKind.QUIET,
            glyph_size=24,
        )
        self._language_button.setObjectName("onboardingLanguage")
        self._language_menu = QMenu(self._language_button)
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self._language_group.triggered.connect(self._select_language)
        self._language_menu.aboutToShow.connect(self._refresh_language_menu)
        self._language_button.setMenu(self._language_menu)
        self._language_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self._language_button)
        layout.addLayout(header)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._pages = QStackedWidget(self._scroll)
        self._pages.setObjectName("onboardingPages")
        self._scroll.setWidget(self._pages)
        layout.addWidget(self._scroll, 1)

        self._populate_pages()
        self._settings_reminder = _label(
            self.tr("You can always change this later in settings"),
            "onboardingCaption",
            self,
        )
        layout.addWidget(self._settings_reminder)
        self._error = _label("", "onboardingError", self)
        self._error.setAccessibleName(self.tr("Settings save error"))
        self._error.hide()
        layout.addWidget(self._error)
        buttons = QHBoxLayout()
        self._later = ActionButton(
            self.tr("Set up later"), self, kind=ActionButtonKind.QUIET
        )
        self._later.setObjectName("onboardingLater")
        self._later.clicked.connect(self.reject)
        buttons.addWidget(self._later)
        buttons.addStretch()
        self._back = ActionButton(self.tr("Back"), self)
        self._back.setObjectName("onboardingBack")
        self._back.clicked.connect(self._previous)
        buttons.addWidget(self._back)
        self._next = ActionButton("", self, kind=ActionButtonKind.PRIMARY)
        self._next.setObjectName("onboardingNext")
        self._next.setDefault(True)
        self._next.clicked.connect(self._advance)
        buttons.addWidget(self._next)
        layout.addLayout(buttons)
        self._update_navigation()
        self._refresh_language_menu()
        i18n_manager.languageChanged.connect(self._language_changed)

    def _populate_pages(self) -> None:
        settings = self._settings
        self._navigation = _ChoicePage(
            self.tr("Choose your navigation style"),
            self.tr(
                "Have navigation across the top, or expand it onto the left of your Library."
            ),
            NAVIGATION_STYLE,
            (
                _Choice(
                    NavigationStyle.COMPACT_TOP_BAR.value,
                    self.tr("Compact top bar"),
                    "navigation-compact.png",
                    self.tr(
                        "More room for your Library. Open the headings to find each view."
                    ),
                ),
                _Choice(
                    NavigationStyle.SIDEBAR.value,
                    self.tr("Sidebar"),
                    "navigation-sidebar.png",
                    self.tr(
                        "Keep Library sections and Playlists visible down the left."
                    ),
                ),
            ),
            settings,
            self,
        )
        self._pages.addWidget(self._navigation)
        self._library = _ChoicePage(
            self.tr("Opening an Album"),
            self.tr("Choose how Tracks appear when you open an Album in your Library."),
            IPOD_LIBRARY_VIEW_MODE,
            (
                _Choice(
                    IPodLibraryViewMode.SPLIT_TABLE.value,
                    self.tr("Split Table"),
                    "library-split.png",
                    self.tr(
                        "Browse Albums above, with the selected Album's Tracks below."
                    ),
                ),
                _Choice(
                    IPodLibraryViewMode.WHOLE_PAGE_TABLE.value,
                    self.tr("Whole Page Table"),
                    "library-whole.png",
                    self.tr(
                        "Open Tracks on their own page. Back takes you to the Albums."
                    ),
                ),
                _Choice(
                    IPodLibraryViewMode.ITUNES_11.value,
                    self.tr("iTunes 11 style"),
                    "library-inline.png",
                    self.tr("Expand an Album's Tracks right inside the artwork grid."),
                ),
            ),
            settings,
            self,
        )
        self._pages.addWidget(self._library)
        self._artwork = _ChoicePage(
            self.tr("iPod image"),
            self.tr("Choose the device images shown in iOpenPod."),
            ITUNES_107_ARTWORK,
            (
                _Choice(
                    False,
                    self.tr("Standard"),
                    "device-standard.png",
                    self.tr("Use the standard device portrait."),
                ),
                _Choice(
                    True,
                    self.tr("iTunes 10.7 style"),
                    "device-classic.png",
                    self.tr("Use classic angled artwork where available."),
                ),
            ),
            settings,
            self,
        )
        self._pages.addWidget(self._artwork)
        transcoding = _Page(
            self.tr("Transcoding settings"),
            self.tr(
                "Open Settings > Transcoding before your first sync to set things up the way "
                "you like. Transcoding converts "
                "media into formats your iPod can play. Your original files stay unchanged."
            ),
            self,
        )
        transcoding.illustrate(
            "transcoding.png",
            self.tr(
                "Leave on Auto for iOpenPod to automatically choose the best encoder, and use "
                "Compact, Balanced, and High Quality presets to configure how much space the "
                "files use on your iPod. Change to a specific encoder to access advanced "
                "configuration."
            ),
        )
        self._pages.addWidget(transcoding)
        self._sync_start = _Page(
            self.tr("1. Open Sync with Host"),
            self.tr(
                "Connect your iPod and load it with Choose Device. Then press Sync with Host "
                "in the navigation bar. Host means the computer running iOpenPod."
            ),
            self,
        )
        self._sync_start.illustrate(
            "sync-start-compact.png",
            self.tr(
                "This button starts the guided Sync workflow. It does not immediately "
                "copy or remove any media."
            ),
        )
        self._pages.addWidget(self._sync_start)
        folders = _Page(
            self.tr("2. Choose your media folders"),
            self.tr(
                "In Choose Media Folders, press Add Folder to pick folders on your computer. "
                "Use each folder's settings button to choose media types and whether to "
                "include subfolders."
            ),
            self,
        )
        folders.illustrate(
            "sync-folders.png",
            self.tr(
                "Press Sync to scan these folders and compare them with your iPod. "
                "This step finds media; you choose what to transfer next."
            ),
        )
        self._pages.addWidget(folders)
        selection = _Page(
            self.tr("3. Select your media"),
            self.tr(
                "After scanning, browse the media found on your computer. Check the Tracks, "
                "Albums, or other items you want on your iPod. Checked items with the iPod "
                "symbol are already on your iPod."
            ),
            self,
        )
        selection.illustrate(
            "sync-selection.png",
            self.tr(
                "Watch the estimated storage as you choose. Press Review Sync when "
                "your selection is ready. Nothing has been transferred yet."
            ),
        )
        self._pages.addWidget(selection)
        review = _Page(
            self.tr("4. Review, then sync"),
            self.tr(
                "Review the proposed additions, updates, and removals. Uncheck changes you "
                "do not want, or press Edit Selection to go back. iPod-only removals start unchecked."
            ),
            self,
        )
        review.illustrate(
            "sync-review.png",
            self.tr(
                "Press Sync Selected to apply the checked changes. Keep your iPod connected "
                "until Sync finishes, check the result, then eject it before unplugging."
            ),
        )
        self._pages.addWidget(review)
        self._help = HelpSupportPage(self)
        self._pages.addWidget(self._help)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_pages()

    def _fit_pages(self) -> None:
        available = self.width() - 2 * LAYOUT.space_lg - LAYOUT.scrollbar_extent
        for page in (self._navigation, self._library, self._artwork):
            page.fit_options(available)
        self._help.fit_actions(available)

    def _refresh_language_menu(self) -> None:
        self._language_menu.clear()
        for option in self._i18n_manager.available_languages():
            action = QAction(option.label, self._language_menu)
            action.setData(option.language_tag)
            action.setCheckable(True)
            action.setChecked(option.language_tag == self._i18n_manager.language)
            self._language_group.addAction(action)
            self._language_menu.addAction(action)

    def _select_language(self, action: QAction) -> None:
        language = action.data()
        if not isinstance(language, str) or language == self._i18n_manager.language:
            return
        try:
            self._i18n_manager.set_language(language)
        except Exception:
            logger.exception("Could not save onboarding language")
            self._error.setText(
                self.tr("Could not save the language. Please try again.")
            )
            self._error.show()
            self._refresh_language_menu()

    def _language_changed(self, _language: str) -> None:
        index = self._pages.currentIndex()
        scroll = self._scroll.verticalScrollBar().value()
        choices = (
            self._navigation.selected_index,
            self._library.selected_index,
            self._artwork.selected_index,
        )
        while self._pages.count():
            page = self._pages.widget(0)
            if page is None:
                break
            self._pages.removeWidget(page)
            page.setParent(None)
            page.deleteLater()
        self._populate_pages()
        self._navigation.select_index(choices[0])
        self._library.select_index(choices[1])
        self._artwork.select_index(choices[2])
        self._pages.setCurrentIndex(index)
        self.setWindowTitle(self.tr("Welcome to iOpenPod"))
        self._later.setText(self.tr("Set up later"))
        self._back.setText(self.tr("Back"))
        self._settings_reminder.setText(
            self.tr("You can always change this later in settings")
        )
        self._language_button.setAccessibleName(self.tr("Language"))
        self._language_button.setToolTip(self.tr("Language"))
        self._error.setAccessibleName(self.tr("Settings save error"))
        self._error.hide()
        self._fit_pages()
        self._update_navigation()
        self._scroll.verticalScrollBar().setValue(scroll)

    def _update_navigation(self) -> None:
        index = self._pages.currentIndex()
        self._settings_reminder.setVisible(
            self._pages.currentWidget()
            in (self._navigation, self._library, self._artwork)
        )
        if self._pages.currentWidget() is self._sync_start:
            style = (
                "sidebar"
                if self._navigation.selected_value == NavigationStyle.SIDEBAR.value
                else "compact"
            )
            self._sync_start.preview.set_image(
                f"sync-start-{style}.png", self._sync_start.caption.text()
            )
        self._scroll.verticalScrollBar().setValue(0)
        self._progress.setText(
            self.tr("GETTING STARTED · %1 OF %2")
            .replace("%1", str(index + 1))
            .replace("%2", str(self._pages.count()))
        )
        self._back.setEnabled(index > 0)
        self._next.setText(
            self.tr("Finish") if index == self._pages.count() - 1 else self.tr("Next")
        )
        self._next.setFocus()

    def _previous(self) -> None:
        self._pages.setCurrentIndex(max(0, self._pages.currentIndex() - 1))
        self._update_navigation()

    def _advance(self) -> None:
        if self._pages.currentIndex() < self._pages.count() - 1:
            self._pages.setCurrentIndex(self._pages.currentIndex() + 1)
            self._update_navigation()
        else:
            self.accept()

    def accept(self) -> None:
        if self._pages.currentIndex() != self._pages.count() - 1:
            return
        self._error.hide()
        self._next.set_state(ActionButtonState.LOADING)
        try:
            self._navigation.save(self._settings)
            self._library.save(self._settings)
            self._artwork.save(self._settings)
            # Persist this last: a failed preference write must leave the tour due.
            self._settings.set_global(ONBOARDING_COMPLETE, True)
        except Exception:
            logger.exception("Could not save onboarding preferences")
            self._error.setText(
                self.tr(
                    "Could not save settings. Check available space and permissions, then try Finish again."
                )
            )
            self._error.show()
            self._next.set_state(ActionButtonState.ERROR)
            return
        self._next.set_state(ActionButtonState.SUCCESS)
        super().accept()
