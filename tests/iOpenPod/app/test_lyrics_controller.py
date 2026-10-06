"""Current-track lyrics are lazy, draft-aware, and immune to stale results."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, tracks
from tests.iOpenPod.lyrics_test_support import (
    WORDS,
    MemorySource,
    SourceProvider,
    finish_lyrics_workers,
    media,
)
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.lyrics_controller import LyricsController, LyricsState
from iOpenPod.app.playback_controller import PlaybackController
from iPodDB.library import LibrarySnapshot, TrackFieldEdit, TrackMetadata

type System = tuple[
    LyricsController, PlaybackController, LibraryWorkspace, SourceProvider
]


@pytest.fixture
def system() -> Iterator[System]:
    playback = PlaybackController(FakePlaybackBackend())
    workspace = LibraryWorkspace()
    provider = SourceProvider({0: MemorySource(media())})
    controller = LyricsController(playback, provider, workspace)
    try:
        yield controller, playback, workspace, provider
    finally:
        controller.shutdown()
        playback.shutdown()
        APPLICATION.processEvents()


def settle(controller: LyricsController) -> None:
    finish_lyrics_workers(controller)
    APPLICATION.processEvents()


def assert_state(controller: LyricsController, expected: LyricsState) -> None:
    assert controller.state is expected


def test_reads_only_when_visible_and_does_not_require_the_presence_flag(
    system: System,
) -> None:
    controller, playback, _workspace, provider = system
    track = tracks(1)[0]
    assert not track.metadata.has_lyrics
    playback.enqueue(track)
    assert_state(controller, LyricsState.NOT_LOADED)
    assert provider.opened == []
    controller.set_active(True)
    assert_state(controller, LyricsState.LOADING)
    settle(controller)
    assert_state(controller, LyricsState.READY)
    assert controller.text == WORDS
    assert provider.opened == [track]
    controller.set_active(False)
    controller.set_active(True)
    assert provider.opened == [track]


def test_file_lyrics_win_for_display_but_explicit_draft_clear_wins(
    system: System,
) -> None:
    controller, playback, workspace, provider = system
    track = replace(
        tracks(1)[0], metadata=TrackMetadata(lyrics="Database words", has_lyrics=True)
    )
    workspace.load(LibrarySnapshot(tracks=(track,)))
    playback.enqueue(track)
    controller.set_active(True)
    assert controller.text == "Database words"
    settle(controller)
    assert controller.text == WORDS
    assert_state(controller, LyricsState.READY)
    assert provider.opened == [track]
    assert not workspace.dirty

    workspace.apply_track_edits(
        (TrackUpdate(track.track_id, (TrackFieldEdit("metadata.lyrics", ""),)),),
        workspace.edit_revision,
    )
    playback.reconcile_library(workspace.tracks)
    assert controller.text == ""
    assert_state(controller, LyricsState.READY)
    assert provider.opened == [track]


def test_database_lyrics_are_used_when_file_has_none(system: System) -> None:
    controller, playback, workspace, provider = system
    track = replace(
        tracks(1)[0], metadata=TrackMetadata(lyrics="Database words", has_lyrics=True)
    )
    provider.sources[0] = MemorySource(media(lyrics=""))
    workspace.load(LibrarySnapshot(tracks=(track,)))
    playback.enqueue(track)
    controller.set_active(True)
    settle(controller)
    assert controller.text == "Database words"
    assert_state(controller, LyricsState.READY)
    assert not workspace.dirty


@pytest.mark.parametrize("clear_session", [False, True])
def test_completed_but_undelivered_read_cannot_replace_new_current_track(
    system: System, clear_session: bool
) -> None:
    controller, playback, _workspace, _provider = system
    first, second = tracks(2)
    second = replace(second, metadata=TrackMetadata(lyrics="Second track"))
    controller.set_active(True)
    playback.enqueue(first)
    # Finish the worker, but deliberately leave its queued result undelivered.
    finish_lyrics_workers(controller)
    if clear_session:
        playback.clear_session()
    else:
        playback.play_now((second,))
    APPLICATION.processEvents()
    assert controller.text == ("" if clear_session else "Second track")
    if not clear_session:
        assert controller.state is LyricsState.LOADING
        settle(controller)
    assert controller.state is (
        LyricsState.NO_TRACK if clear_session else LyricsState.READY
    )


def test_missing_lyrics_and_read_failure_are_distinct_and_leave_playback_running(
    system: System,
) -> None:
    controller, playback, _workspace, provider = system
    provider.sources[0] = MemorySource(media(lyrics=""))
    first, second = tracks(2)
    controller.set_active(True)
    playback.enqueue(first)
    settle(controller)
    assert_state(controller, LyricsState.READY)
    assert controller.text == ""

    playback.play_now((second,))
    settle(controller)
    assert_state(controller, LyricsState.UNAVAILABLE)
    assert controller.text == ""
    assert playback.current_track == second
    assert playback.playing
