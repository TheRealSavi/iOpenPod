"""Host Library artwork stays isolated from the Active iPod artwork source."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from time import monotonic

import pytest
from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStackedWidget, QToolButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    IPodLibraryViewMode,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
    HostMediaCacheStats,
    HostMediaLibrary,
)
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.selection_grouping import SelectionGroupingProxyModel
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView
from iOpenPod.GUI.widgets.library_content import LibraryContent
from iOpenPod.GUI.widgets.sync_selection_actions import SyncSelectionActions
from iPodDB.library import LibrarySnapshot, Track
from storage import HostPath


class _DeviceArtworkLoader:
    def __init__(self) -> None:
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        self.requests.append(request)
        return None


@pytest.mark.parametrize("selection_mode", [False, True])
def test_selection_grids_default_to_grouping_only_in_sync(selection_mode: bool) -> None:
    device_controller = ArtworkController(_DeviceArtworkLoader())
    device_provider = ArtworkPixmapProvider(device_controller)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    theme = ThemeManager(APPLICATION, settings)
    parent = QStackedWidget()
    browser = HostLibraryBrowser(
        settings,
        theme,
        device_provider,
        LibraryWorkspace(),
        parent,
        SyncSelection() if selection_mode else None,
    )
    try:
        assert (parent.findChild(SyncSelectionActions) is not None) is selection_mode
        for page_id in (
            PageId.ALBUMS,
            PageId.ARTISTS,
            PageId.GENRES,
            PageId.TV_SHOWS,
            PageId.MUSIC_VIDEOS,
            PageId.PHOTOS,
        ):
            page = browser.page_widgets[page_id]
            content = page.findChild(LibraryContent)
            if content is not None:
                for mode in IPodLibraryViewMode:
                    settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
                    assert content.whole_page_table is selection_mode
            grouping = next(
                button
                for button in page.findChildren(QToolButton)
                if button.accessibleName() == "Group by selection"
            )
            assert grouping.isChecked() is selection_mode
            grids = page.findChildren(EqualizedGridView)
            assert grids
            for grid in grids:
                assert grid.sectioned_layout is selection_mode
                model = grid.model()
                if selection_mode:
                    assert isinstance(model, SelectionGroupingProxyModel)
                    assert model.grouping_enabled
            if selection_mode:
                grouping.click()
                browser.retranslate()
                assert not grouping.isChecked()
                for grid in grids:
                    assert not grid.sectioned_layout
                    model = grid.model()
                    assert isinstance(model, SelectionGroupingProxyModel)
                    assert not model.grouping_enabled
    finally:
        browser.shutdown()
        device_provider.shutdown()
        device_controller.shutdown()
        parent.close()
        theme.close()


def test_host_browser_loads_cover_from_host_artwork_source(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (12, 8), "#32c850").save(cover)
    payload = cover.read_bytes()
    metadata = cover.stat()
    artwork_id = 4_668_449_358_420_290_499
    library = HostMediaLibrary(
        snapshot=LibrarySnapshot(
            tracks=(Track(1, "Track", "Artist", "Album", 1_000, artwork_id=artwork_id),)
        ),
        sources=(),
        issues=(),
        cache=HostMediaCacheStats(inspected=1),
        artwork_sources=(
            HostMediaArtworkSource(
                artwork_id,
                HostArtworkKind.FOLDER,
                HostPath(cover),
                metadata.st_size,
                metadata.st_mtime_ns,
                hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )
    device_loader = _DeviceArtworkLoader()
    device_controller = ArtworkController(device_loader)
    device_provider = ArtworkPixmapProvider(device_controller)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    parent = QStackedWidget()
    browser = HostLibraryBrowser(
        settings,
        theme,
        device_provider,
        LibraryWorkspace(),
        parent,
    )

    try:
        browser.load(library)
        assert browser.artwork_provider.pixmap(artwork_id, 44, 1.0) is None
        _wait_until(
            lambda: browser.artwork_provider.pixmap(artwork_id, 44, 1.0) is not None
        )

        pixmap = browser.artwork_provider.pixmap(artwork_id, 44, 1.0)
        assert pixmap is not None
        assert pixmap.toImage().pixelColor(0, 0).green() == 200
        assert device_loader.requests == []
    finally:
        browser.shutdown()
        device_provider.shutdown()
        device_controller.shutdown()
        parent.close()
        theme.close()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for Host artwork pixmap"
