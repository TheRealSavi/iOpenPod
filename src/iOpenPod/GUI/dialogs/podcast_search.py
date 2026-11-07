"""Cover-led Podcast discovery with a secondary direct-RSS path."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from PySide6.QtCore import QEvent, QItemSelection, QModelIndex, Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.podcast_list_models import PodcastSearchResultListModel
from iOpenPod.app.podcasts.controller import (
    PodcastController,
    PodcastOperation,
    PodcastOperationFailure,
)
from iOpenPod.app.podcasts.models import PodcastSearchResult
from iOpenPod.GUI.delegates.podcast_delegates import PodcastSearchResultDelegate
from iOpenPod.GUI.presentation.i18n.text import podcasts_found_text
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.podcast_styles import render_podcast_search_style
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class PodcastSearchDialog(QDialog):
    """Find a Podcast by title and publisher, or supply a known RSS URL."""

    def __init__(
        self,
        controller: PodcastController,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
        *,
        artwork_provider: PodcastArtworkPixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._theme_manager = theme_manager
        self._search_state: Literal[
            "initial", "loading", "results", "empty", "error"
        ] = "initial"
        self._search_error = ""
        self._results_model = PodcastSearchResultListModel(self)
        self.setObjectName("podcastSearchDialog")
        self.setModal(True)
        self.setMinimumSize(640, 560)
        self.resize(820, 720)

        self._title = QLabel(self)
        self._title.setObjectName("podcastDialogTitle")
        self._intro = QLabel(self)
        self._intro.setObjectName("podcastDialogIntro")
        self._intro.setWordWrap(True)

        self._query_label = QLabel(self)
        self._query_label.setObjectName("podcastFieldLabel")
        self._query = QLineEdit(self)
        self._query.setObjectName("podcastDirectoryQuery")
        self._query.setClearButtonEnabled(True)
        self._query.setMinimumHeight(LAYOUT.control_height_large)
        self._query.returnPressed.connect(self._search)
        self._search_button = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._search_button.setObjectName("podcastDirectorySearch")
        self._search_button.setMinimumHeight(LAYOUT.control_height_large)
        self._search_button.clicked.connect(self._search)
        search_row = QHBoxLayout()
        search_row.setSpacing(LAYOUT.space_xs)
        search_row.addWidget(self._query, 1)
        search_row.addWidget(self._search_button)

        self._results = QListView(self)
        self._results.setObjectName("podcastDirectoryResults")
        self._results.setModel(self._results_model)
        self._results.setItemDelegate(
            PodcastSearchResultDelegate(
                theme_manager,
                self._results,
                artwork_provider=artwork_provider,
            )
        )
        self._results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._results.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._results.setMouseTracking(True)
        self._results.setUniformItemSizes(True)
        self._results.activated.connect(self._subscribe_selected)
        self._result_stack = QStackedWidget(self)
        self._result_stack.setMinimumHeight(120)
        self._result_stack.addWidget(self._results)
        self._empty_results = QLabel(self)
        self._empty_results.setObjectName("podcastSearchEmpty")
        self._empty_results.setWordWrap(True)
        self._empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_stack.addWidget(self._empty_results)
        self._result_stack.setCurrentWidget(self._empty_results)
        if artwork_provider is not None:
            artwork_provider.artworkChanged.connect(self._artwork_changed)

        rss_panel = QFrame(self)
        self._rss_panel = rss_panel
        rss_panel.setObjectName("podcastRssPanel")
        rss_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._rss_toggle = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._rss_toggle.setObjectName("podcastToggleRss")
        self._rss_toggle.setCheckable(True)
        self._rss_toggle.toggled.connect(self._toggle_rss)
        self._rss_title = QLabel(rss_panel)
        self._rss_title.setObjectName("podcastRssTitle")
        self._rss_detail = QLabel(rss_panel)
        self._rss_detail.setObjectName("podcastRssDetail")
        self._rss_detail.setWordWrap(True)
        self._rss_label = QLabel(rss_panel)
        self._rss_label.setObjectName("podcastFieldLabel")
        self._rss_url = QLineEdit(rss_panel)
        self._rss_url.setObjectName("podcastRssUrl")
        self._rss_url.setClearButtonEnabled(True)
        self._rss_url.setMinimumHeight(LAYOUT.control_height_large)
        self._rss_url.returnPressed.connect(self._subscribe_url)
        self._add_url = ActionButton(parent=rss_panel)
        self._add_url.setObjectName("podcastAddRss")
        self._add_url.setMinimumHeight(LAYOUT.control_height_large)
        self._add_url.clicked.connect(self._subscribe_url)
        rss_row = QHBoxLayout()
        rss_row.setSpacing(LAYOUT.space_xs)
        rss_row.addWidget(self._rss_url, 1)
        rss_row.addWidget(self._add_url)
        rss_layout = QVBoxLayout(rss_panel)
        rss_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        rss_layout.setSpacing(LAYOUT.space_xs)
        rss_layout.addWidget(self._rss_title)
        rss_layout.addWidget(self._rss_detail)
        rss_layout.addSpacing(LAYOUT.space_2xs)
        rss_layout.addWidget(self._rss_label)
        rss_layout.addLayout(rss_row)
        rss_panel.hide()

        self._status = QLabel(self)
        self._status.setObjectName("podcastSearchStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setMinimumHeight(24)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        subscribe = self._buttons.addButton(
            self.tr("Subscribe"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._subscribe = subscribe
        apply_action_button_kind(self._subscribe, ActionButtonKind.PRIMARY)
        self._subscribe.setObjectName("podcastSubscribeSelected")
        self._subscribe.clicked.connect(self._subscribe_selected)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._intro)
        layout.addSpacing(LAYOUT.space_xs)
        layout.addWidget(self._query_label)
        layout.addLayout(search_row)
        layout.addWidget(self._result_stack, 1)
        layout.addWidget(self._rss_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(rss_panel)
        layout.addWidget(self._status)
        layout.addWidget(self._buttons)

        controller.searchFinished.connect(self._search_finished)
        controller.busyChanged.connect(self._busy_changed)
        controller.operationFailed.connect(self._operation_failed)
        self._results.selectionModel().selectionChanged.connect(self._selection_changed)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        self._apply_styles()
        self.retranslate_ui()
        self._availability_changed()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Add Podcast"))
        self._title.setText(self.tr("Find your next show"))
        self._intro.setText(self.tr("Search by show name or publisher."))
        self._query_label.setText(self.tr("Podcast name"))
        self._query.setPlaceholderText(self.tr("e.g. 99% Invisible"))
        self._query.setAccessibleName(self.tr("Podcast search query"))
        self._search_button.setText(self.tr("Search"))
        self._rss_title.setText(self.tr("Have a feed URL?"))
        self._rss_toggle.setText(self.tr("Add using an RSS feed"))
        self._rss_detail.setText(
            self.tr("Subscribe directly when a Podcast is not listed in the directory.")
        )
        self._rss_label.setText(self.tr("RSS feed URL"))
        self._rss_url.setPlaceholderText(self.tr("https://example.com/feed.xml"))
        self._rss_url.setAccessibleName(self.tr("Podcast RSS URL"))
        self._add_url.setText(self.tr("Add Feed"))
        self._subscribe.setText(self.tr("Subscribe"))
        self._render_result_text()

    def _render_result_text(self) -> None:
        if self._search_state == "results":
            self._status.setText(podcasts_found_text(self._results_model.rowCount()))
            return
        self._status.clear()
        if self._search_state == "error":
            message = workflow_text(self._search_error)
        elif self._search_state == "loading":
            message = self.tr("Searching the Podcast directory…")
        elif self._search_state == "empty":
            message = self.tr(
                "No matching Podcasts were found. Try another name or add the RSS feed below."
            )
        else:
            message = self.tr("Discover a show to take with you.")
        self._empty_results.setText(message)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    @Slot()
    def _search(self) -> None:
        if not self._query.text().strip():
            self._status.setText(self.tr("Enter a Podcast name, then choose Search."))
            self._query.setFocus()
            return
        self._search_state = "loading"
        self._results_model.replace(())
        self._render_result_text()
        self._result_stack.setCurrentWidget(self._empty_results)
        self._controller.search(self._query.text())

    @Slot(object)
    def _search_finished(self, value: object) -> None:
        results = _podcast_search_results(value)
        if results is None:
            return
        self._results_model.replace(results)
        self._search_state = "results" if results else "empty"
        self._render_result_text()
        if results:
            self._result_stack.setCurrentWidget(self._results)
            self._results.setCurrentIndex(self._results_model.index(0, 0))
        else:
            self._result_stack.setCurrentWidget(self._empty_results)
        self._availability_changed()

    @Slot()
    @Slot(QModelIndex)
    def _subscribe_selected(self, _index: QModelIndex | None = None) -> None:
        if self._controller.busy or not self._controller.can_edit:
            return
        result = self._results_model.result_at(self._results.currentIndex().row())
        if result is None:
            return
        self._controller.subscribe(result.feed_url)
        self.accept()

    @Slot()
    def _subscribe_url(self) -> None:
        url = self._rss_url.text().strip()
        if not url:
            self._status.setText(
                self.tr(
                    "Enter the full HTTP or HTTPS RSS feed URL, then choose Add Feed."
                )
            )
            self._rss_url.setFocus()
            return
        self._controller.subscribe(url)
        if self._controller.busy:
            self.accept()

    @Slot(bool)
    def _busy_changed(self, _busy: bool) -> None:
        self._availability_changed()

    @Slot(object)
    def _operation_failed(self, value: object) -> None:
        if (
            isinstance(value, PodcastOperationFailure)
            and value.operation is PodcastOperation.SEARCH
        ):
            self._search_state = "error"
            self._search_error = value.message
            self._render_result_text()
            self._result_stack.setCurrentWidget(self._empty_results)

    @Slot()
    def _availability_changed(self) -> None:
        idle = not self._controller.busy
        self._results.setEnabled(idle)
        self._query.setEnabled(idle)
        self._search_button.setEnabled(idle)
        self._rss_url.setEnabled(idle and self._controller.can_edit)
        self._add_url.setEnabled(idle and self._controller.can_edit)
        self._subscribe.setEnabled(
            idle
            and self._controller.can_edit
            and self._results_model.result_at(self._results.currentIndex().row())
            is not None
        )

    @Slot(QItemSelection, QItemSelection)
    def _selection_changed(
        self,
        _selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        self._availability_changed()

    @Slot(bool)
    def _toggle_rss(self, visible: bool) -> None:
        self._rss_panel.setVisible(visible)
        self.setMinimumHeight(
            max(560, self.minimumSizeHint().height()) if visible else 560
        )
        if visible:
            self._rss_url.setFocus()

    @Slot(str)
    def _artwork_changed(self, _source: str) -> None:
        self._results.viewport().update()

    @Slot(str)
    def _theme_changed(self, _theme: str) -> None:
        self._apply_styles()
        self._results.viewport().update()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            render_podcast_search_style(
                self._theme_manager.tokens,
                self._theme_manager.typography,
            )
        )


def _podcast_search_results(
    value: object,
) -> tuple[PodcastSearchResult, ...] | None:
    if not isinstance(value, tuple):
        return None
    items = cast("tuple[object, ...]", value)
    results: list[PodcastSearchResult] = []
    for item in items:
        if not isinstance(item, PodcastSearchResult):
            return None
        results.append(item)
    return tuple(results)


__all__ = ["PodcastSearchDialog"]
