from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTreeWidget,
)

# Reuse captured multi-group scan evidence without exposing a test fixture as app API.
from tests.iOpenPod.app.test_sync_duplicate_selection import (
    _comparison,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
    SyncDetails,
)
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_plan import (
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlanAction,
    SyncPlanBasis,
    prepare_sync_plan,
)
from iOpenPod.GUI.dialogs.sync_duplicates import SyncDuplicatesDialog
from iOpenPod.GUI.pages.sync_plan_page import SyncPlanPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMetadata,
)
from storage import DevicePath, HostPath


def _selection(
    tmp_path: Path,
    *,
    hosts: int = 2,
    ipods: int = 2,
    established: bool = False,
    all_established: bool = False,
    target: SyncSelection | None = None,
) -> SyncSelection:
    host_tracks = tuple(
        Track(
            index + 1,
            "Same song",
            "Artist",
            "Original album" if index == 0 else "Greatest hits",
            180_000,
            metadata=TrackMetadata(location=str(tmp_path / f"host-{index}.mp3")),
        )
        for index in range(hosts)
    )
    host = HostMediaLibrary(
        LibrarySnapshot(host_tracks),
        tuple(
            HostMediaSource(
                HostPath(track.metadata.location or ""),
                HostMediaFileKind.AUDIO,
                100,
                1_000,
                acoustic_fingerprint="1,2,3",
            )
            for track in host_tracks
        ),
        (),
        HostMediaCacheStats(),
    )
    ipod_tracks = tuple(
        Track(
            10 + index,
            "Same song",
            "Artist",
            "Original album" if index == 0 else "Greatest hits",
            180_000,
            rating=80 if index == 0 else 0,
            play_count=80 if index == 0 else 0,
            metadata=TrackMetadata(location=f"iPod_Control/Music/F00/{index}.mp3"),
        )
        for index in range(ipods)
    )
    evidence = tuple(
        IPodTrackFingerprint(
            database_track_id=100 + track.track_id,
            track_id=track.track_id,
            path=DevicePath(track.metadata.location or ""),
            size_bytes=100,
            modified_ns=1_000,
            acoustic_fingerprint="1,2,3",
        )
        for track in ipod_tracks
    )
    if established or all_established:
        evidence = tuple(
            replace(
                item,
                sync=SyncDetails(
                    "2026-10-07T12:00:00Z",
                    host_tracks[index].metadata.location or "",
                    100,
                    1_000,
                    "mp3",
                    "mp3",
                    False,
                ),
            )
            if index < len(host_tracks) and (index == 0 or all_established)
            else item
            for index, item in enumerate(evidence)
        )
    ipod = IPodMediaLibrary(evidence, (), (), IPodMediaCacheStats(), None, False)
    library = LibrarySnapshot(
        ipod_tracks,
        playlists=(
            Playlist(
                1,
                "Favorites",
                entries=(PlaylistEntry("first", 10), PlaylistEntry("repeat", 10)),
            ),
        )
        if ipods
        else (),
    )
    selection = target if target is not None else SyncSelection()
    selection.reset(host, prepare_sync_plan(host, ipod, library))
    return selection


@pytest.fixture
def workspace() -> Iterator[SyncWorkspace]:
    context = build_context()
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = SyncWorkspace(context.settings, context.theme_manager, artwork)
    page.resize(1050, 800)
    page.show()
    page.set_execution_available(True)
    try:
        yield page
    finally:
        page.clear()
        page.shutdown()
        artwork.shutdown()
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        context.shutdown()


@pytest.mark.parametrize("podcasts", (0, 4))
def test_selected_album_copies_prompt_for_choices_before_sync(
    tmp_path: Path, workspace: SyncWorkspace, podcasts: int
) -> None:
    selection = _selection(tmp_path, target=workspace.selection)
    selection.set_tracks_checked((1, 2), True)
    workspace.set_podcast_count(podcasts)
    requested = QSignalSpy(workspace.executeRequested)
    workspace.show_review()

    dialog = workspace.findChild(SyncDuplicatesDialog)
    assert dialog is not None and dialog.isVisible()
    assert requested.count() == 0
    assert selection.selected_plan.change_count == 0
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    assert choice is not None and hosts is not None
    choice.setCurrentIndex(choice.findData(10))
    second = hosts.topLevelItem(1)
    assert second is not None
    hosts.setCurrentItem(second)
    choice.setCurrentIndex(choice.findData("add"))
    dialog.accept()

    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0
    assert requested.count() == 0
    execute = workspace.findChild(QPushButton, "executeSync")
    assert execute is not None and execute.isEnabled()
    execute.click()
    assert requested.count() == 1


@pytest.mark.parametrize("podcasts", (0, 4))
def test_cancelled_choices_cannot_silently_skip_selected_songs_during_sync(
    tmp_path: Path, workspace: SyncWorkspace, podcasts: int
) -> None:
    selection = _selection(tmp_path, target=workspace.selection)
    selection.set_tracks_checked((1, 2), True)
    workspace.set_podcast_count(podcasts)
    requested = QSignalSpy(workspace.executeRequested)
    workspace.show_review()
    dialog = workspace.findChild(SyncDuplicatesDialog)
    assert dialog is not None
    dialog.reject()
    APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    execute = workspace.findChild(QPushButton, "executeSync")
    assert execute is not None and execute.isEnabled()
    assert execute.text() == "Resolve selected duplicates…"
    execute.click()
    assert requested.count() == 0
    dialog = workspace.findChild(SyncDuplicatesDialog)
    assert dialog is not None and dialog.isVisible()
    skip = dialog.findChild(QPushButton, "syncDuplicateSkipGroup")
    assert skip is not None
    skip.click()
    dialog.accept()
    assert selection.selected_host_count == 0
    assert execute.text() == "Sync Selected"
    assert execute.isEnabled() is bool(podcasts)
    execute.click()
    assert requested.count() == (1 if podcasts else 0)


@pytest.mark.parametrize("ipods, selected", ((2, False), (0, True)))
def test_unselected_ambiguities_and_host_only_copies_do_not_interrupt_review(
    tmp_path: Path, workspace: SyncWorkspace, ipods: int, selected: bool
) -> None:
    selection = _selection(tmp_path, ipods=ipods, target=workspace.selection)
    selection.set_tracks_checked((1, 2), selected)
    workspace.set_podcast_count(4)
    requested = QSignalSpy(workspace.executeRequested)
    workspace.show_review()
    assert workspace.findChild(SyncDuplicatesDialog) is None
    assert selection.selected_plan.count(SyncPlanAction.ADD) == (2 if selected else 0)
    execute = workspace.findChild(QPushButton, "executeSync")
    assert execute is not None and execute.isEnabled()
    execute.click()
    assert requested.count() == 1


def _open(selection: SyncSelection) -> tuple[SyncPlanPage, SyncDuplicatesDialog]:
    page = SyncPlanPage()
    page.load_review(selection)
    page.show()
    button = page.findChild(QPushButton, "syncReviewDuplicates")
    assert button is not None and button.isVisible()
    button.click()
    dialog = page.findChild(SyncDuplicatesDialog)
    assert dialog is not None and dialog.isVisible()
    return page, dialog


def test_selected_duplicate_group_is_presented_before_unselected_groups(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path, separate_groups=True)
    path = str(host.sources[1].path)
    pending = next(
        group
        for group in comparison.duplicate_groups
        if any(member.host_path == path for member in group.hosts)
    )
    others = tuple(
        group for group in comparison.duplicate_groups if group is not pending
    )
    selection = SyncSelection()
    selection.reset(host, replace(comparison, duplicate_groups=(*others, pending)))
    selection.set_tracks_checked((2,), True)
    page, dialog = _open(selection)
    try:
        assert selection.pending_duplicate_groups == (pending,)
        details = dialog.findChild(QLabel, "syncDuplicateHostDetails")
        assert details is not None and path in details.text()
        dialog.reject()
        assert selection.pending_duplicate_groups == (pending,)
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_selected_host_is_focused_inside_its_duplicate_group(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    selection.set_tracks_checked((2,), True)
    page, dialog = _open(selection)
    try:
        hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
        assert hosts is not None
        current = hosts.currentItem()
        assert current is not None and "Greatest hits" in current.text(1)
        assert selection.unresolved_selected_host_paths
        dialog.reject()
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_duplicate_review_links_adds_and_removes_are_separate_choices(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    page, dialog = _open(selection)
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    ipods = dialog.findChild(QTreeWidget, "syncDuplicateIPods")
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    assert (
        hosts is not None
        and ipods is not None
        and choice is not None
        and remove is not None
    )
    assert hosts.topLevelItemCount() == 2 and ipods.topLevelItemCount() == 2
    first_ipod = ipods.topLevelItem(0)
    assert first_ipod is not None
    assert first_ipod.text(2) == "80"
    assert first_ipod.text(3) == "4 / 5"
    assert "Favorites" in first_ipod.text(4)
    details = dialog.findChild(QLabel, "syncDuplicateHostDetails")
    assert details is not None and str(tmp_path) in details.text()

    choice.setCurrentIndex(choice.findData(10))
    assert not remove.isEnabled()
    second_host = hosts.topLevelItem(1)
    assert second_host is not None
    hosts.setCurrentItem(second_host)
    assert choice.findData(10) == -1
    choice.setCurrentIndex(choice.findData("add"))
    second_ipod = ipods.topLevelItem(1)
    assert second_ipod is not None
    ipods.setCurrentItem(second_ipod)
    assert remove.isEnabled() and not remove.isChecked()
    assert selection.duplicate_resolutions == ()
    assert selection.selected_plan.change_count == 0
    remove.click()
    dialog.accept()

    plan = selection.selected_plan
    assert plan.attention_count == 0
    assert plan.count(SyncPlanAction.UPDATE) == 1
    assert plan.count(SyncPlanAction.ADD) == 1
    assert plan.count(SyncPlanAction.REMOVE) == 1
    link = next(item for item in plan.items if item.action is SyncPlanAction.UPDATE)
    assert link.basis is SyncPlanBasis.USER_MATCH and link.ipod_id == 10
    assert page.plan == plan


def test_cancel_duplicate_choices_leaves_sync_selection_unchanged(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    before = selection.selected_plan
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    assert choice is not None
    choice.setCurrentIndex(choice.findData("add"))
    dialog.reject()
    assert selection.selected_plan == before
    assert selection.duplicate_resolutions == ()


def test_matched_copies_explain_status_and_focus_the_corresponding_album(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path, all_established=True)
    _, dialog = _open(selection)
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    ipods = dialog.findChild(QTreeWidget, "syncDuplicateIPods")
    status = dialog.findChild(QLabel, "syncDuplicateStatus")
    help_text = dialog.findChild(QLabel, "syncDuplicateChoiceHelp")
    buttons = dialog.findChild(QDialogButtonBox)
    cleanup = dialog.findChild(QPushButton, "syncDuplicateCleanup")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    assert hosts is not None and ipods is not None and status is not None
    assert help_text is not None and buttons is not None
    assert cleanup is not None and remove is not None
    assert status.text() == "Already matched"
    assert "previous Sync" in help_text.text()
    assert buttons.button(QDialogButtonBox.StandardButton.Ok).text() == "Done"
    assert not remove.isVisible()
    second = hosts.topLevelItem(1)
    assert second is not None
    hosts.setCurrentItem(second)
    selected = ipods.currentItem()
    assert selected is not None and selected.data(0, Qt.ItemDataRole.UserRole) == 11
    cleanup.click()
    assert remove.isVisible() and not remove.isEnabled()
    assert dialog.resolutions == ()
    dialog.reject()


def test_unresolved_copy_offers_an_explicit_skip_instead_of_a_default_choice(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    selection.set_tracks_checked((1,), True)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    details = dialog.findChild(QLabel, "syncDuplicateHostDetails")
    toggle = dialog.findChild(QPushButton, "syncDuplicateHostDetailsToggle")
    assert choice is not None and details is not None and toggle is not None
    assert choice.currentData() is None
    assert choice.currentText() == "Choose an action…"
    assert not details.isVisible()
    toggle.click()
    assert details.isVisible() and "host-0.mp3" in details.text()
    choice.setCurrentIndex(choice.findData("skip"))
    assert len(dialog.resolutions) == 1
    dialog.accept()
    assert selection.selected_host_count == 0
    assert not selection.pending_duplicate_groups


def test_manual_match_focuses_existing_copy_without_assigning_other_hosts(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    ipods = dialog.findChild(QTreeWidget, "syncDuplicateIPods")
    assert choice is not None and ipods is not None
    choice.setCurrentIndex(choice.findData(11))
    selected = ipods.currentItem()
    assert selected is not None and selected.data(0, Qt.ItemDataRole.UserRole) == 11
    assert len(dialog.resolutions[0].pairs) == 1
    assert not dialog.resolutions[0].removed_ipod_ids
    dialog.reject()


def test_established_pair_is_protected_and_extra_copy_stays_optional(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path, hosts=2, ipods=1, established=True)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    assert choice is not None and hosts is not None and remove is not None
    assert not choice.isEnabled() and not remove.isEnabled()
    second = hosts.topLevelItem(1)
    assert second is not None
    hosts.setCurrentItem(second)
    assert choice.isEnabled() and choice.currentData() == "skip"
    choice.setCurrentIndex(choice.findData("add"))
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0
    assert selection.track_check_state(1) is Qt.CheckState.Checked


def test_host_only_choices_preserve_selected_album_copies(tmp_path: Path) -> None:
    selection = _selection(tmp_path, ipods=0)
    selection.set_tracks_checked((1, 2), True)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    assert choice is not None and choice.currentData() == "add"
    choice.setCurrentIndex(choice.findData("skip"))
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    assert selection.track_check_state(2) is Qt.CheckState.Checked


def test_ipod_only_cleanup_is_explicit_and_shows_history_warning(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path, hosts=0)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    warning = dialog.findChild(QLabel, "syncDuplicateRemovalNote")
    assert choice is not None and not choice.isEnabled()
    assert remove is not None and remove.isEnabled() and not remove.isChecked()
    assert warning is not None and "not merged" in warning.text()
    remove.click()
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1


def test_skip_unresolved_group_and_clear_scan_retire_choices(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    page, dialog = _open(selection)
    skip = dialog.findChild(QPushButton, "syncDuplicateSkipGroup")
    assert skip is not None
    skip.click()
    dialog.accept()
    assert selection.selected_plan.attention_count == 0
    assert selection.selected_plan.change_count == 0
    APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    button = page.findChild(QPushButton, "syncReviewDuplicates")
    assert button is not None and button.isVisible()
    APPLICATION.processEvents()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    reopened = page.findChild(SyncDuplicatesDialog)
    assert reopened is not None and reopened.isVisible()
    selection.clear()
    assert not reopened.isVisible()
    assert selection.duplicate_resolutions == ()


def test_skip_unlinked_hosts_preserves_a_chosen_link(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    skip = dialog.findChild(QPushButton, "syncDuplicateSkipGroup")
    assert choice is not None and skip is not None
    choice.setCurrentIndex(choice.findData(10))
    skip.click()
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0


def test_editing_extra_copy_preserves_deselected_established_pair(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path, hosts=2, ipods=1, established=True)
    selection.set_tracks_checked((1,), False)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    assert choice is not None and hosts is not None and remove is not None
    assert remove.isChecked() and not remove.isEnabled()
    second = hosts.topLevelItem(1)
    assert second is not None
    hosts.setCurrentItem(second)
    choice.setCurrentIndex(choice.findData("add"))
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1
    assert selection.track_check_state(1) is Qt.CheckState.Unchecked


def test_reopening_deselected_manual_pair_keeps_removal_separate(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    group = selection.comparison.duplicate_groups[0]
    selection.set_duplicate_resolution(
        SyncDuplicateResolution(
            group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
        )
    )
    selection.set_tracks_checked((1,), False)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    remove = dialog.findChild(QCheckBox, "syncDuplicateRemove")
    assert choice is not None and hosts is not None and remove is not None
    assert choice.currentData() == 10
    assert remove.isChecked() and not remove.isEnabled()
    first = hosts.topLevelItem(0)
    second = hosts.topLevelItem(1)
    assert first is not None and second is not None
    assert first.text(2) == "Remove (Host selection)"
    hosts.setCurrentItem(second)
    choice.setCurrentIndex(choice.findData("add"))
    assert dialog.resolutions[0].removed_ipod_ids == frozenset()
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1


def test_editing_another_host_preserves_review_exclusion(tmp_path: Path) -> None:
    selection = _selection(tmp_path, ipods=0)
    selection.set_tracks_checked((1, 2), True)
    first = selection.review_plan.items[0]
    selection.set_review_items_checked((first,), False)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    hosts = dialog.findChild(QTreeWidget, "syncDuplicateHosts")
    assert choice is not None and hosts is not None
    assert choice.currentData() == "add"
    second = hosts.topLevelItem(1)
    assert second is not None
    hosts.setCurrentItem(second)
    choice.setCurrentIndex(choice.findData("skip"))
    dialog.accept()
    assert selection.selected_plan.change_count == 0
    assert selection.track_check_state(1) is Qt.CheckState.Checked


def test_untouched_selected_ambiguous_host_stays_skipped(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    selection.set_tracks_checked((1, 2), True)
    _, dialog = _open(selection)
    choice = dialog.findChild(QComboBox, "syncDuplicateHostChoice")
    assert choice is not None
    choice.setCurrentIndex(choice.findData(10))
    dialog.accept()
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    assert selection.track_check_state(2) is Qt.CheckState.Unchecked
