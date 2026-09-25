"""Behavior tests for runtime-only playback state."""

import pytest
from PySide6.QtCore import QModelIndex, Qt
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.playback.backend import PlaybackFailure
from iOpenPod.app.playback_controller import PlaybackController
from iPodDB.library import Track


def test_idle_enqueue_starts_track_and_records_history() -> None:
    controller = _controller()
    track = _track(1, "First")

    controller.enqueue(track)

    assert controller.current_track == track
    assert controller.playing
    assert controller.position_ms == 0
    assert controller.queue_model.entries == ()
    assert tuple(entry.track for entry in controller.history_model.entries) == (track,)


@pytest.mark.parametrize("stopped_before_finish", (False, True))
def test_successor_track_notification_exposes_reset_transport(
    stopped_before_finish: bool,
) -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    first, second = _track(1, "First"), _track(2, "Second")
    controller.play_now((first, second))
    backend.emit_position(first.length_ms)
    if stopped_before_finish:
        backend.emit_playing(False)
    observed: list[tuple[Track | None, int, bool]] = []

    def record_transport(_track: object) -> None:
        observed.append(
            (controller.current_track, controller.position_ms, controller.playing)
        )

    controller.currentTrackChanged.connect(record_transport)

    backend.finish()

    assert observed == [(second, 0, False)]
    assert controller.playing


def test_next_entry_observes_queue_occurrences_without_advancing_playback() -> None:
    controller = _controller()
    initial_next = controller.next_entry
    assert initial_next is None
    current, repeated = _track(1, "Current"), _track(2, "Repeated")
    controller.play_now((current, repeated, repeated))
    first, second = controller.queue_model.entries

    first_next = controller.next_entry
    assert first_next == first
    assert controller.move_queue_entry(1, 0)
    reordered_next = controller.next_entry
    assert reordered_next == second
    controller.remove_queue_entry(second.entry_id)
    remaining_next = controller.next_entry
    assert remaining_next == first
    assert controller.current_track == current
    assert controller.position_ms == 0
    assert len(controller.history_model.entries) == 1
    controller.clear_queue()
    assert controller.next_entry is None


def test_next_entry_matches_forward_history_before_the_queue() -> None:
    controller = _controller()
    first, second, third = tuple(_track(value, str(value)) for value in range(3))
    controller.play_now((first, second, third))
    next_entry = controller.next_entry
    assert next_entry is not None
    controller.next()
    assert controller.current_entry_id == next_entry.entry_id
    controller.previous()

    assert controller.current_track == first
    assert controller.queue_model.entries[0].track == third
    assert controller.next_entry == next_entry
    controller.next()
    assert controller.current_track == second
    assert controller.next_entry == controller.queue_model.entries[0]


def test_queue_occurrences_can_be_removed_reordered_and_cleared() -> None:
    controller = _controller()
    current = _track(1, "Current")
    duplicate = _track(2, "Duplicate")
    final = _track(3, "Final")
    controller.enqueue(current)
    controller.enqueue(duplicate)
    controller.enqueue(duplicate)
    controller.enqueue(final)

    entries = controller.queue_model.entries
    assert tuple(entry.track for entry in entries) == (duplicate, duplicate, final)
    assert len({entry.entry_id for entry in entries}) == 3

    controller.remove_queue_entry(entries[0].entry_id)
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        duplicate,
        final,
    )

    assert controller.move_queue_entry(1, 0)
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        final,
        duplicate,
    )

    controller.clear_queue()
    assert controller.queue_model.entries == ()
    assert controller.current_track == current
    assert tuple(entry.track for entry in controller.history_model.entries) == (
        current,
    )


@pytest.mark.parametrize("paused", (False, True))
def test_play_next_prepends_ordered_occurrences_without_interrupting_current(
    paused: bool,
) -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    current, queued, first, second = tuple(
        _track(track_id, str(track_id)) for track_id in range(4)
    )
    controller.enqueue(current)
    controller.enqueue(queued)
    controller.seek(12_000)
    if paused:
        controller.pause()
    entry_id = controller.current_entry_id
    history = controller.history_model.entries
    pending = controller.queue_model.entries

    assert controller.play_next((first, second, first))

    entries = controller.queue_model.entries
    assert tuple(entry.track for entry in entries) == (first, second, first, queued)
    assert len({entry.entry_id for entry in entries}) == 4
    assert entries[-1:] == pending
    assert controller.current_track == current
    assert controller.current_entry_id == entry_id
    assert controller.position_ms == 12_000
    assert controller.playing is not paused
    assert controller.history_model.entries == history
    assert backend.started == [current]

    controller.next()
    assert controller.current_track == first
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        second,
        first,
        queued,
    )


def test_play_next_starts_an_idle_queue_and_empty_input_does_nothing() -> None:
    controller = _controller()
    first, second = _track(1, "First"), _track(2, "Second")
    assert not controller.play_next(())
    assert controller.current_entry_id is None

    assert controller.play_next((first, second, first))

    assert controller.current_track == first
    assert controller.playing
    entries = controller.queue_model.entries
    assert tuple(entry.track for entry in entries) == (second, first)
    assert not controller.play_next(())
    assert controller.queue_model.entries == entries
    assert tuple(entry.track for entry in controller.history_model.entries) == (first,)


def test_play_now_replaces_current_and_places_remaining_tracks_at_queue_top() -> None:
    controller = _controller()
    previous = _track(1, "Previous")
    queued = _track(2, "Already queued")
    dropped = tuple(_track(track_id, str(track_id)) for track_id in range(3, 6))
    controller.enqueue(previous)
    controller.enqueue(queued)

    assert controller.play_now(dropped)

    assert controller.current_track == dropped[0]
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        dropped[1],
        dropped[2],
        queued,
    )
    assert tuple(entry.track for entry in controller.history_model.entries) == (
        dropped[0],
        previous,
    )


def test_queue_model_accepts_an_internal_drag_move() -> None:
    controller = _controller()
    tracks = tuple(_track(track_id, str(track_id)) for track_id in range(4))
    for track in tracks:
        controller.enqueue(track)
    model = controller.queue_model

    dragged = model.mimeData([model.index(0, 0)])

    assert model.dropMimeData(
        dragged,
        Qt.DropAction.MoveAction,
        model.rowCount(),
        0,
        QModelIndex(),
    )
    assert tuple(entry.track for entry in model.entries) == (
        tracks[2],
        tracks[3],
        tracks[1],
    )


def test_previous_restarts_only_when_strictly_past_ten_seconds() -> None:
    controller = _controller()
    first = _track(1, "First")
    second = _track(2, "Second")
    controller.enqueue(first)
    controller.enqueue(second)
    controller.next()
    original_history = controller.history_model.entries

    controller.seek(10_001)
    controller.previous()

    assert controller.current_track == second
    assert controller.position_ms == 0
    assert controller.history_model.entries == original_history

    controller.seek(10_000)
    controller.previous()

    assert controller.current_track == first
    assert controller.position_ms == 0
    assert controller.history_model.entries == original_history


def test_history_traversal_precedes_resuming_queue_advancement() -> None:
    controller = _controller()
    first = _track(1, "First")
    second = _track(2, "Second")
    third = _track(3, "Third")
    fourth = _track(4, "Fourth")
    for track in (first, second, third):
        controller.enqueue(track)
    controller.next()
    controller.next()
    original_history = controller.history_model.entries
    controller.enqueue(fourth)

    controller.previous()
    controller.previous()
    assert controller.current_track == first
    assert controller.history_model.entries == original_history

    controller.previous()
    assert controller.current_track == first
    assert controller.history_model.entries == original_history

    controller.next()
    assert controller.current_track == second
    controller.finish_current()
    assert controller.current_track == third
    assert controller.history_model.entries == original_history
    assert tuple(entry.track for entry in controller.queue_model.entries) == (fourth,)

    controller.next()
    assert controller.current_track == fourth
    assert tuple(entry.track for entry in controller.history_model.entries) == (
        fourth,
        third,
        second,
        first,
    )
    assert controller.queue_model.entries == ()


def test_play_pause_finish_and_clear_session_update_runtime_state_only() -> None:
    controller = _controller()
    track = _track(1, "Only")
    controller.enqueue(track)

    controller.toggle_play_pause()
    assert not controller.playing
    assert controller.current_track == track
    controller.toggle_play_pause()
    assert controller.playing

    controller.seek(30_000)
    controller.finish_current()

    assert controller.current_track is None
    assert not controller.playing
    assert controller.position_ms == 0
    assert tuple(entry.track for entry in controller.history_model.entries) == (track,)

    controller.clear_session()

    assert controller.current_track is None
    assert controller.queue_model.entries == ()
    assert controller.history_model.entries == ()


@pytest.mark.parametrize("paused", (False, True))
def test_clear_history_preserves_playback_and_queue_then_records_new_starts(
    paused: bool,
) -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    first, second, pending = tuple(_track(i, str(i)) for i in range(3))
    controller.insert_tracks((first, second, pending), 0)
    controller.next()
    controller.previous()
    controller.seek(5_000)
    if paused:
        controller.pause()
    entry_id = controller.current_entry_id
    queue = controller.queue_model.entries
    starts = backend.started.copy()

    controller.clear_history()
    controller.clear_history()

    assert controller.history_model.rowCount() == 0
    assert controller.current_track == first
    assert controller.current_entry_id == entry_id
    assert controller.position_ms == 5_000
    assert controller.playing is not paused
    assert controller.queue_model.entries == queue
    assert backend.started == starts

    controller.previous()
    assert controller.current_track == first
    assert controller.position_ms == 0
    assert controller.history_model.rowCount() == 0
    controller.next()
    assert controller.current_track == pending
    assert tuple(entry.track for entry in controller.history_model.entries) == (
        pending,
    )
    assert controller.current_entry_id != entry_id


def test_play_and_pause_are_idempotent_transport_intents() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    track = _track(1, "Only")
    controller.enqueue(track)

    controller.play()
    assert controller.playing
    controller.pause()
    controller.pause()
    assert not controller.playing
    controller.play()
    controller.play()
    assert controller.playing
    assert backend.started == [track]


def test_reconcile_library_refreshes_tracks_and_drops_missing_queue_entries() -> None:
    controller = _controller()
    current = _track(1, "Current")
    removed = _track(2, "Removed")
    pending = _track(3, "Pending")
    controller.enqueue(current)
    controller.enqueue(removed)
    controller.enqueue(pending)
    updated_current = _track(1, "Current updated")
    updated_pending = _track(3, "Pending updated")

    controller.reconcile_library((updated_current, updated_pending))

    assert controller.current_track == updated_current
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        updated_pending,
    )
    assert tuple(entry.track for entry in controller.history_model.entries) == (
        updated_current,
    )


def test_backend_events_drive_position_finish_volume_and_shutdown() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    first = _track(1, "First")
    second = _track(2, "Second")
    controller.enqueue(first)
    controller.enqueue(second)

    backend.emit_position(12_345)
    controller.set_volume(150)
    backend.finish()

    assert controller.position_ms == 0
    assert controller.current_track == second
    assert backend.started == [first, second]
    assert backend.volume_percent == 100
    assert controller.volume_percent == 100

    controller.shutdown()

    assert backend.closed
    assert not controller.playing


def test_current_backend_failure_is_reported_and_play_retries_the_track() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    track = _track(1, "First")
    failures: list[object] = []
    controller.playbackFailed.connect(failures.append)
    controller.enqueue(track)

    attempt_id = backend.current_attempt_id
    assert attempt_id is not None
    failure = PlaybackFailure(
        attempt_id,
        track.track_id,
        "Decoder failed",
        "DecodeError",
    )
    backend.emit_playing(False)
    backend.fail(failure)

    assert not controller.playing
    assert failures == [failure]

    controller.toggle_play_pause()

    assert controller.playing
    assert backend.started == [track, track]


def test_stale_backend_events_cannot_mutate_the_successor_attempt() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    first = _track(1, "First")
    second = _track(2, "Second")
    controller.enqueue(first)
    controller.enqueue(second)
    first_attempt = backend.started_attempt_ids[0]

    backend.finish()

    assert controller.current_track == second
    assert controller.position_ms == 0
    assert controller.playing

    backend.emit_position(90_000, attempt_id=first_attempt)
    backend.emit_playing(False, attempt_id=first_attempt)
    backend.finish(attempt_id=first_attempt)

    assert controller.current_track == second
    assert controller.position_ms == 0
    assert controller.playing


def _controller() -> PlaybackController:
    return PlaybackController(FakePlaybackBackend())


def _track(track_id: int, title: str) -> Track:
    return Track(track_id, title, "Artist", "Album", 180_000)
