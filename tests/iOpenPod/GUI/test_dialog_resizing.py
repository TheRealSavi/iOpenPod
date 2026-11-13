"""Resizing keeps dialog forms at the top and actions at the bottom."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.test_podcast_page import PodcastControllerStub
from tests.iOpenPod.GUI.test_tones import (
    TRACK,
    ConversionTestController,
    ToneTestController,
)
from whenever import Time

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.genius_mixes import (
    MIN_MIX_TRACKS,
    MIX_CATALOG,
    MixPolicy,
    MixProposal,
)
from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.models.extras import AlarmItem
from iOpenPod.app.phase_runtime_controller import PhaseRuntimeController
from iOpenPod.app.podcasts.models import (
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.GUI.dialogs.genius_mixes import (
    AddGeniusMixesDialog,
    GeniusMixSettingsDialog,
)
from iOpenPod.GUI.dialogs.media_folders import MediaFolderSettingsDialog
from iOpenPod.GUI.dialogs.phase_runtime_setup import PhaseRuntimeSetupDialog
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.dialogs.playlist_export import PlaylistExportDialog
from iOpenPod.GUI.dialogs.podcast_login import PodcastLoginDialog
from iOpenPod.GUI.dialogs.podcast_search import PodcastSearchDialog
from iOpenPod.GUI.dialogs.podcast_sync_settings import PodcastSyncSettingsDialog
from iOpenPod.GUI.dialogs.timer_editor import TimerEditor
from iOpenPod.GUI.dialogs.tone_conversion import ToneConversionDialog
from iOpenPod.GUI.pages.alarms_page import AlarmEditor
from iOpenPod.GUI.pages.calendar_page import CalendarEditor
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iPodDB.alarms import CountdownTimerSnapshot
from iPodDB.calendar import CalendarEntryKind
from iPodDB.library import PlaylistKind

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.controller import PodcastController


@pytest.fixture(params=[AppearanceMode.LIGHT, AppearanceMode.DARK], autouse=True)
def theme(request: pytest.FixtureRequest) -> Iterator[ThemeManager]:
    manager = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    manager.set_mode(request.param)
    yield manager
    manager.close()


def _rect(widget: QWidget, dialog: QDialog) -> QRect:
    return QRect(widget.mapTo(dialog, QPoint()), widget.size())


def _skip_phase_refresh(_controller: PhaseRuntimeController) -> None:
    """Keep layout tests independent of the installed optional runtime."""


def _assert_form_anchored(dialog: QDialog) -> None:
    dialog.show()
    APPLICATION.processEvents()
    # Let wrapped descriptions reach their preferred height before testing surplus space.
    layout = dialog.layout()
    assert layout is not None
    dialog.resize(
        dialog.width(),
        max(dialog.height(), layout.totalHeightForWidth(dialog.width())) + 80,
    )
    APPLICATION.processEvents()
    original_size = dialog.size()
    controls = [
        widget
        for widget in dialog.findChildren(QWidget)
        if isinstance(widget, (QLabel, QLineEdit, QComboBox, QCheckBox))
        and widget.isVisibleTo(dialog)
    ]
    assert controls
    positions = [_rect(widget, dialog) for widget in controls]
    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.isVisibleTo(dialog)
    ]
    action = max(buttons, key=lambda button: _rect(button, dialog).bottom())
    bottom_gap = dialog.height() - _rect(action, dialog).bottom()
    for extra in (320, 0):
        dialog.resize(original_size.width(), original_size.height() + extra)
        APPLICATION.processEvents()
        assert [_rect(widget, dialog) for widget in controls] == positions
        assert dialog.height() - _rect(action, dialog).bottom() == bottom_gap
    right = max(buttons, key=lambda button: _rect(button, dialog).right())
    right_gap = dialog.width() - _rect(right, dialog).right()
    dialog.resize(original_size.width() + 240, original_size.height() + 320)
    APPLICATION.processEvents()
    assert dialog.width() - _rect(right, dialog).right() == right_gap
    assert dialog.height() - _rect(action, dialog).bottom() == bottom_gap


@pytest.mark.parametrize(
    "factory",
    [
        lambda: GeniusMixSettingsDialog(MixPolicy()),
        lambda: PlaylistExportDialog(4),
        lambda: PlaylistEditorDialog(PlaylistKind.PLAYLIST),
        lambda: PlaylistEditorDialog(PlaylistKind.FOLDER),
        lambda: AlarmEditor(AlarmItem(0, "Alarm", Time(7), None, True)),
        lambda: TimerEditor(CountdownTimerSnapshot(saved_hours=0, saved_minutes=15)),
    ],
    ids=[
        "genius-settings",
        "playlist-export",
        "playlist",
        "playlist-folder",
        "alarm",
        "timer",
    ],
)
def test_small_editor_anchors(factory: Callable[[], QDialog]) -> None:
    _assert_form_anchored(factory())


def test_media_folder_settings_anchors(tmp_path: Path) -> None:
    _assert_form_anchored(MediaFolderSettingsDialog(create_host_media_folder(tmp_path)))


def test_tone_conversion_anchors() -> None:
    extras, conversion = ToneTestController(), ConversionTestController()
    _assert_form_anchored(ToneConversionDialog(TRACK, conversion, extras))


def test_podcast_login_anchors() -> None:
    subscription = PodcastSubscription(
        "show", "https://example.test/feed", "Example show", SubscriptionSource.USER
    )
    controller = PodcastControllerStub(
        PodcastSnapshot(subscriptions=(subscription,), writable=True)
    )
    _assert_form_anchored(
        PodcastLoginDialog(cast("PodcastController", controller), "show")
    )


def test_phase_setup_anchors_without_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PhaseRuntimeController, "refresh", _skip_phase_refresh)
    controller = PhaseRuntimeController()
    try:
        _assert_form_anchored(PhaseRuntimeSetupDialog(controller))
    finally:
        controller.shutdown()


@pytest.mark.parametrize("has_proposals", [False, True])
def test_genius_shelf_keeps_heading_top_and_footer_bottom(has_proposals: bool) -> None:
    proposals = (
        (MixProposal(MIX_CATALOG[0], tuple(range(MIN_MIX_TRACKS))),)
        if has_proposals
        else ()
    )
    dialog = AddGeniusMixesDialog(proposals)
    dialog.show()
    APPLICATION.processEvents()
    heading = dialog.findChild(QLabel, "geniusMixDialogHeading")
    footer = dialog.findChild(QWidget, "geniusMixDialogFooter")
    assert heading is not None and footer is not None
    heading_rect, footer_height = heading.geometry(), footer.height()
    dialog.resize(dialog.width(), dialog.height() + 320)
    APPLICATION.processEvents()
    assert heading.geometry() == heading_rect
    assert footer.height() == footer_height
    assert footer.geometry().bottom() + 1 == dialog.height()


def test_podcast_settings_keeps_form_top_and_actions_bottom() -> None:
    dialog = PodcastSyncSettingsDialog("Example Podcast", PodcastSyncSettings())
    dialog.show()
    APPLICATION.processEvents()
    title = dialog.findChild(QLabel, "dialogTitle")
    slots = dialog.findChild(QComboBox, "podcastSyncEpisodeSlots")
    save = dialog.findChild(QPushButton, "podcastSyncSettingsSave")
    assert title is not None and slots is not None and save is not None
    title_rect, slots_rect = title.geometry(), slots.geometry()
    dialog.resize(dialog.width(), dialog.height() + 320)
    APPLICATION.processEvents()
    assert title.geometry() == title_rect
    assert slots.geometry() == slots_rect
    assert dialog.height() - save.geometry().bottom() - 1 == LAYOUT.space_lg


@pytest.mark.parametrize("requires_login", [False, True])
def test_podcast_rss_keeps_heading_and_form_top(
    requires_login: bool, theme: ThemeManager
) -> None:
    controller = PodcastControllerStub(PodcastSnapshot(writable=True))
    dialog = PodcastSearchDialog(cast("PodcastController", controller), theme)
    try:
        dialog.show()
        toggle = dialog.findChild(QPushButton, "podcastToggleRss")
        login = dialog.findChild(QCheckBox, "podcastRequiresLogin")
        title = dialog.findChild(QLabel, "podcastDialogTitle")
        save = dialog.findChild(QPushButton, "podcastSubscribeSelected")
        assert toggle is not None and login is not None
        assert title is not None and save is not None
        APPLICATION.processEvents()
        search_title = title.geometry()
        results = dialog.findChild(QStackedWidget)
        assert results is not None
        results_height, original_size = results.height(), dialog.size()
        toggle.click()
        login.setChecked(requires_login)
        APPLICATION.processEvents()
        title_rect, toggle_rect = title.geometry(), toggle.geometry()
        dialog.resize(dialog.width(), dialog.height() + 320)
        APPLICATION.processEvents()
        assert title.geometry() == title_rect
        assert toggle.geometry() == toggle_rect
        assert dialog.height() - _rect(save, dialog).bottom() - 1 == LAYOUT.space_lg
        toggle.click()
        APPLICATION.processEvents()
        assert title.geometry() == search_title
        assert (
            results.height() - results_height
            == dialog.height() - original_size.height()
        )
        dialog.resize(original_size)
        APPLICATION.processEvents()
        assert results.height() == results_height
    finally:
        dialog.close()


@pytest.mark.parametrize("kind", list(CalendarEntryKind))
def test_calendar_fields_grow_and_actions_stay_bottom(kind: CalendarEntryKind) -> None:
    dialog = CalendarEditor(kind, None)
    dialog.show()
    APPLICATION.processEvents()
    scroll = dialog.findChild(QScrollArea, "calendarEditorFields")
    save = dialog.findChild(QPushButton, "calendarEditorSave")
    assert scroll is not None and save is not None
    summary = dialog.findChild(QLineEdit, "calendarSummary")
    assert summary is not None
    summary_top = _rect(summary, dialog).top()
    top, height, original_height = scroll.y(), scroll.height(), dialog.height()
    original_maximum = scroll.verticalScrollBar().maximum()
    dialog.resize(dialog.width(), original_height + 400)
    APPLICATION.processEvents()
    assert scroll.y() == top
    assert scroll.height() - height == dialog.height() - original_height
    assert dialog.height() - save.geometry().bottom() - 1 == LAYOUT.space_lg
    assert _rect(summary, dialog).top() == summary_top
    assert scroll.verticalScrollBar().maximum() <= original_maximum
    dialog.resize(dialog.width(), original_height)
    APPLICATION.processEvents()
    assert scroll.height() == height
    assert scroll.verticalScrollBar().maximum() == original_maximum


def test_phase_details_expand_after_becoming_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PhaseRuntimeController, "refresh", _skip_phase_refresh)
    controller = PhaseRuntimeController()
    dialog = PhaseRuntimeSetupDialog(controller)
    try:
        dialog.show()
        APPLICATION.processEvents()
        controller.details = "Example error details"
        controller.changed.emit()
        APPLICATION.processEvents()
        details = dialog.findChild(QPlainTextEdit, "phaseRuntimeDetails")
        assert details is not None and details.isVisible()
        original_height, details_height = dialog.height(), details.height()
        dialog.resize(dialog.width(), original_height + 320)
        APPLICATION.processEvents()
        assert details.height() - details_height == dialog.height() - original_height
    finally:
        dialog.close()
        controller.shutdown()
