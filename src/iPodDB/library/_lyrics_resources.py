"""Validate application evidence for media-file lyrics edits without doing I/O."""

from iPodDB.library._artwork_writing import validated_path
from iPodDB.library.writing import LibraryWritePlan, WriteIssue, WriteResources


def validate_lyrics(
    plan: LibraryWritePlan, resources: WriteResources
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = []
    tracks = {track.track_id: track for track in plan.draft.snapshot.tracks}
    supplied = {item.track_id: item for item in resources.lyrics}
    media = {item.track_id: item for item in resources.media}
    required = frozenset(plan.required_lyrics)
    if len(supplied) != len(resources.lyrics):
        issues.append(
            WriteIssue(
                "resources.duplicate_lyrics",
                "Lyrics resources repeat a Track identity.",
            )
        )
    issues.extend(
        WriteIssue(
            "resources.missing_lyrics",
            "Supply verified embedded lyrics and the resulting media file identity.",
            subject="track",
            record_id=identity,
            field="metadata.lyrics",
        )
        for identity in plan.required_lyrics
        if identity not in supplied
    )
    for item in resources.lyrics:
        try:
            if item.track_id not in required:
                raise ValueError(
                    "Embedded lyrics were supplied without a requested lyrics change."
                )
            track = tracks[item.track_id]
            validated_path(item.file.relative_path)
            if (
                item.lyrics != track.metadata.lyrics
                or item.file.relative_path != track.metadata.location
            ):
                raise ValueError(
                    "Embedded lyrics do not match the requested text and Track location."
                )
            if (
                not 0 < item.file.size <= 0xFFFFFFFF
                or len(item.file.sha256) != 64
                or len(bytes.fromhex(item.file.sha256)) != 32
            ):
                raise ValueError(
                    "Embedded lyrics require a nonempty media file with a 32-bit size and SHA-256 fingerprint."
                )
            prepared_media = media.get(item.track_id)
            if prepared_media is not None and prepared_media.file != item.file:
                raise ValueError(
                    "Prepared media and embedded lyrics identify different file content."
                )
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "resources.invalid_lyrics",
                    str(error),
                    subject="track",
                    record_id=item.track_id,
                    field="metadata.lyrics",
                )
            )
    return tuple(issues)
