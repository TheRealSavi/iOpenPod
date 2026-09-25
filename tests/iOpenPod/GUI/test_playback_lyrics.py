"""Lyrics tab integration with playback, Library edits, and plain-text display."""

from dataclasses import replace

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPlainTextEdit, QTabWidget
from pytest import MonkeyPatch
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.application_shell_test_support import tracks as build_tracks
from tests.iOpenPod.lyrics_test_support import (
    WORDS,
    MemorySource,
    SourceProvider,
    finish_lyrics_workers,
    media,
)

from iOpenPod.app.library_workspace import TrackUpdate
from iOpenPod.app.lyrics_controller import LyricsState
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.playback_pane import PlaybackPane
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iPodDB.library import LibrarySnapshot, TrackFieldEdit, TrackMetadata


def test_lyrics_follow_playback_and_live_edits_while_preserving_plain_text() -> None:
    context = build_context()
    first, second = build_tracks(2)
    first = replace(first, metadata=TrackMetadata(lyrics=WORDS, has_lyrics=True))
    second = replace(second, metadata=TrackMetadata(lyrics="Second track"))
    context.library_workspace.load(LibrarySnapshot(tracks=(first, second)))
    # Constructing the pane after playback starts must display the current lyrics.
    context.playback_controller.enqueue(first)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        toggle = window.findChild(IconButton, "playerQueueToggle")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        lyrics = window.findChild(QPlainTextEdit, "playbackLyricsText")
        pane = window.findChild(PlaybackPane, "playbackPane")
        assert toggle is not None and tabs is not None and lyrics is not None
        assert pane is not None
        toggle.click()
        tabs.setCurrentIndex(2)
        assert lyrics.toPlainText() == WORDS
        assert lyrics.isReadOnly()
        lyrics.selectAll()
        QTest.keyClicks(lyrics, "Cannot edit")
        QTest.keyClick(lyrics, Qt.Key.Key_Backspace)
        assert lyrics.toPlainText() == WORDS

        context.playback_controller.pause()
        context.playback_controller.seek(15_000)
        APPLICATION.sendEvent(pane, QEvent(QEvent.Type.LanguageChange))
        assert lyrics.toPlainText() == WORDS

        context.library_workspace.apply_track_edits(
            (
                TrackUpdate(
                    first.track_id,
                    (TrackFieldEdit("metadata.lyrics", "Edited\r\nverse"),),
                ),
            ),
            context.library_workspace.edit_revision,
        )
        assert lyrics.toPlainText() == "Edited\nverse"
        context.playback_controller.enqueue(second)
        context.playback_controller.next()
        assert lyrics.toPlainText() == "Second track"
        context.playback_controller.previous()
        assert lyrics.toPlainText() == "Edited\nverse"

        context.library_workspace.apply_track_edits(
            (TrackUpdate(first.track_id, (TrackFieldEdit("metadata.lyrics", ""),)),),
            context.library_workspace.edit_revision,
        )
        assert lyrics.toPlainText() == ""
        assert lyrics.placeholderText() == "No lyrics available for this track."
        context.playback_controller.clear_session()
        assert lyrics.toPlainText() == ""
        assert lyrics.placeholderText() == "Play a track to see its lyrics."
    finally:
        window.close()
        context.shutdown()


def test_embedded_lyrics_load_only_in_visible_tab_and_clear_on_track_change(
    monkeypatch: MonkeyPatch,
) -> None:
    context = build_context()
    first, second = build_tracks(2)
    provider = SourceProvider(
        {first.track_id: MemorySource(media("tone.m4a"), "track.m4a")}
    )
    monkeypatch.setattr(
        context.device_coordinator,
        "open_playback_source",
        provider.open_playback_source,
    )
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        context.playback_controller.enqueue(first)
        toggle = window.findChild(IconButton, "playerQueueToggle")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        lyrics = window.findChild(QPlainTextEdit, "playbackLyricsText")
        assert toggle is not None and tabs is not None and lyrics is not None
        tabs.setCurrentIndex(2)
        assert provider.opened == []
        toggle.click()
        assert lyrics.placeholderText() == "Loading lyrics…"
        finish_lyrics_workers(context.lyrics_controller)
        APPLICATION.processEvents()
        assert lyrics.toPlainText() == WORDS
        assert provider.opened == [first]

        context.playback_controller.play_now((second,))
        assert lyrics.toPlainText() == ""
        finish_lyrics_workers(context.lyrics_controller)
        APPLICATION.processEvents()
        assert context.lyrics_controller.state is LyricsState.UNAVAILABLE
        assert lyrics.placeholderText() == "Lyrics could not be loaded for this track."
    finally:
        window.close()
        context.shutdown()
