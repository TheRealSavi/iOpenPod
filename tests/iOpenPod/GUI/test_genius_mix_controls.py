"""Genius header controls, selection, and stale-dialog protection."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QMessageBox, QSpinBox
from tests.iOpenPod.app.test_genius_mixes import music
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.test_genius_page import Browser, active, button, tree

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.genius_mixes import GENIUS_MIX_POLICY, MixPolicy, propose_mixes
from iOpenPod.GUI.dialogs.genius_mixes import (
    AddGeniusMixesDialog,
    GeniusMixSettingsDialog,
)
from iOpenPod.GUI.pages.genius_page import GeniusPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, IconButton
from iPodDB.library.genius import GeniusBrowse, GeniusCollection, GeniusCollectionKind


@pytest.fixture
def mix_browser() -> Iterator[Browser]:
    context = build_context()
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    context.settings.load_device("mix-test", {}, writable=True)
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MD479"
    )
    current = replace(
        active(), profile=profile, library=music("Rock", "Jazz"), genius=GeniusBrowse()
    )
    context.library_workspace.load(current.library)
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = GeniusPage(
        context.library_workspace, context.settings, context.theme_manager, artwork
    )
    page.set_active_ipod(current)
    page.resize(1000, 700)
    page.show()
    APPLICATION.processEvents()
    try:
        yield Browser(page, context)
    finally:
        page.close()
        context.shutdown()
        artwork.deleteLater()
        page.deleteLater()
        APPLICATION.processEvents()


def icon(page: GeniusPage, name: str) -> IconButton:
    button = page.findChild(IconButton, name)
    assert button is not None
    return button


def test_empty_mix_header_shows_settings_then_add_and_locks_during_work(
    mix_browser: Browser,
) -> None:
    page = mix_browser.page
    assert tree(page).topLevelItemCount() == 1
    section = tree(page).topLevelItem(0)
    assert section is not None and section.text(0) == "Genius Mixes"
    settings, add = icon(page, "geniusMixSettings"), icon(page, "addGeniusMixes")
    assert settings.isEnabled() and add.isEnabled()
    assert settings.x() < add.x()
    mix_browser.context.library_workspace.set_locked(True)
    assert not settings.isEnabled() and not add.isEnabled()


def test_add_grid_supports_multiple_selection_and_stages_one_edit(
    mix_browser: Browser,
) -> None:
    def choose() -> None:
        dialog = mix_browser.page.findChild(AddGeniusMixesDialog)
        assert dialog is not None
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        add = dialog.findChild(ActionButton, "confirmAddGeniusMixes")
        assert grid is not None and add is not None
        assert not add.isEnabled()
        for row in range(grid.count()):
            item = grid.item(row)
            if item.text().startswith(("Rock Mix", "Jazz Mix")):
                item.setSelected(True)
        assert set(dialog.selected_keys) == {"rock", "jazz"}
        assert add.isEnabled()
        add.click()

    QTimer.singleShot(0, choose)
    icon(mix_browser.page, "addGeniusMixes").click()
    assert set(mix_browser.context.library_workspace.genius_mix_additions) == {
        "rock",
        "jazz",
    }
    assert mix_browser.context.library_workspace.dirty
    mix_browser.context.library_workspace.reset_changes()
    assert not mix_browser.context.library_workspace.genius_mix_additions
    assert not mix_browser.context.library_workspace.dirty


def test_settings_save_count_and_expiry_together_for_selected_ipod(
    mix_browser: Browser,
) -> None:
    def configure() -> None:
        dialog = mix_browser.page.findChild(GeniusMixSettingsDialog)
        assert dialog is not None
        count = dialog.findChild(QSpinBox, "automaticGeniusMixCount")
        expiry = dialog.findChild(QSpinBox, "automaticGeniusMixExpiry")
        assert count is not None and expiry is not None
        count.setValue(3)
        expiry.setValue(14)
        dialog.accept()

    QTimer.singleShot(0, configure)
    icon(mix_browser.page, "geniusMixSettings").click()
    assert MixPolicy.decode(
        mix_browser.context.settings.get(GENIUS_MIX_POLICY)
    ) == MixPolicy(3, 14)
    assert not mix_browser.context.library_workspace.dirty


def test_disconnect_while_dialog_open_discards_selection(mix_browser: Browser) -> None:
    def disconnect() -> None:
        dialog = mix_browser.page.findChild(AddGeniusMixesDialog)
        assert dialog is not None
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        assert grid is not None
        grid.item(0).setSelected(True)
        mix_browser.page.set_active_ipod(None)
        mix_browser.context.library_workspace.load(None)
        dialog.accept()

    QTimer.singleShot(0, disconnect)
    icon(mix_browser.page, "addGeniusMixes").click()
    assert not mix_browser.context.library_workspace.genius_mix_additions


def test_add_dialog_only_shows_eligible_proposals() -> None:
    dialog = AddGeniusMixesDialog(propose_mixes(music("Rock")))
    try:
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        assert grid is not None
        assert grid.count() == 1
        assert grid.item(0).data(Qt.ItemDataRole.UserRole) == "rock"
        assert dialog.selected_keys == ()
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        dialog.deleteLater()


def test_add_dialog_shows_empty_state_when_no_mix_can_be_added() -> None:
    dialog = AddGeniusMixesDialog(propose_mixes(music("Unknown")))
    try:
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        empty = dialog.findChild(QLabel, "geniusMixEmpty")
        add = dialog.findChild(ActionButton, "confirmAddGeniusMixes")
        assert grid is not None and empty is not None and add is not None
        assert grid.count() == 0
        assert not add.isEnabled()
        dialog.show()
        APPLICATION.processEvents()
        assert empty.isVisible() and not grid.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_add_dialog_uses_one_horizontally_scrolling_row_with_colored_icons() -> None:
    dialog = AddGeniusMixesDialog(
        propose_mixes(music("Rock", "Jazz", "Pop", "Metal", "Blues"))
    )
    try:
        dialog.show()
        APPLICATION.processEvents()
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        assert grid is not None
        assert grid.count() >= 5
        assert not grid.isWrapping()
        assert grid.viewport().height() >= grid.gridSize().height()
        assert grid.horizontalScrollBar().maximum() > 0
        assert grid.verticalScrollBar().maximum() == 0
        hues: set[int] = set()
        for index in range(grid.count()):
            assert "\n" not in grid.item(index).text()
            pixmap = grid.item(index).icon().pixmap(42, 42)
            assert not pixmap.isNull()
            image = pixmap.toImage()
            visible = (
                QColor.fromRgba(image.pixel(x, y))
                for y in range(image.height())
                for x in range(image.width())
            )
            color = next(pixel for pixel in visible if pixel.alpha() > 200)
            assert color.saturation() > 0
            hues.add(color.hue())
        assert len(hues) >= 4
    finally:
        dialog.close()
        dialog.deleteLater()


def test_mood_cards_show_only_the_mix_name() -> None:
    dialog = AddGeniusMixesDialog(propose_mixes(music("Rock", "Jazz"), preview=True))
    try:
        grid = dialog.findChild(QListWidget, "geniusMixProposals")
        assert grid is not None
        cards = {
            grid.item(i).data(Qt.ItemDataRole.UserRole): grid.item(i)
            for i in range(grid.count())
        }
        assert cards["focus"].text() == "Focus Mix"
        assert "love" not in cards
        assert dialog.findChild(QLabel, "geniusMixDialogDescription") is None
        assert dialog.findChild(QLabel, "geniusMixDialogNote") is None
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize(
    "kind", (GeniusCollectionKind.PLAYLIST, GeniusCollectionKind.MIX)
)
def test_remove_button_stages_selected_genius_collection(
    mix_browser: Browser, monkeypatch: pytest.MonkeyPatch, kind: GeniusCollectionKind
) -> None:
    snapshot = mix_browser.context.library_workspace.snapshot
    assert snapshot is not None
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MD479"
    )
    collection = GeniusCollection(
        f"genius-{kind.value}:000000000000007b",
        "Selected Genius",
        kind,
        (snapshot.tracks[0].track_id,),
        snapshot.tracks[0].track_id,
        123,
    )
    mix_browser.page.set_active_ipod(
        replace(
            active(),
            profile=profile,
            library=snapshot,
            genius=GeniusBrowse((collection,)),
        )
    )
    section = tree(mix_browser.page).topLevelItem(0)
    assert section is not None
    item = section.child(0)
    assert item is not None
    tree(mix_browser.page).setCurrentItem(item)
    remove = button(mix_browser.page, "removePlaylist")
    assert remove.isVisible() and remove.isEnabled()

    def cancel(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    remove.click()
    assert not mix_browser.context.library_workspace.genius_collection_removals

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    remove.click()
    assert mix_browser.context.library_workspace.genius_collection_removals == (
        collection.collection_id,
    )
    assert mix_browser.context.library_workspace.dirty
    section = tree(mix_browser.page).topLevelItem(0)
    assert section is not None and section.childCount() == 0
