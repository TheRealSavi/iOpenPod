from types import SimpleNamespace
from typing import Any, cast

from GUI.app import MainWindow
from GUI.internal_drag import IOP_EXPORT_DRAG_MIME


class _FakeStack:
    def __init__(self, current_index: int = 0, current_widget=None):
        self._current_index = current_index
        self._current_widget = current_widget
        self.set_indices: list[int] = []

    def currentIndex(self) -> int:
        return self._current_index

    def currentWidget(self):
        return self._current_widget

    def setCurrentIndex(self, index: int) -> None:
        self.set_indices.append(index)
        self._current_index = index


class _FakeSidebar:
    def __init__(self):
        self.library_tabs_visible: list[bool] = []
        self.tag_fixes_available: list[bool] = []
        self.device_info_updates: list[dict] = []

    def setLibraryTabsVisible(self, visible: bool) -> None:
        self.library_tabs_visible.append(visible)

    def setTagFixesAvailable(self, available: bool) -> None:
        self.tag_fixes_available.append(available)

    def updateDeviceInfo(self, **kwargs) -> None:
        self.device_info_updates.append(kwargs)


class _FakeDropOverlay:
    def __init__(self, *, visible: bool = False):
        self._visible = visible
        self.show_count = 0
        self.hide_count = 0

    def isVisible(self) -> bool:
        return self._visible

    def show_overlay(self) -> None:
        self.show_count += 1
        self._visible = True

    def hide_overlay(self) -> None:
        self.hide_count += 1
        self._visible = False


class _FakeMime:
    def __init__(self, *, formats: set[str] | None = None, urls: list | None = None):
        self._formats = formats or set()
        self._urls = urls or []

    def hasFormat(self, name: str) -> bool:
        return name in self._formats

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self) -> list:
        return self._urls


class _FakeDropEvent:
    def __init__(self, mime: _FakeMime):
        self._mime = mime
        self.accepted = False
        self.ignored = False

    def mimeData(self) -> _FakeMime:
        return self._mime

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _FakeCache:
    def is_ready(self) -> bool:
        return True

    def get_tracks(self) -> list:
        return []

    def get_albums(self) -> list:
        return []

    def get_album_index(self) -> dict:
        return {}

    def get_album_only_index(self) -> dict:
        return {}

    def get_data(self) -> dict:
        return {}

    def get_playlists(self) -> list:
        return []


def _build_window_for_data_ready(
    *,
    current_page_index: int = 1,
    sync_results_visible: bool = True,
):
    window = SimpleNamespace()
    sync_review = SimpleNamespace(stack=_FakeStack(current_index=3))
    current_widget = sync_review if sync_results_visible else object()

    window.syncReview = sync_review
    window.centralStack = _FakeStack(
        current_index=current_page_index,
        current_widget=current_widget,
    )
    window.mainContentStack = _FakeStack()
    identity = SimpleNamespace(ipod_name="RoadPod", display_name="iPod Classic")
    window.device_manager = SimpleNamespace(
        device_path="E:/iPod",
        discovered_ipod=SimpleNamespace(path=""),
    )
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(identity=identity),
    )
    window.sidebar = _FakeSidebar()
    window.library_cache = _FakeCache()
    window.musicBrowser = SimpleNamespace(
        browserTrack=SimpleNamespace(clearTable=lambda clear_cache=False: None),
        onDataReady=lambda: None,
    )
    window._classify_tracks = lambda tracks: {
        "video": [],
        "podcast": [],
        "audiobook": [],
    }
    window._update_sidebar_visibility = lambda classified: None
    window._update_podcast_statuses = lambda: None
    window._is_sync_results_visible = MainWindow._is_sync_results_visible.__get__(
        window
    )
    window._refresh_default_page_state = MainWindow._refresh_default_page_state.__get__(
        window
    )
    window._show_default_page = MainWindow._show_default_page.__get__(window)
    window._should_show_default_page_on_data_ready = (
        MainWindow._should_show_default_page_on_data_ready.__get__(window)
    )
    return window


def _build_window_for_drop_events(*, overlay_visible: bool = False):
    window = SimpleNamespace()
    window._drop_overlay = _FakeDropOverlay(visible=overlay_visible)
    window.device_manager = SimpleNamespace(device_path="E:/iPod")
    window._sync_execute_worker = None
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(capabilities=None),
    )
    window.dropped_paths = []
    window._on_files_dropped = lambda paths: window.dropped_paths.extend(paths)
    return window


def _call_on_data_ready(window: object) -> None:
    MainWindow.onDataReady(cast(Any, window))


def test_post_sync_rescan_refreshes_library_without_leaving_results():
    window = _build_window_for_data_ready(sync_results_visible=True)
    window._keep_sync_results_visible_after_rescan = True
    scheduled_rebuild_pages: list[int] = []
    window._apply_match_ipod_accent = lambda dev: True
    window._schedule_themed_rebuild = (
        lambda restore_page=0: scheduled_rebuild_pages.append(restore_page)
    )

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == []
    assert window.mainContentStack.set_indices == [0]
    assert window._keep_sync_results_visible_after_rescan is False
    assert scheduled_rebuild_pages == [1]


def test_data_ready_preserves_settings_page():
    window = _build_window_for_data_ready(
        current_page_index=2,
        sync_results_visible=False,
    )
    window._keep_sync_results_visible_after_rescan = False
    window._apply_match_ipod_accent = lambda dev: False

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == []
    assert window.mainContentStack.set_indices == [0]
    assert window._keep_sync_results_visible_after_rescan is False


def test_data_ready_updates_main_page_when_main_page_is_visible():
    window = _build_window_for_data_ready(
        current_page_index=0,
        sync_results_visible=False,
    )
    window._keep_sync_results_visible_after_rescan = False
    window._apply_match_ipod_accent = lambda dev: False

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == [0]
    assert window.mainContentStack.set_indices == [0]


def test_own_export_drag_is_ignored_for_sync_drag_enter():
    window = _build_window_for_drop_events()
    event = _FakeDropEvent(_FakeMime(formats={IOP_EXPORT_DRAG_MIME}))

    MainWindow.dragEnterEvent(cast(Any, window), cast(Any, event))

    assert event.ignored
    assert not event.accepted
    assert window._drop_overlay.hide_count == 1
    assert window._drop_overlay.show_count == 0


def test_own_export_drag_is_ignored_for_sync_drop():
    window = _build_window_for_drop_events(overlay_visible=True)
    event = _FakeDropEvent(_FakeMime(formats={IOP_EXPORT_DRAG_MIME}))

    MainWindow.dropEvent(cast(Any, window), cast(Any, event))

    assert event.ignored
    assert not event.accepted
    assert window.dropped_paths == []
    assert window._drop_overlay.hide_count == 1
