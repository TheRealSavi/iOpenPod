"""Tests for the sync-stages-panel state machine.

The widget itself is a thin renderer; all of the interesting behaviour
lives in ``apply_stage_event`` / ``finalize_states`` which transition a
plain dict of ``StageStatus`` values.  These tests exercise that pure
logic so we can catch regressions without spinning up Qt.
"""

from __future__ import annotations

from iopenpod.gui.widgets.syncStagesPanel import (
    DEFAULT_PIPELINE,
    StageStatus,
    SyncStage,
    apply_stage_event,
    finalize_states_for_end_of_sync,
    init_states,
)

# ── A small fixed test pipeline ─────────────────────────────────────────
# Using a dedicated 5-step pipeline keeps these tests independent of
# tweaks to ``DEFAULT_PIPELINE`` (which represents the real executor).

_TEST_PIPELINE: tuple[SyncStage, ...] = (
    SyncStage("backup", "Backup", frozenset({"backup"})),
    SyncStage("remove", "Remove", frozenset({"remove", "remove_chapter"})),
    SyncStage("add", "Add", frozenset({"add"})),
    SyncStage(
        "scrobble",
        "Scrobble",
        frozenset({"scrobble_listenbrainz", "scrobble_lastfm"}),
    ),
    SyncStage("write", "Write database", frozenset({"write_database"})),
)


# ── init_states ─────────────────────────────────────────────────────────


def test_init_states_marks_every_step_pending() -> None:
    states = init_states(_TEST_PIPELINE)
    assert states == {
        "backup": StageStatus.PENDING,
        "remove": StageStatus.PENDING,
        "add": StageStatus.PENDING,
        "scrobble": StageStatus.PENDING,
        "write": StageStatus.PENDING,
    }


# ── apply_stage_event ───────────────────────────────────────────────────


def test_first_event_marks_only_that_step_current() -> None:
    # Sync starts at backup → only "backup" becomes CURRENT, rest stay PENDING.
    states, active = apply_stage_event(
        _TEST_PIPELINE,
        init_states(_TEST_PIPELINE),
        None,
        "backup",
    )
    assert active == "backup"
    assert states["backup"] == StageStatus.CURRENT
    assert all(states[k] == StageStatus.PENDING for k in ("remove", "add", "scrobble", "write"))


def test_advancing_marks_previous_done_and_new_current() -> None:
    # backup → add: backup becomes DONE, add becomes CURRENT.  remove was
    # passed over with no work, so it gets SKIPPED.
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "backup")
    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "add")

    assert active == "add"
    assert states["backup"] == StageStatus.DONE
    assert states["remove"] == StageStatus.SKIPPED
    assert states["add"] == StageStatus.CURRENT


def test_skip_is_only_applied_to_pending_steps() -> None:
    # If a step is somehow already DONE/CURRENT (shouldn't happen but the
    # function defends against it), the skip pass leaves it alone.
    states = init_states(_TEST_PIPELINE)
    states["backup"] = StageStatus.DONE
    states["remove"] = StageStatus.DONE  # pretend we ran it

    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "scrobble_listenbrainz")
    assert active == "scrobble"
    assert states["backup"] == StageStatus.DONE  # untouched
    assert states["remove"] == StageStatus.DONE  # untouched
    assert states["add"] == StageStatus.SKIPPED  # was PENDING, now SKIPPED
    assert states["scrobble"] == StageStatus.CURRENT


def test_alias_stage_maps_to_canonical_row() -> None:
    # ``remove_chapter`` is an alias of the ``remove`` row.
    states, active = apply_stage_event(
        _TEST_PIPELINE,
        init_states(_TEST_PIPELINE),
        None,
        "remove_chapter",
    )
    assert active == "remove"
    assert states["remove"] == StageStatus.CURRENT


def test_repeated_alias_within_same_step_is_noop() -> None:
    # Switching from one scrobble service to another mustn't re-flip the
    # state machine — both are aliases of the same row.
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "scrobble_listenbrainz")
    snapshot = dict(states)
    states_after, active_after = apply_stage_event(_TEST_PIPELINE, states, active, "scrobble_lastfm")

    assert active_after == "scrobble"
    assert states_after == snapshot


def test_unknown_stage_is_ignored() -> None:
    # ``transcode`` is a sub-stage that's intentionally not in the pipeline;
    # the executor emits it inside the ``add`` phase.  We must keep "add"
    # CURRENT and not touch anything else.
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "add")
    snapshot = dict(states)

    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "transcode")
    assert active == "add"
    assert states == snapshot


def test_repeated_event_for_active_step_is_noop() -> None:
    # The executor fires many events for the same stage as work progresses;
    # the state machine only reacts to transitions.
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "add")
    snapshot = dict(states)

    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "add")
    assert active == "add"
    assert states == snapshot


def test_input_states_dict_is_not_mutated() -> None:
    # Callers store the dict and pass it back in; we must return a new one.
    states = init_states(_TEST_PIPELINE)
    before = dict(states)

    apply_stage_event(_TEST_PIPELINE, states, None, "add")

    assert states == before


# ── finalize_states ─────────────────────────────────────────────────────


def test_finalize_marks_active_done_and_remaining_skipped() -> None:
    # Sync ended successfully while in the middle of "add".  add → DONE,
    # later steps that never fired → SKIPPED.
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "backup")
    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "add")

    final = finalize_states_for_end_of_sync(_TEST_PIPELINE, states, active)
    assert final["backup"] == StageStatus.DONE
    assert final["remove"] == StageStatus.SKIPPED
    assert final["add"] == StageStatus.DONE
    assert final["scrobble"] == StageStatus.SKIPPED
    assert final["write"] == StageStatus.SKIPPED


def test_finalize_marks_active_failed_when_sync_failed() -> None:
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "add")

    final = finalize_states_for_end_of_sync(_TEST_PIPELINE, states, active, failed=True)
    assert final["add"] == StageStatus.FAILED
    # Steps after the failure are still considered "didn't run".
    assert final["scrobble"] == StageStatus.SKIPPED
    assert final["write"] == StageStatus.SKIPPED


def test_finalize_with_no_active_step_marks_all_pending_skipped() -> None:
    # Nothing fired (e.g. an empty sync).  Every step ends up SKIPPED.
    states = init_states(_TEST_PIPELINE)
    final = finalize_states_for_end_of_sync(_TEST_PIPELINE, states, None)
    assert all(v == StageStatus.SKIPPED for v in final.values())


def test_finalize_does_not_overwrite_done_steps() -> None:
    states = init_states(_TEST_PIPELINE)
    states, active = apply_stage_event(_TEST_PIPELINE, states, None, "backup")
    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "remove")
    states, active = apply_stage_event(_TEST_PIPELINE, states, active, "write_database")

    # Before finalize: backup DONE, remove DONE, add SKIPPED (passed over),
    # scrobble SKIPPED (passed over), write CURRENT.
    final = finalize_states_for_end_of_sync(_TEST_PIPELINE, states, active)
    assert final["backup"] == StageStatus.DONE
    assert final["remove"] == StageStatus.DONE
    assert final["add"] == StageStatus.SKIPPED
    assert final["scrobble"] == StageStatus.SKIPPED
    assert final["write"] == StageStatus.DONE


# ── DEFAULT_PIPELINE smoke tests ────────────────────────────────────────


def test_default_pipeline_covers_known_executor_stages() -> None:
    # Every stage_id the executor actually emits should map to *some* row
    # in the canonical pipeline.  This guards against the executor adding
    # a new stage without a corresponding checklist row.
    executor_stages = {
        "backup",
        "remove",
        "remove_chapter",
        "replace_remove",
        "update_file",
        "update_metadata",
        "podcast_download",
        "add",
        "sound_check",
        "sync_playcount",
        "sync_rating",
        "scrobble",
        "scrobble_listenbrainz",
        "scrobble_lastfm",
        "playlists",
        "write_database",
        "quick_write",
        "assemble_commit",
        "commit",
        "backpatch",
        "scan_photos",
        "photo_prepare",
        "photo_write",
        "photo_compact",
    }
    covered = {s for s in executor_stages if any(step.matches(s) for step in DEFAULT_PIPELINE)}
    assert covered == executor_stages, f"executor stages without a pipeline row: {executor_stages - covered}"


def test_default_pipeline_full_walkthrough() -> None:
    # Drive the canonical pipeline through every phase in order and make
    # sure the final state has no leftover PENDING rows.
    states = init_states(DEFAULT_PIPELINE)
    active: str | None = None

    for stage in (
        "backup",
        "remove",
        "update_file",
        "update_metadata",
        "podcast_download",
        "add",
        "sound_check",
        "sync_playcount",
        "scrobble_lastfm",
        "playlists",
        "write_database",
        "backpatch",
        "photo_write",
    ):
        states, active = apply_stage_event(DEFAULT_PIPELINE, states, active, stage)

    final = finalize_states_for_end_of_sync(DEFAULT_PIPELINE, states, active)
    # Every named step that we fired should be DONE; the only one we
    # skipped (replace_remove) should be SKIPPED.
    assert final["replace_remove"] == StageStatus.SKIPPED
    expected_done = {
        "backup",
        "remove",
        "update_file",
        "update_metadata",
        "podcast_download",
        "add",
        "sound_check",
        "playcount",
        "scrobble",
        "playlists",
        "write_database",
        "backpatch",
        "photo",
    }
    for key in expected_done:
        assert final[key] == StageStatus.DONE, f"{key} should be DONE, got {final[key]}"


# ── Qt widget smoke tests ───────────────────────────────────────────────


def test_panel_widget_reflects_state_machine(qtbot) -> None:
    """End-to-end: notify_stage on the widget should rebuild row visuals."""
    from iopenpod.gui.widgets.syncStagesPanel import SyncStagesPanel

    panel = SyncStagesPanel(_TEST_PIPELINE)
    qtbot.addWidget(panel)

    # Fresh panel: every row PENDING.
    initial = panel.states_snapshot()
    assert all(v == StageStatus.PENDING for v in initial.values())
    assert panel.active_stage() is None

    # Drive a transition.
    panel.notify_stage("backup")
    assert panel.active_stage() == "backup"
    assert panel.states_snapshot()["backup"] == StageStatus.CURRENT

    panel.notify_stage("add")
    snap = panel.states_snapshot()
    assert snap["backup"] == StageStatus.DONE
    assert snap["remove"] == StageStatus.SKIPPED
    assert snap["add"] == StageStatus.CURRENT

    panel.end_of_sync()
    final = panel.states_snapshot()
    assert final["add"] == StageStatus.DONE
    assert final["scrobble"] == StageStatus.SKIPPED
    assert final["write"] == StageStatus.SKIPPED
    assert panel.active_stage() is None


def test_panel_reset_for_pipeline_clears_previous_state(qtbot) -> None:
    """Reusing the panel for a fresh sync wipes the prior run's status."""
    from iopenpod.gui.widgets.syncStagesPanel import SyncStagesPanel

    panel = SyncStagesPanel(_TEST_PIPELINE)
    qtbot.addWidget(panel)

    panel.notify_stage("add")
    panel.end_of_sync()
    assert panel.states_snapshot()["add"] == StageStatus.DONE

    # Second sync run — every row goes back to PENDING.
    panel.reset_for_pipeline(_TEST_PIPELINE)
    assert all(v == StageStatus.PENDING for v in panel.states_snapshot().values())
    assert panel.active_stage() is None
