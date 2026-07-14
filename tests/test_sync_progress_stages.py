from __future__ import annotations

from iopenpod.sync_progress_stages import (
    EXECUTION_STAGE_TO_ENGINE_STAGE,
    PIPELINE_STAGE_ROWS,
    PLANNING_STAGE_TO_ENGINE_STAGE,
    PROGRESS_STAGE_LABELS,
    classify_execution_stage_value,
    classify_planning_stage_value,
    friendly_stage_label,
    known_pipeline_stage_aliases,
    progress_stage_help,
)


def test_progress_stage_registry_labels_known_pipeline_aliases() -> None:
    missing = known_pipeline_stage_aliases() - set(PROGRESS_STAGE_LABELS)

    assert missing == set()


def test_progress_stage_registry_covers_known_executor_stages() -> None:
    known_executor_stages = {
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

    assert known_executor_stages <= known_pipeline_stage_aliases()


def test_progress_stage_registry_classifies_current_pipeline() -> None:
    assert classify_planning_stage_value("scan_playlists") == "scan"
    assert classify_planning_stage_value("scan_photos") == "scan"
    assert classify_planning_stage_value("fingerprint") == "identify"
    assert classify_planning_stage_value("load_mapping") == "load"
    assert classify_planning_stage_value("unknown") == "plan"

    assert classify_execution_stage_value("add") == "execute_files"
    assert classify_execution_stage_value("playlists") == "assemble_commit"
    assert classify_execution_stage_value("scrobble_lastfm") == "assemble_commit"
    assert classify_execution_stage_value("photo_write") == "commit"
    assert classify_execution_stage_value("backpatch") == "post_commit"
    assert classify_execution_stage_value("unknown") == "execute_files"


def test_progress_stage_registry_has_valid_engine_stage_values() -> None:
    valid_values = {
        "load",
        "migrate",
        "normalize",
        "scan",
        "identify",
        "plan",
        "validate",
        "execute_files",
        "assemble_commit",
        "commit",
        "post_commit",
        "complete",
    }

    assert set(PLANNING_STAGE_TO_ENGINE_STAGE.values()) <= valid_values
    assert set(EXECUTION_STAGE_TO_ENGINE_STAGE.values()) <= valid_values


def test_friendly_stage_label_uses_registry_with_fallback() -> None:
    assert friendly_stage_label("scan_pc") == "Scanning media folders"
    assert friendly_stage_label("bootstrap_mapping") == "Analyzing existing iPod tracks"
    assert friendly_stage_label("new_future_stage") == "New Future Stage"


def test_pipeline_row_ids_are_unique() -> None:
    row_ids = [row.stage_id for row in PIPELINE_STAGE_ROWS]

    assert len(row_ids) == len(set(row_ids))


def test_bootstrap_mapping_help_explains_one_time_fingerprint_analysis() -> None:
    help_content = progress_stage_help("bootstrap_mapping")

    assert help_content is not None
    explanation = f"{help_content.text} {help_content.informative_text}".lower()
    assert "one-time" in explanation
    assert "fingerprint" in explanation
    assert "iopenpod's database" in explanation
    assert "future sync" in explanation


def test_progress_help_is_available_only_for_explanatory_stages() -> None:
    assert progress_stage_help("fingerprint") is not None
    assert progress_stage_help("integrity") is not None
    assert progress_stage_help("scan_pc") is None
