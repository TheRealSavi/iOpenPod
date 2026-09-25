"""Background normalization is a preview, never permission to overwrite edits."""

import threading
from collections.abc import Callable
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QThreadPool
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app import tag_normalization_controller as workers
from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import TagProfile, TagSuggestion, normalize_tags
from iPodDB.library import LibrarySnapshot, Track, TrackFieldEdit


def _wait(predicate: Callable[[], bool]) -> None:
    until = monotonic() + 5
    while not predicate() and monotonic() < until:
        APPLICATION.processEvents()
        sleep(0.005)
    assert predicate()


def test_background_scan_requires_apply_and_preserves_the_source() -> None:
    workspace = LibraryWorkspace()
    source = LibrarySnapshot((Track(1, " Song  ", "The Artist", "The Album", 100),))
    workspace.load(source)
    controller = TagNormalizationController(workspace)
    try:
        controller.start(TagProfile())
        _wait(lambda: not controller.scanning)
        assert controller.suggestion is not None
        assert controller.suggestion.field_count == 3
        assert not workspace.dirty
        controller.apply()
        assert workspace.tracks[0].title == "Song"
        assert workspace.tracks[0].metadata.sort_artist == "Artist, The"
        assert workspace.snapshot is source and workspace.dirty
        assert controller.suggestion is None
    finally:
        controller.shutdown()


@pytest.mark.parametrize("action", ["edit", "reload", "cancel", "lock"])
def test_late_scan_result_cannot_apply_to_a_changed_workspace(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((Track(1, " Song  ", "The Artist", "Album", 100),)))
    entered, release = threading.Event(), threading.Event()
    caller_thread = threading.get_ident()
    worker_threads: list[int] = []

    def delayed(
        tracks: tuple[Track, ...],
        profile: TagProfile,
        *,
        checkpoint: Callable[[], None],
    ) -> TagSuggestion:
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        # Deliberately ignore cancellation to exercise stale-result rejection.
        return normalize_tags(tracks, profile)

    monkeypatch.setattr(workers, "normalize_tags", delayed)
    controller = TagNormalizationController(workspace)
    try:
        controller.start(TagProfile())
        _wait(entered.is_set)
        if action == "edit":
            workspace.rename_device("Edited", workspace.edit_revision)
        elif action == "reload":
            workspace.load(
                LibrarySnapshot((Track(1, "Replacement", "New", "New", 100),))
            )
        elif action == "lock":
            workspace.set_locked(True)
        else:
            controller.cancel()
        expected = workspace.desired_snapshot()
        release.set()
        pool = controller.findChild(QThreadPool)
        assert pool is not None and pool.waitForDone(5_000)
        APPLICATION.processEvents()
        assert controller.suggestion is None
        with pytest.raises(ValueError, match="Scan"):
            controller.apply()
        assert workspace.desired_snapshot() == expected
        assert worker_threads and worker_threads[0] != caller_thread
    finally:
        release.set()
        controller.shutdown()


def test_realistic_normalization_is_deterministic_and_cancellable() -> None:
    tracks = tuple(
        Track(i, f" Track {i} ", f"The Artist {i // 20}", f"Album {i // 10}", 120_000)
        for i in range(10_000)
    )
    suggestion = normalize_tags(tracks)
    assert len(suggestion.updates) == 10_000
    assert suggestion.field_count == 30_000
    assert normalize_tags(tracks) == suggestion
    count = 0

    def stop() -> None:
        nonlocal count
        count += 1
        if count == 4:
            raise InterruptedError

    with pytest.raises(InterruptedError):
        normalize_tags(tracks, checkpoint=stop)
    assert count == 4


def test_monitor_counts_fields_and_refreshes_after_edits_apply_and_unlock() -> None:
    workspace = LibraryWorkspace()
    controller = TagNormalizationController(workspace)
    profile = TagProfile()
    try:
        controller.monitor(profile)
        assert controller.pending_count == 0 and not controller.scanning
        workspace.load(
            LibrarySnapshot((Track(1, " Song ", "The Artist", "Album", 100),))
        )
        _wait(lambda: controller.suggestion is not None)
        assert controller.pending_count == 3 and not workspace.dirty
        previous = controller.suggestion
        controller.ensure_scan(profile)
        assert controller.suggestion is previous and not controller.scanning
        workspace.apply_track_edits(
            (TrackUpdate(1, (TrackFieldEdit("title", "Song"),)),),
            workspace.edit_revision,
        )
        assert controller.pending_count == 0
        _wait(lambda: controller.suggestion is not None)
        assert controller.pending_count == 2
        workspace.set_locked(True)
        assert controller.suggestion is None and controller.pending_count == 0
        workspace.set_locked(False)
        _wait(lambda: controller.suggestion is not None)
        assert controller.pending_count == 2
        controller.apply()
        assert controller.pending_count == 0 and workspace.dirty
        _wait(lambda: controller.suggestion is not None)
        assert controller.pending_count == 0
        workspace.load(None)
        controller.monitor(None)
        assert controller.suggestion is None and not controller.monitoring
    finally:
        controller.shutdown()


@pytest.mark.parametrize("action", ["reload", "profile", "disconnect"])
def test_monitor_rejects_old_counts_and_rechecks_the_latest_source(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((Track(1, " Old ", "The Artist", "Album", 100),)))
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def delayed(
        tracks: tuple[Track, ...],
        profile: TagProfile,
        *,
        checkpoint: Callable[[], None],
    ) -> TagSuggestion:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(5)
        return normalize_tags(tracks, profile)

    monkeypatch.setattr(workers, "normalize_tags", delayed)
    controller = TagNormalizationController(workspace)
    profile = TagProfile()
    try:
        controller.monitor(profile)
        _wait(entered.is_set)
        if action == "reload":
            workspace.load(LibrarySnapshot((Track(2, "New", "Artist", "Album", 100),)))
        elif action == "profile":
            profile = TagProfile("Another iPod", True, True)
            controller.monitor(profile)
        else:
            workspace.load(None)
            controller.monitor(None)
        assert controller.pending_count == 0
        release.set()
        if action == "disconnect":
            pool = controller.findChild(QThreadPool)
            assert pool is not None and pool.waitForDone(5_000)
            APPLICATION.processEvents()
            assert controller.suggestion is None and controller.pending_count == 0
        else:
            _wait(lambda: controller.suggestion is not None)
            assert controller.suggestion == normalize_tags(workspace.tracks, profile)
    finally:
        release.set()
        controller.shutdown()
