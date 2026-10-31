"""Games navigation and background reservation tests using virtual devices."""

from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event, get_ident
from time import monotonic

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.library_filter_models import AlbumFilterProxyModel
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncRecoveryRequiredError,
)
from iOpenPod.app.services.game_installation import (
    GameInstallationPhase,
    GameInstallationProgress,
)
from iOpenPod.app.services.game_library import GameCatalog, InstalledGame
from iOpenPod.app.services.game_uninstallation import (
    GameRemovalPhase,
    GameRemovalProgress,
)
from iOpenPod.app.services.games import GamesResult
from iOpenPod.GUI.delegates.game_card_delegate import (
    TITLE_ROLE,
    VERSION_ROLE,
    GameCardDelegate,
)
from iOpenPod.GUI.dialogs.game_catalog import GameCatalogDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.games_page import GamesPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.selection_grid import SelectionGridView
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.status_controls import StatusBarControls
from iPodDB.library import LibrarySnapshot, Track
from storage import FileFingerprint, HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform


@pytest.fixture(autouse=True)
def prepared_host_game_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUI tests never download payloads or depend on the user's Host cache."""

    def prepare(
        _coordinator: DeviceCoordinator,
        _active: ActiveIPod,
        _cancelled: Event,
        *,
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        return None

    monkeypatch.setattr(DeviceCoordinator, "prepare_game_files", prepare)


def wait_for_games(controller: object) -> None:
    from iOpenPod.app.games_controller import GamesController

    assert isinstance(controller, GamesController)
    deadline = monotonic() + 5
    while controller.busy and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(5)
    assert not controller.busy


def answer_uninstall_confirmation(
    answer: str,
    *,
    before_reply: Callable[[], None] = lambda: None,
) -> list[tuple[str, str, str, bool, Qt.TextFormat]]:
    observations: list[tuple[str, str, str, bool, Qt.TextFormat]] = []

    def reply() -> None:
        dialog = APPLICATION.activeModalWidget()
        if not isinstance(dialog, QMessageBox):
            return
        observations.append(
            (
                dialog.windowTitle(),
                dialog.text(),
                dialog.informativeText(),
                dialog.defaultButton()
                is dialog.button(QMessageBox.StandardButton.Cancel),
                dialog.textFormat(),
            )
        )
        before_reply()
        if answer == "enter":
            QTest.keyClick(dialog, Qt.Key.Key_Return)
        elif answer == "escape":
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        elif answer == "close":
            dialog.close()
        elif answer == "confirm":
            for button in dialog.buttons():
                if dialog.buttonRole(button) is QMessageBox.ButtonRole.DestructiveRole:
                    button.click()
                    return
        else:
            dialog.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(0, reply)
    return observations


def test_sidebar_opens_games_page_with_one_disabled_action_without_device() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        navigation = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.GAMES.value
        )
        assert navigation.isHidden()
        navigation.click()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None and isinstance(pages.currentWidget(), GamesPage)
        page = pages.currentWidget()
        assert page is not None
        action = page.findChild(QPushButton, "gimmeGames")
        assert action is not None
        assert action.text() == "Gimme Games" and not action.isEnabled()
        header = page.findChild(PageHeader)
        assert header is not None and header.title_label.text() == "Games"
        assert header.findChild(QPushButton, "gimmeGames") is action
        empty_action = page.findChild(QPushButton, "gamesEmptyAdd")
        assert empty_action is not None and not empty_action.isEnabled()
        assert len(page.findChildren(QPushButton)) == 2
        empty = page.findChild(QLabel, "gamesEmptyTitle")
        assert empty is not None and not empty.isVisible()
        assert page.findChild(QPushButton, "refreshGames") is None
        assert not context.games_controller.start()
    finally:
        window.close()
        context.shutdown()


def test_games_sidebar_visibility_changes_with_selection_and_disconnect() -> None:
    sidebar = Sidebar()
    try:
        assert not sidebar.page_available(PageId.GAMES)
        for supported in (True, False, True):
            profile = next(
                p
                for p in DEFAULT_DEVICE_REGISTRY.profiles
                if p.capabilities.supports_games is supported
            )
            candidate = DeviceCandidate(
                DeviceCandidateId("games-sidebar"),
                "iPod",
                "Virtual",
                "virtual",
                IdentificationStatus.EXACT,
                DeviceReadiness.READY,
                profile,
                1000,
                500,
            )
            active = ActiveIPod(
                candidate,
                profile,
                LibrarySnapshot(()),
                "iTunesDB",
                FileFingerprint(0, 0, 0, 0, "0" * 64),
            )
            sidebar.set_active_ipod(active)
            assert sidebar.page_available(PageId.GAMES) is supported
        sidebar.set_active_ipod(None)
        assert not sidebar.page_available(PageId.GAMES)
    finally:
        sidebar.deleteLater()


def test_games_gamepad_glyph_has_visible_pixels() -> None:
    image = glyph_icon("games", 24, QColor("#ffffff")).pixmap(24, 24).toImage()
    assert any(
        image.pixelColor(x, y).alpha()
        for x in range(image.width())
        for y in range(image.height())
    )


def test_games_and_albums_share_column_geometry_on_resize_and_scrollbar_changes() -> (
    None
):
    context = build_context()
    context.track_model.replace_tracks(
        tuple(Track(i + 1, "Song", "Artist", f"Album {i}", 120000) for i in range(140))
    )
    proxy = AlbumFilterProxyModel(context.album_model)
    provider = ArtworkPixmapProvider(context.artwork_controller)
    albums = AlbumGridView(proxy, context.theme_manager, provider)
    page = GamesPage(context.games_controller, theme_manager=context.theme_manager)
    games = page.findChild(SelectionGridView, "gamesGrid")
    assert games is not None
    model = games.model()
    assert isinstance(model, QStandardItemModel)
    try:
        page.show()
        albums.show()
        for width in (420, 793, 1000, 1193, 600):
            for count in (2, 140):
                context.track_model.replace_tracks(
                    tuple(
                        Track(i + 1, "Song", "Artist", f"Album {i}", 120000)
                        for i in range(count)
                    )
                )
                model.clear()
                for i in range(count):
                    item = QStandardItem(f"Game {i}")
                    item.setData(f"Game {i}", TITLE_ROLE)
                    model.appendRow(item)
                page.resize(width, 420)
                albums.resize(width, 420)
                for _ in range(4):
                    APPLICATION.processEvents()
                    games.doItemsLayout()
                    albums.doItemsLayout()
                assert games.viewport().width() == albums.viewport().width()
                assert games.gridSize().width() == albums.gridSize().width()
                # Landscape cards change row height, not the column math.
                for column in range(min(8, count)):
                    assert (
                        games.visualRect(model.index(column, 0)).x()
                        == albums.visualRect(proxy.index(column, 0)).x()
                    )
    finally:
        page.close()
        albums.close()
        context.shutdown()


def test_games_grid_loads_titles_versions_covers_and_clears_after_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    buffer = BytesIO()
    Image.new("RGB", (320, 240), "red").save(buffer, "JPEG")
    data = buffer.getvalue()
    calls: list[int] = []

    def load(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
        calls.append(get_ident())
        return GameCatalog(
            (
                InstalledGame("1D000", "Phase", "1.0.0", data),
                InstalledGame("broken-art", "Another game", "1.2", b"invalid image"),
            )
        )

    monkeypatch.setattr(coordinator, "load_installed_games", load)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    # Playlist editing needs this inventory even if Games has never been opened.
    deadline = monotonic() + 5
    while not context.games_controller.catalog_ready and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(5)
    assert context.games_controller.catalog_ready
    assert len(calls) == 1
    page = GamesPage(context.games_controller)
    try:
        page.show()
        grid = page.findChild(SelectionGridView, "gamesGrid")
        assert grid is not None
        model = grid.model()
        assert isinstance(model, QStandardItemModel)
        deadline = monotonic() + 5
        while model.rowCount() != 2 and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert model.rowCount() == 2
        assert calls and calls[0] != get_ident()
        first, second = model.item(0), model.item(1)
        assert first.text() == "Phase\nVersion 1.0.0"
        assert isinstance(grid.itemDelegate(), GameCardDelegate)
        assert first.data(TITLE_ROLE) == "Phase"
        assert first.data(VERSION_ROLE) == "Version 1.0.0"
        assert first.icon().actualSize(QSize(192, 144)) == QSize(192, 144)
        assert not second.icon().isNull()

        def authorize(_active: ActiveIPod, _cancelled: Event) -> GamesResult:
            return GamesResult(0, 0, 49, False)

        monkeypatch.setattr(coordinator, "install_game_authorizations", authorize)
        monkeypatch.setattr(
            context.games_controller,
            "offered_games",
            lambda: (
                InstalledGame("1D000", "Phase", "2.0"),
                InstalledGame("new", "New game", "1.0"),
            ),
        )
        action = page.findChild(QPushButton, "gimmeGames")
        assert action is not None
        action.click()
        wait_for_games(context.games_controller)
        catalog_dialog = page.findChild(GameCatalogDialog)
        assert catalog_dialog is not None and catalog_dialog.isVisible()
        deadline = monotonic() + 5
        while not context.games_controller.catalog_ready and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert context.games_controller.catalog_ready
        offered = catalog_dialog.findChild(SelectionGridView, "availableGamesGrid")
        search = catalog_dialog.findChild(SearchField, "gameCatalogSearch")
        assert offered is not None and search is not None
        assert offered.model().rowCount() == 1
        assert offered.model().index(0, 0).data(TITLE_ROLE) == "New game"
        assert len(calls) == 1
        assert all(
            label.text() in {"Games", "Available games", "No available games", ""}
            for label in page.findChildren(QLabel)
            if label.isVisible()
        )
        deadline = monotonic() + 5
        while context.games_controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert not context.games_controller.busy
        catalog_dialog.reject()
        action.click()
        wait_for_games(context.games_controller)
        assert page.findChild(GameCatalogDialog) is catalog_dialog
        assert catalog_dialog.isVisible() and offered.model().rowCount() == 1
        assert len(calls) == 1  # Reopening consumes the installed grid's snapshot.
        search.setText("Phase")
        QTest.qWait(220)
        assert offered.model().rowCount() == 0
        empty_title = page.findChild(QLabel, "gamesEmptyTitle")
        empty_action = page.findChild(QPushButton, "gamesEmptyAdd")
        assert empty_title is not None and not empty_title.isVisible()
        assert empty_action is not None
        monkeypatch.setattr(
            coordinator, "load_installed_games", lambda *_: GameCatalog()
        )
        context.games_controller.load_games(force=True)
        deadline = monotonic() + 5
        while not context.games_controller.catalog_ready and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert context.games_controller.catalog_ready
        assert model.rowCount() == 0 and not grid.isVisible()
        assert empty_title.isVisible()
        assert empty_title.text() == "No games on this iPod"
        assert empty_title.alignment() == Qt.AlignmentFlag.AlignCenter
        empty_detail = page.findChild(QLabel, "gamesEmptyDetail")
        assert empty_detail is not None and empty_detail.text() == "Choose games to add"
        assert empty_detail.height() >= empty_detail.heightForWidth(
            empty_detail.width()
        )
        assert empty_action.isVisible() and empty_action.isEnabled()
        assert empty_action.text() == "Gimme Games"
        empty_action.click()
        assert not empty_action.isEnabled() and not action.isEnabled()
        wait_for_games(context.games_controller)
        assert empty_action.isEnabled() and action.isEnabled()
        assert catalog_dialog.isVisible()
        scan_started, release_scan = Event(), Event()

        def delayed(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
            scan_started.set()
            assert release_scan.wait(5)
            return GameCatalog((InstalledGame("stale", "Old device", "1.0"),))

        monkeypatch.setattr(coordinator, "load_installed_games", delayed)
        context.games_controller.load_games(force=True)
        assert scan_started.wait(5)
        assert not empty_title.isVisible()
        search.clear()
        QTest.qWait(220)
        assert offered.model().rowCount() == 0
        context.device_controller.finish_sync_recovery(None)
        assert not catalog_dialog.isVisible()
        assert not empty_title.isVisible() and not empty_action.isEnabled()
        release_scan.set()
        context.games_controller.shutdown()
        APPLICATION.processEvents()
        assert model.rowCount() == 0
    finally:
        page.close()
        context.shutdown()


def test_catalog_search_always_excludes_installed_games() -> None:
    games = (
        InstalledGame("ABC", "Alpha Chess", "2.0"),
        InstalledGame("DEF", "Beta Chess", "1.0"),
        InstalledGame("GHI", "Music Quiz", "1.0"),
    )
    installed = (
        InstalledGame("renamed-folder", "Old title", "1.0", identifier=" abc "),
        InstalledGame("ghi", "Damaged manifest", ""),
    )
    dialog = GameCatalogDialog(games)
    grid = dialog.findChild(SelectionGridView, "availableGamesGrid")
    search = dialog.findChild(SearchField, "gameCatalogSearch")
    assert grid is not None and search is not None
    empty = dialog.findChild(QLabel, "gameCatalogEmpty")
    body = dialog.findChild(QStackedWidget, "gameCatalogBody")
    assert empty is not None and body is not None
    assert empty.text() == "No available games"
    assert empty.alignment() == Qt.AlignmentFlag.AlignCenter
    model = grid.model()

    def titles() -> list[object]:
        return [model.index(row, 0).data(TITLE_ROLE) for row in range(model.rowCount())]

    def query(text: str) -> None:
        search.setText(text)
        QTest.qWait(220)

    try:
        dialog.set_installed_games(None)
        query("chess")
        assert titles() == []  # Never expose installations before the scan finishes.
        dialog.set_installed_games(installed)
        assert titles() == ["Beta Chess"]
        assert body.currentWidget() is grid
        query("ALPHA")
        assert titles() == []
        assert body.currentWidget() is empty
        query(" BETA ")
        assert titles() == ["Beta Chess"]
        assert body.currentWidget() is grid
        query(".")
        assert titles() == []  # Search text is literal, not a regular expression.
        query("")
        assert titles() == ["Beta Chess"]
        query("chess")
        dialog.set_installed_games((InstalledGame("def", "Beta Chess", "1.0"),))
        assert titles() == ["Alpha Chess"]
        dialog.set_installed_games(games)
        query("")
        assert titles() == []
        assert body.currentWidget() is empty
    finally:
        dialog.hide()
        dialog.deleteLater()


def test_catalog_checks_multiple_games_across_search_and_keyboard() -> None:
    dialog = GameCatalogDialog(
        (
            InstalledGame("ABC", "Alpha", "1.0"),
            InstalledGame("DEF", "Beta", "1.0"),
        )
    )
    grid = dialog.findChild(SelectionGridView, "availableGamesGrid")
    search = dialog.findChild(SearchField, "gameCatalogSearch")
    add = dialog.findChild(QPushButton, "addGames")
    assert grid is not None and search is not None and add is not None
    requests: list[object] = []
    dialog.installRequested.connect(requests.append)
    try:
        dialog.show()
        APPLICATION.processEvents()
        assert not add.isEnabled()
        first = grid.model().index(0, 0)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(first).center(),
        )
        assert first.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        assert not add.isEnabled()  # Authorization has not completed yet.
        dialog.set_installation_state(available=True, installing=False)
        assert add.isEnabled()
        search.setText("Beta")
        QTest.qWait(220)
        second = grid.model().index(0, 0)
        assert second.data(TITLE_ROLE) == "Beta"
        grid.setCurrentIndex(second)
        QTest.keyClick(grid, Qt.Key.Key_Space)
        assert second.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        add.click()
        assert requests == [("ABC", "DEF")]
        QTest.keyClick(grid, Qt.Key.Key_Space)
        add.click()
        assert requests[-1] == ("ABC",)  # Search hides, but does not uncheck Alpha.
        dialog.set_installation_state(available=False, installing=True)
        assert add.text() == "Adding…" and not add.isEnabled() and not grid.isEnabled()
        dialog.set_installed_games((InstalledGame("abc", "Alpha", "1.0"),))
        dialog.set_installation_state(available=True, installing=False)
        assert not add.isEnabled()
    finally:
        dialog.hide()
        dialog.deleteLater()


def test_catalog_select_all_checks_only_visible_available_games_in_left_footer() -> (
    None
):
    games = (
        InstalledGame("ABC", "Alpha Chess", "1.0"),
        InstalledGame("DEF", "Beta Chess", "1.0"),
        InstalledGame("GHI", "Music Quiz", "1.0"),
    )
    dialog = GameCatalogDialog(games)
    select_all = dialog.findChild(QPushButton, "selectAllGames")
    add = dialog.findChild(QPushButton, "addGames")
    grid = dialog.findChild(SelectionGridView, "availableGamesGrid")
    search = dialog.findChild(SearchField, "gameCatalogSearch")
    assert (
        select_all is not None
        and add is not None
        and grid is not None
        and search is not None
    )
    requests: list[object] = []
    dialog.installRequested.connect(requests.append)
    try:
        dialog.set_installed_games((games[0],))
        dialog.set_installation_state(available=True, installing=False)
        dialog.show()
        APPLICATION.processEvents()
        assert select_all.text() == "Select all"
        assert select_all.mapTo(dialog, QPoint()).x() < add.mapTo(dialog, QPoint()).x()
        assert select_all.mapTo(dialog, QPoint()).y() == add.mapTo(dialog, QPoint()).y()
        search.setText("Chess")
        QTest.qWait(220)
        select_all.click()
        add.click()
        assert requests == [("DEF",)]
        search.clear()
        QTest.qWait(220)
        select_all.click()
        add.click()
        assert requests[-1] == ("DEF", "GHI")
        dialog.set_installation_state(available=False, installing=True)
        assert not select_all.isEnabled()
        dialog.set_installation_state(available=True, installing=False)
        dialog.set_installed_games(None)
        assert not select_all.isEnabled()
        dialog.set_installed_games(games)
        assert not select_all.isEnabled()
    finally:
        dialog.hide()
        dialog.deleteLater()


@pytest.mark.parametrize("failure", ["", "validation", "recovery"])
def test_game_context_menu_uninstalls_clicked_item_off_gui_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    first = InstalledGame("1D000", "Phase", "1.0", identifier="1D000")
    second = InstalledGame("ABCDE", "Other game", "1.0", identifier="ABCDE")

    def load(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
        return GameCatalog((first, second))

    monkeypatch.setattr(coordinator, "load_installed_games", load)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    page = GamesPage(context.games_controller)
    started, release = Event(), Event()
    threads: list[int] = []
    controls = StatusBarControls(context.status)
    status_threads: list[int] = []
    context.status.activeMessagesChanged.connect(
        lambda: status_threads.append(get_ident())
    )

    def uninstall(
        expected: ActiveIPod,
        game: InstalledGame,
        _cancelled: Event,
        *,
        progress: Callable[[GameRemovalProgress], None],
    ) -> GameCatalog:
        assert expected is active and game == first
        threads.append(get_ident())
        progress(GameRemovalProgress(GameRemovalPhase.REMOVING, 2, 4))
        started.set()
        assert release.wait(5)
        if failure == "validation":
            raise ValueError("Game folder changed")
        if failure == "recovery":
            raise SyncRecoveryRequiredError("retained journal")
        return GameCatalog((second,))

    monkeypatch.setattr(coordinator, "uninstall_game", uninstall)
    try:
        page.resize(800, 600)
        page.show()
        deadline = monotonic() + 5
        while not context.games_controller.can_uninstall and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert context.games_controller.can_uninstall
        assert (
            not context.games_controller.can_install
        )  # No Gimme Games/authorization prerequisite.
        grid = page.findChild(SelectionGridView, "gamesGrid")
        menu = page.findChild(QMenu, "gameContextMenu")
        action = page.findChild(QAction, "uninstallGame")
        assert grid is not None and menu is not None and action is not None
        assert grid.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        assert action.text() == "Uninstall"
        grid.setCurrentIndex(grid.model().index(1, 0))
        grid.customContextMenuRequested.emit(
            grid.visualRect(grid.model().index(0, 0)).center()
        )
        assert menu.isVisible() and action.isEnabled()
        # An empty-space request discards the previously targeted game.
        grid.customContextMenuRequested.emit(
            QPoint(grid.viewport().width() - 1, grid.viewport().height() - 1)
        )
        assert not menu.isVisible()
        action.trigger()
        assert not started.is_set()
        grid.customContextMenuRequested.emit(
            grid.visualRect(grid.model().index(0, 0)).center()
        )
        menu.hide()
        confirmations = answer_uninstall_confirmation("confirm")
        action.trigger()
        assert confirmations == [
            (
                "Uninstall game?",
                'Uninstall "Phase"?',
                "The game, its saved progress, and its statistics will be deleted from this iPod.",
                True,
                Qt.TextFormat.PlainText,
            )
        ]
        assert controls.progress.minimum() == controls.progress.maximum() == 0
        assert started.wait(5)
        deadline = monotonic() + 5
        while controls.progress.value() != 5000 and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert controls.progress.isVisible() and controls.progress.value() == 5000
        assert context.status.current_message == "Uninstalling Phase…"
        assert context.games_controller.busy and context.device_controller.busy
        assert not action.isEnabled() and not context.games_controller.uninstall(second)
        release.set()
        deadline = monotonic() + 5
        while context.games_controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert not context.games_controller.busy and not context.device_controller.busy
        assert not any(
            value.source == "games.uninstall"
            for value in context.status.active_messages
        )
        assert controls.progress.isHidden()
        assert threads and threads[0] != get_ident()
        assert status_threads and set(status_threads) == {get_ident()}
        if not failure:
            assert grid.model().rowCount() == 1
            assert grid.model().index(0, 0).data(TITLE_ROLE) == "Other game"
            assert context.games_controller.message == ""
        else:
            assert grid.model().rowCount() == 2
            assert context.games_controller.message
            assert context.games_controller.can_uninstall is (failure == "validation")
    finally:
        release.set()
        page.close()
        controls.close()
        context.shutdown()


@pytest.mark.parametrize(
    "answer", ["cancel", "escape", "enter", "close", "device-change"]
)
def test_uninstall_confirmation_cancellation_or_device_change_prevents_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    game = InstalledGame("1D000", "<b>Phase</b>", "1.0")

    def load(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
        return GameCatalog((game,))

    monkeypatch.setattr(coordinator, "load_installed_games", load)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    page = GamesPage(context.games_controller)
    calls: list[InstalledGame] = []

    def uninstall(game: InstalledGame) -> bool:
        calls.append(game)
        return True

    monkeypatch.setattr(context.games_controller, "uninstall", uninstall)
    try:
        page.show()
        deadline = monotonic() + 5
        while not context.games_controller.can_uninstall and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        grid = page.findChild(SelectionGridView, "gamesGrid")
        action = page.findChild(QAction, "uninstallGame")
        assert grid is not None and action is not None
        grid.customContextMenuRequested.emit(
            grid.visualRect(grid.model().index(0, 0)).center()
        )
        if answer == "device-change":
            observations = answer_uninstall_confirmation(
                "confirm",
                before_reply=lambda: context.device_controller.finish_sync_recovery(
                    None
                ),
            )
        else:
            observations = answer_uninstall_confirmation(answer)
        action.trigger()
        assert observations and observations[0][1] == 'Uninstall "<b>Phase</b>"?'
        assert observations[0][-1] == Qt.TextFormat.PlainText
        assert not calls and not context.games_controller.busy
        assert not any(
            status.source == "games.uninstall"
            for status in context.status.active_messages
        )
    finally:
        page.close()
        context.shutdown()


def test_game_menu_discards_target_when_active_ipod_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    game = InstalledGame("1D000", "Phase", "1.0")

    def load(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
        return GameCatalog((game,))

    monkeypatch.setattr(coordinator, "load_installed_games", load)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    page = GamesPage(context.games_controller)
    try:
        page.show()
        deadline = monotonic() + 5
        while not context.games_controller.catalog_ready and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        grid = page.findChild(SelectionGridView, "gamesGrid")
        menu = page.findChild(QMenu, "gameContextMenu")
        action = page.findChild(QAction, "uninstallGame")
        assert grid is not None and menu is not None and action is not None
        grid.customContextMenuRequested.emit(
            grid.visualRect(grid.model().index(0, 0)).center()
        )
        assert menu.isVisible()
        context.device_controller.finish_sync_recovery(None)
        assert not menu.isVisible() and not action.isEnabled()
        action.trigger()
        assert not context.games_controller.busy
    finally:
        page.close()
        context.shutdown()


@pytest.mark.parametrize("stop", ["device-change", "shutdown"])
@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_queued_game_progress_cannot_restore_an_invalidated_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
    operation: str,
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    game = InstalledGame("1D000", "Phase", "1.0")

    def load(_active: ActiveIPod, _cancelled: Event) -> GameCatalog:
        return GameCatalog((game,))

    monkeypatch.setattr(coordinator, "load_installed_games", load)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    started, release = Event(), Event()

    def uninstall(
        _active: ActiveIPod,
        _game: InstalledGame,
        _cancelled: Event,
        *,
        progress: Callable[[GameRemovalProgress], None],
    ) -> GameCatalog:
        progress(GameRemovalProgress(GameRemovalPhase.REMOVING, 1, 2))
        started.set()
        assert release.wait(5)
        progress(GameRemovalProgress(GameRemovalPhase.REMOVING, 2, 2))
        return GameCatalog()

    monkeypatch.setattr(coordinator, "uninstall_game", uninstall)

    def install(
        _active: ActiveIPod,
        _identifiers: tuple[str, ...],
        _cancelled: Event,
        *,
        progress: Callable[[GameInstallationProgress], None],
    ) -> GameCatalog:
        progress(GameInstallationProgress(GameInstallationPhase.INSTALLING, 1, 2))
        started.set()
        assert release.wait(5)
        progress(GameInstallationProgress(GameInstallationPhase.INSTALLING, 2, 2))
        return GameCatalog()

    def authorize(_active: ActiveIPod, _cancelled: Event) -> GamesResult:
        return GamesResult(0, 0, 1, False)

    monkeypatch.setattr(coordinator, "install_games", install)
    monkeypatch.setattr(coordinator, "install_game_authorizations", authorize)
    source = "games.install" if operation == "install" else "games.uninstall"
    controller = context.games_controller
    try:
        deadline = monotonic() + 5
        while not controller.can_uninstall and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        if operation == "install":
            assert controller.start()
            deadline = monotonic() + 5
            while controller.busy and monotonic() < deadline:
                APPLICATION.processEvents()
                QTest.qWait(5)
            assert controller.install(("ABCDE",))
        else:
            assert controller.uninstall(game)
        assert started.wait(5)
        assert any(status.source == source for status in context.status.active_messages)
        if stop == "device-change":
            context.device_controller.finish_sync_recovery(None)
            release.set()
        else:
            release.set()
            controller.shutdown()
        assert not any(
            status.source == source for status in context.status.active_messages
        )
        deadline = monotonic() + 5
        while controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        APPLICATION.processEvents()
        assert not controller.busy
        assert not any(
            status.source == source for status in context.status.active_messages
        )
    finally:
        release.set()
        context.shutdown()


@pytest.mark.parametrize("failure", ["", "validation", "recovery"])
def test_checked_games_install_in_background_and_refresh_both_grids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)

    def authorize(_active: ActiveIPod, _cancelled: Event) -> GamesResult:
        return GamesResult(0, 0, 1, False)

    monkeypatch.setattr(coordinator, "install_game_authorizations", authorize)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    offered = (
        InstalledGame("ABC", "Alpha", "1.0"),
        InstalledGame("DEF", "Beta", "1.0"),
    )
    monkeypatch.setattr(context.games_controller, "offered_games", lambda: offered)
    started, release = Event(), Event()
    threads: list[int] = []
    controls = StatusBarControls(context.status)
    status_messages: list[str] = []
    context.status.messageChanged.connect(status_messages.append)

    def install(
        expected: ActiveIPod,
        identifiers: tuple[str, ...],
        _cancelled: Event,
        *,
        progress: Callable[[GameInstallationProgress], None],
    ) -> GameCatalog:
        assert expected is active and identifiers == ("ABC", "DEF")
        threads.append(get_ident())
        progress(GameInstallationProgress(GameInstallationPhase.INSTALLING, 2, 4))
        started.set()
        assert release.wait(5)
        if failure == "validation":
            raise ValueError("Archive failed verification")
        if failure == "recovery":
            raise SyncRecoveryRequiredError("retained journal")
        return GameCatalog(offered)

    monkeypatch.setattr(coordinator, "install_games", install)
    page = GamesPage(context.games_controller)

    def settle() -> None:
        deadline = monotonic() + 5
        while (
            context.games_controller.busy or not context.games_controller.catalog_ready
        ) and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert (
            not context.games_controller.busy and context.games_controller.catalog_ready
        )

    try:
        page.show()
        settle()
        button = page.findChild(QPushButton, "gimmeGames")
        assert button is not None
        button.click()
        settle()
        dialog = page.findChild(GameCatalogDialog)
        assert dialog is not None
        grid = dialog.findChild(SelectionGridView, "availableGamesGrid")
        add = dialog.findChild(QPushButton, "addGames")
        assert grid is not None and add is not None
        for row in range(2):
            grid.model().setData(
                grid.model().index(row, 0),
                Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
        assert add.isEnabled()
        add.click()
        assert started.wait(5)
        deadline = monotonic() + 5
        while controls.progress.value() != 5000 and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert controls.progress.isVisible() and controls.progress.value() == 5000
        assert context.status.current_message == "Installing games…"
        assert not any("Extracting" in message for message in status_messages)
        assert context.games_controller.installing and context.device_controller.busy
        assert not add.isEnabled() and add.text() == "Adding…"
        assert not context.games_controller.install(("ABC",))
        release.set()
        settle()
        assert not any(
            status.source == "games.install"
            for status in context.status.active_messages
        )
        assert controls.progress.isHidden()
        assert threads and threads[0] != get_ident()
        installed = page.findChild(SelectionGridView, "gamesGrid")
        assert installed is not None
        if not failure:
            assert installed.model().rowCount() == 2
            assert grid.model().rowCount() == 0
            empty = dialog.findChild(QLabel, "gameCatalogEmpty")
            assert empty is not None and empty.isVisible()
            assert context.games_controller.message == "" and not add.isEnabled()
        else:
            assert installed.model().rowCount() == 0 and grid.model().rowCount() == 2
            assert context.games_controller.message
            assert add.isEnabled() is (failure == "validation")
            assert context.device_controller.device_writes_allowed is (
                failure == "validation"
            )
    finally:
        release.set()
        page.close()
        controls.close()
        context.shutdown()


@pytest.mark.parametrize("dismiss", ["button", "escape", "window"])
def test_catalog_dismissal_retains_native_window(dismiss: str) -> None:
    dialog = GameCatalogDialog((InstalledGame("game", "Game", "1.0"),))
    results: list[int] = []
    dialog.finished.connect(results.append)
    try:
        dialog.show()
        APPLICATION.processEvents()
        window = dialog.winId()
        if dismiss == "button":
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            buttons.button(QDialogButtonBox.StandardButton.Close).click()
        elif dismiss == "escape":
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        else:
            dialog.close()
        APPLICATION.processEvents()
        assert not dialog.isVisible()
        assert results == [GameCatalogDialog.DialogCode.Rejected]
        dialog.show()
        APPLICATION.processEvents()
        assert dialog.isVisible() and dialog.winId() == window
        assert dialog.windowModality() is Qt.WindowModality.WindowModal
    finally:
        dialog.hide()
        dialog.deleteLater()


@pytest.mark.parametrize("failure", [False, True])
def test_gimme_games_prepares_host_files_with_progress_before_authorization_and_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    started, release = Event(), Event()
    authorized: list[ActiveIPod] = []
    threads: list[int] = []

    def prepare(
        expected: ActiveIPod,
        _cancelled: Event,
        *,
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        assert expected is active
        threads.append(get_ident())
        progress(GameInstallationProgress(GameInstallationPhase.DOWNLOADING, 50, 100))
        started.set()
        assert release.wait(5)
        if failure:
            raise OSError("download interrupted")
        progress(GameInstallationProgress(GameInstallationPhase.EXTRACTING, 100, 100))

    def authorize(expected: ActiveIPod, _cancelled: Event) -> GamesResult:
        authorized.append(expected)
        return GamesResult(0, 0, 1, False)

    monkeypatch.setattr(coordinator, "prepare_game_files", prepare)
    monkeypatch.setattr(coordinator, "install_game_authorizations", authorize)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    controller = context.games_controller
    page = GamesPage(controller)
    controls = StatusBarControls(context.status)
    messages: list[str] = []
    context.status.messageChanged.connect(messages.append)
    try:
        page.show()
        button = page.findChild(QPushButton, "gimmeGames")
        assert button is not None and button.isEnabled()
        button.click()
        assert started.wait(5)
        deadline = monotonic() + 5
        while controls.progress.value() != 5000 and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert controls.progress.isVisible() and controls.progress.value() == 5000
        assert context.status.current_message == "Downloading game files…"
        assert page.findChild(GameCatalogDialog) is None and not authorized
        assert not button.isEnabled() and threads[0] != get_ident()
        release.set()
        wait_for_games(controller)
        assert controls.progress.isHidden() and not context.device_controller.busy
        if failure:
            assert page.findChild(GameCatalogDialog) is None and not authorized
            assert (
                controller.message
                == "Game files could not be prepared: download interrupted"
            )
        else:
            assert authorized == [active] and not controller.message
            assert "Extracting game archives…" in messages
            dialog = page.findChild(GameCatalogDialog)
            assert dialog is not None and dialog.isVisible()
    finally:
        release.set()
        page.close()
        controls.close()
        context.shutdown()


@pytest.mark.parametrize("failure", ["", "unchanged", "validation", "recovery"])
def test_games_runs_off_gui_thread_and_releases_device_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    controller = context.games_controller
    # Let the startup Podcast scan release its reservation before this workflow.
    deadline = monotonic() + 5
    while context.podcast_controller.busy and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(5)
    assert not context.podcast_controller.busy
    page = GamesPage(controller)
    controller.load_games()
    started = Event()
    release = Event()
    threads: list[int] = []

    def install(expected: ActiveIPod, _cancelled: Event) -> GamesResult:
        assert expected is active
        threads.append(get_ident())
        started.set()
        assert release.wait(5)
        if failure == "validation":
            raise ValueError("Invalid authorization")
        if failure == "recovery":
            raise SyncRecoveryRequiredError("retained journal")
        return GamesResult(2, 1, 3, failure != "unchanged")

    monkeypatch.setattr(coordinator, "install_game_authorizations", install)
    try:
        button = page.findChild(QPushButton, "gimmeGames")
        assert button is not None and button.isEnabled()
        button.click()
        assert started.wait(5)
        assert page.findChild(GameCatalogDialog) is None
        assert controller.busy and context.device_controller.busy
        assert not button.isEnabled() and not controller.start()
        assert threads[0] != get_ident()
        release.set()
        wait_for_games(controller)
        assert not context.device_controller.busy
        if failure in {"validation", "recovery"}:
            assert page.findChild(GameCatalogDialog) is None
            assert controller.message
            assert context.device_controller.device_writes_allowed is (
                failure == "validation"
            )
        else:
            assert not controller.message
            dialog = page.findChild(GameCatalogDialog)
            assert dialog is not None and dialog.isVisible()
            offered = dialog.findChild(SelectionGridView, "availableGamesGrid")
            assert offered is not None and offered.model().rowCount() == 49
            native_window = dialog.winId()
            model = offered.model()
            for attempt in range(2):
                dialog.reject()
                button.click()
                wait_for_games(controller)
                assert page.findChild(GameCatalogDialog) is dialog
                assert dialog.isVisible() and dialog.winId() == native_window
                assert offered.model() is model and len(threads) == attempt + 2
    finally:
        release.set()
        page.close()
        context.shutdown()


@pytest.mark.parametrize("interruption", ["shutdown", "selection"])
@pytest.mark.parametrize("failure", [False, True])
def test_queued_results_cannot_update_closed_or_replaced_games_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
    failure: bool,
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    context = build_context(device_coordinator=coordinator)
    devices = context.device_controller
    devices.finish_library_save(active)
    controller = context.games_controller
    # Isolate Games' queued signals from the startup Podcast scan's completion.
    deadline = monotonic() + 5
    while context.podcast_controller.busy and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(5)
    assert not context.podcast_controller.busy
    started = Event()
    release = Event()

    def install(_expected: ActiveIPod, _cancelled: Event) -> GamesResult:
        started.set()
        assert release.wait(5)
        if failure:
            raise SyncRecoveryRequiredError("old device journal")
        return GamesResult(2, 1, 3, True)

    monkeypatch.setattr(coordinator, "install_game_authorizations", install)
    try:
        assert controller.start()
        assert started.wait(5)
        if interruption == "selection":
            devices.finish_library_save(replace(active))
        release.set()
        if interruption == "shutdown":
            # Waiting here deliberately leaves worker signals queued on the GUI thread.
            controller.shutdown()
            assert devices.begin_exclusive_operation()
        deadline = monotonic() + 5
        while controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        APPLICATION.processEvents()
        assert not controller.busy
        assert "saved:" not in controller.message
        assert "was interrupted" not in controller.message
        if interruption == "shutdown":
            # The old queued finished signal must not release a newer reservation.
            assert devices.busy
            devices.finish_exclusive_operation()
        assert devices.device_writes_allowed
    finally:
        release.set()
        context.shutdown()
