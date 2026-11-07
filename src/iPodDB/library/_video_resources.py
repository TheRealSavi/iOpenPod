"""Validate observations for SQLite video metadata without opening media files."""

from iPodDB.library._artwork_writing import validated_path
from iPodDB.library.video import is_video_track
from iPodDB.library.writing import LibraryWritePlan, WriteIssue, WriteResources


def validate_video_metadata(
    plan: LibraryWritePlan, resources: WriteResources
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = []
    tracks = {t.track_id: t for t in plan.draft.snapshot.tracks}
    supplied = {item.track_id for item in resources.video_metadata}
    final_files = {m.track_id: m.file for m in resources.media}
    final_files.update({m.track_id: m.file for m in resources.lyrics})
    if len(supplied) != len(resources.video_metadata):
        issues.append(
            WriteIssue(
                "resources.duplicate_video_metadata",
                "Video playback metadata repeats a Track identity.",
            )
        )
    for item in resources.video_metadata:
        try:
            track = tracks.get(item.track_id)
            if (
                not plan.changes_sqlite
                or track is None
                or not is_video_track(track)
                or not (
                    plan.draft.regenerate_sqlite
                    or item.track_id in plan.required_media
                    or item.track_id in plan.required_lyrics
                )
            ):
                raise ValueError(
                    "Video metadata requires a video media write or explicit SQLite refresh."
                )
            validated_path(item.file.relative_path)
            if item.file.relative_path != track.metadata.location:
                raise ValueError("Video metadata refers to a different Track location.")
            if (
                not 0 < item.file.size <= 0xFFFFFFFF
                or len(item.file.sha256) != 64
                or len(bytes.fromhex(item.file.sha256)) != 32
            ):
                raise ValueError(
                    "Video metadata requires a nonempty file and SHA-256 fingerprint."
                )
            final = final_files.get(item.track_id)
            if (final is not None and final != item.file) or (
                final is None and item.file.size != track.size_bytes
            ):
                raise ValueError(
                    "Video metadata does not describe the final media bytes."
                )
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "resources.invalid_video_metadata",
                    str(error),
                    subject="track",
                    record_id=item.track_id,
                )
            )
    return tuple(issues)
