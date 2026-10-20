"""Capture final video facts and bind metadata repairs to Storage preconditions."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from iOpenPod.app.media.video_metadata import (
    VIDEO_METADATA_ARGUMENTS,
    parse_video_metadata,
)
from iPodDB.library import (
    FileDependency,
    IssueSeverity,
    PreparedVideoMetadata,
    WriteIssue,
    is_video_track,
    video_metadata_required,
)
from storage import (
    DevicePath,
    FileContent,
    FilePrecondition,
    FilePreconditionError,
    StorageOperationError,
)
from storage.host_input import LocalHostFile
from storage.media_processing import find_media_tool, media_workspace, run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_write import LibraryPreparationRequest
    from iPodDB.library import LibraryWritePlan, SQLiteSource
    from storage import FilesystemSession, HostPath, TransactionWrite


def capture_video_metadata(
    session: FilesystemSession,
    request: LibraryPreparationRequest,
    plan: LibraryWritePlan,
    writes: tuple[TransactionWrite, ...],
    sources: tuple[SQLiteSource, ...],
    checkpoint: Callable[[], None],
) -> tuple[
    tuple[PreparedVideoMetadata, ...],
    tuple[FilePrecondition, ...],
    tuple[WriteIssue, ...],
]:
    if plan.blocked or not plan.changes_sqlite:
        return (), (), ()
    by_path = {str(w.path).casefold(): w for w in writes}
    missing: frozenset[int] = (
        video_metadata_required(request.snapshot, sources)
        if request.regenerate_sqlite
        else frozenset()
    )
    selected = tuple(
        t
        for t in request.snapshot.tracks
        if is_video_track(t)
        and (t.track_id in missing or t.metadata.location.casefold() in by_path)
    )
    if not selected:
        return (), (), ()
    executable = find_media_tool("ffprobe")
    metadata: list[PreparedVideoMetadata] = []
    files: list[FilePrecondition] = []
    issues: list[WriteIssue] = []
    for track in selected:
        checkpoint()
        path = DevicePath(track.metadata.location)
        if (
            not path.is_relative_to(DevicePath("iPod_Control/Music"))
            or len(path.parts) < 4
        ):
            raise ValueError(
                "Video metadata requires a file inside iPod_Control/Music."
            )
        write = by_path.get(str(path).casefold())
        try:
            if executable is None:
                raise ValueError(
                    "FFprobe is required to inspect subtitle and caption metadata."
                )
            if write is not None:
                data = _probe_write(write, executable, checkpoint)
                content = write.content
                precondition = None
            else:
                fingerprint = session.fingerprint(path)
                content = FileContent.from_fingerprint(fingerprint)
                data = session.read_with_tool(
                    path,
                    executable,
                    VIDEO_METADATA_ARGUMENTS,
                    checkpoint=checkpoint,
                    max_output_bytes=1024 * 1024,
                ).stdout
                precondition = FilePrecondition(path, fingerprint)
            playback = parse_video_metadata(data)
        except FilePreconditionError:
            raise
        except (ValueError, StorageOperationError, OSError) as error:
            if not session.is_active:
                raise
            checkpoint()
            if write is not None:
                raise ValueError(
                    f'Cannot prepare video metadata for "{track.title}": {error}'
                ) from error
            issues.append(
                WriteIssue(
                    "video.metadata_unavailable",
                    source_text(
                        'Could not repair subtitle and caption metadata for "{title}". The existing video is unchanged; Sync can retry the repair.',
                        title=track.title,
                    ),
                    severity=IssueSeverity.WARNING,
                    subject="track",
                    record_id=track.track_id,
                    artifact=str(path),
                    detail=str(error),
                )
            )
            continue
        metadata.append(
            PreparedVideoMetadata(
                track.track_id,
                FileDependency(str(path), content.size, content.sha256),
                playback,
            )
        )
        if precondition is not None:
            files.append(precondition)
    return tuple(metadata), tuple(files), tuple(issues)


def _probe_write(
    write: TransactionWrite, executable: HostPath, checkpoint: Callable[[], None]
) -> bytes:
    with media_workspace(checkpoint=checkpoint) as workspace:
        source = write.source
        if isinstance(source, bytes):
            source = workspace.capture_stream(
                io.BytesIO(source),
                ".mp4",
                max_bytes=max(1, len(source)),
                expected_size=len(source),
            ).snapshot
        observed = LocalHostFile.observe(source)
        output = run_media_tool(
            executable,
            VIDEO_METADATA_ARGUMENTS,
            input_file=source,
            checkpoint=checkpoint,
            max_output_bytes=1024 * 1024,
        )
        # Bind the observations to the bytes that the transaction will publish.
        digest = hashlib.sha256()
        with observed.open_read(checkpoint=checkpoint) as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if FileContent(observed.size_bytes, digest.hexdigest()) != write.content:
            raise FilePreconditionError(
                "The video changed while capturing playback metadata."
            )
        return output.stdout
