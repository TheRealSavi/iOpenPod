"""Shared sync progress stage registry.

This module is intentionally independent of Qt and SyncEngine package imports.
The engine uses the lifecycle stage values to classify raw progress events, and
the GUI uses the labels and aliases for progress headlines and the stage panel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressStageRow:
    """One visible row in the sync stages panel."""

    stage_id: str
    label: str
    aliases: frozenset[str]


@dataclass(frozen=True, slots=True)
class ProgressStageHelp:
    """Explanatory copy for an optional progress-screen help action."""

    title: str
    text: str
    informative_text: str


PROGRESS_STAGE_LABELS: dict[str, str] = {
    "load": "Loading sync data",
    "migrate": "Checking sync data",
    "normalize": "Preparing sync inputs",
    "scan": "Scanning media folders",
    "scan_pc": "Scanning media folders",
    "scan_ipod": "Scanning iPod library",
    "scan_playlists": "Scanning playlist files",
    "identify": "Resolving track identities",
    "plan": "Building sync plan",
    "validate": "Preparing sync",
    "execute_files": "Applying file changes",
    "assemble_commit": "Preparing database changes",
    "commit": "Writing iPod database",
    "post_commit": "Finishing sync",
    "complete": "Sync complete",
    "load_mapping": "Loading iPod mapping",
    "integrity": "Checking iPod integrity",
    "fingerprint": "Computing fingerprints",
    "bootstrap_mapping": "Analyzing existing iPod tracks",
    "duplicates": "Checking for duplicates",
    "diff": "Comparing libraries",
    "add": "Copying tracks to iPod",
    "remove": "Removing tracks from iPod",
    "remove_chapter": "Removing obsolete chapter tracks",
    "replace_remove": "Cleaning up replaced tracks",
    "update_file": "Re-syncing changed files",
    "update_metadata": "Updating metadata",
    "quality_change": "Re-syncing quality changes",
    "podcast_download": "Downloading podcasts",
    "sound_check": "Computing Sound Check",
    "playcount": "Syncing play counts and ratings",
    "sync_playcount": "Recording iPod play counts",
    "sync_rating": "Syncing ratings",
    "playlists": "Updating playlists",
    "write_database": "Writing iPod database",
    "quick_write": "Writing iPod database",
    "backpatch": "Recording source file identities",
    "backup": "Creating pre-sync backup",
    "transcode": "Transcoding",
    "scrobble": "Scrobbling plays",
    "scrobble_listenbrainz": "Scrobbling to ListenBrainz",
    "scrobble_lastfm": "Scrobbling to Last.fm",
    "scan_photos": "Scanning photos",
    "photo": "Syncing photos",
    "photo_prepare": "Preparing photos",
    "photo_write": "Writing photo database",
    "photo_compact": "Cleaning up photo thumbnails",
    "backsync_scan_pc": "Back Sync: checking PC library",
    "backsync_pc_fingerprint": "Back Sync: identifying PC tracks",
    "backsync_ipod_fingerprint": "Back Sync: finding missing iPod tracks",
    "backsync_copy": "Back Sync: exporting tracks",
}


PROGRESS_STAGE_HELP: dict[str, ProgressStageHelp] = {
    "bootstrap_mapping": ProgressStageHelp(
        title="Initial iPod analysis",
        text=(
            "Builds iOpenPod's sync database by fingerprinting music already "
            "on the iPod."
        ),
        informative_text=(
            "This is usually a one-time setup step for each existing track. "
            "iOpenPod reads the audio, calculates an acoustic fingerprint, and "
            "uses it to compare with your computer library. It saves fingerprints in"
            " iOpenPod's database so future syncs can recognize the same "
            "audio, avoid duplicate copies, and safely plan additions, updates, "
            "and removals. It may run again for any tracks added outside iOpenPod or "
            "when the mapping needs repair. The analysis does not modify the "
            "audio files on your iPod or PC."
        ),
    ),
    "fingerprint": ProgressStageHelp(
        title="Track identification",
        text=(
            "Creates content-based track identities so the same audio can be "
            "matched across your computer and iPod."
        ),
        informative_text=(
            "An acoustic fingerprint identifies a track by its audio rather than "
            "its filename or tags. iOpenPod uses fingerprints to match tracks "
            "between your computer and iPod, avoid duplicates, and detect changes "
            "reliably. Results are cached, so unchanged tracks are faster to scan "
            "during later syncs."
        ),
    ),
    "integrity": ProgressStageHelp(
        title="Pre-sync safety check",
        text=(
            "Checks that media files, iTunes database entries, and iOpenPod's "
            "saved mapping agree before syncing."
        ),
        informative_text=(
            "iOpenPod compares the iPod's media files, iTunes database, and saved "
            "track mapping. This catches missing or stale references before the "
            "sync plan is built, helping prevent duplicate copies and unsafe "
            "removals."
        ),
    ),
}


PIPELINE_STAGE_ROWS: tuple[ProgressStageRow, ...] = (
    ProgressStageRow("backup", "Pre-sync backup", frozenset({"backup"})),
    ProgressStageRow(
        "remove",
        "Remove obsolete tracks",
        frozenset({"remove", "remove_chapter"}),
    ),
    ProgressStageRow(
        "update_file",
        "Re-sync changed files",
        frozenset({"update_file"}),
    ),
    ProgressStageRow(
        "update_metadata",
        "Update metadata",
        frozenset({"update_metadata"}),
    ),
    ProgressStageRow(
        "podcast_download",
        "Download podcasts",
        frozenset({"podcast_download"}),
    ),
    ProgressStageRow("add", "Copy new tracks", frozenset({"add"})),
    ProgressStageRow(
        "replace_remove",
        "Clean up replaced tracks",
        frozenset({"replace_remove"}),
    ),
    ProgressStageRow(
        "sound_check",
        "Compute Sound Check",
        frozenset({"sound_check"}),
    ),
    ProgressStageRow(
        "playcount",
        "Sync play counts & ratings",
        frozenset({"sync_playcount", "sync_rating"}),
    ),
    ProgressStageRow(
        "scrobble",
        "Scrobble plays",
        frozenset({"scrobble", "scrobble_listenbrainz", "scrobble_lastfm"}),
    ),
    ProgressStageRow("playlists", "Update playlists", frozenset({"playlists"})),
    ProgressStageRow(
        "write_database",
        "Write iPod database",
        frozenset({"write_database", "quick_write", "assemble_commit", "commit"}),
    ),
    ProgressStageRow(
        "backpatch",
        "Record source file identities",
        frozenset({"backpatch"}),
    ),
    ProgressStageRow(
        "photo",
        "Sync photos",
        frozenset({"photo_prepare", "photo_write", "photo_compact", "scan_photos"}),
    ),
)


PLANNING_STAGE_TO_ENGINE_STAGE: dict[str, str] = {
    "scan_pc": "scan",
    "scan_playlists": "scan",
    "scan_photos": "scan",
    "fingerprint": "identify",
    "bootstrap_mapping": "identify",
    "diff": "identify",
    "integrity": "load",
    "load_mapping": "load",
}


EXECUTION_STAGE_TO_ENGINE_STAGE: dict[str, str] = {
    "add": "execute_files",
    "update_file": "execute_files",
    "remove": "execute_files",
    "remove_chapter": "execute_files",
    "replace_remove": "execute_files",
    "podcast_download": "execute_files",
    "transcode": "execute_files",
    "update_metadata": "assemble_commit",
    "playlists": "assemble_commit",
    "sound_check": "assemble_commit",
    "sync_playcount": "assemble_commit",
    "sync_rating": "assemble_commit",
    "scrobble": "assemble_commit",
    "scrobble_listenbrainz": "assemble_commit",
    "scrobble_lastfm": "assemble_commit",
    "write_database": "commit",
    "quick_write": "commit",
    "photos": "commit",
    "photo_prepare": "commit",
    "photo_write": "commit",
    "photo_compact": "commit",
    "backpatch": "post_commit",
}


def friendly_stage_label(stage: str) -> str:
    """Return the user-facing label for a raw progress stage."""

    return PROGRESS_STAGE_LABELS.get(stage, stage.replace("_", " ").title())


def progress_stage_help(stage: str) -> ProgressStageHelp | None:
    """Return optional explanatory copy for a raw progress stage."""

    return PROGRESS_STAGE_HELP.get(stage)


def classify_planning_stage_value(stage: str) -> str:
    """Map a raw planning stage to a canonical engine lifecycle value."""

    return PLANNING_STAGE_TO_ENGINE_STAGE.get(stage, "plan")


def classify_execution_stage_value(stage: str) -> str:
    """Map a raw execution stage to a canonical engine lifecycle value."""

    return EXECUTION_STAGE_TO_ENGINE_STAGE.get(stage, "execute_files")


def known_pipeline_stage_aliases() -> frozenset[str]:
    """Return every raw stage name covered by the visible stage panel."""

    aliases: set[str] = set()
    for row in PIPELINE_STAGE_ROWS:
        aliases.add(row.stage_id)
        aliases.update(row.aliases)
    return frozenset(aliases)


__all__ = [
    "EXECUTION_STAGE_TO_ENGINE_STAGE",
    "PIPELINE_STAGE_ROWS",
    "PLANNING_STAGE_TO_ENGINE_STAGE",
    "PROGRESS_STAGE_HELP",
    "PROGRESS_STAGE_LABELS",
    "ProgressStageHelp",
    "ProgressStageRow",
    "classify_execution_stage_value",
    "classify_planning_stage_value",
    "friendly_stage_label",
    "known_pipeline_stage_aliases",
    "progress_stage_help",
]
