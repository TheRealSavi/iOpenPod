"""Host counterparts for retained music, backed by checked Sync correlations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.library_sync_helper import (
    IPodTrackFingerprint,
    read_track_sync_records,
)
from storage import HostPath, StorageError
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import Track
    from storage import FileIdentity, FilesystemSession


@dataclass(frozen=True, slots=True)
class GeniusHostSource:
    """Optional read evidence; never permission to copy or replace Track media."""

    device: IPodTrackFingerprint
    path: HostPath
    size_bytes: int
    modified_ns: int

    def observe(
        self, track: Track, identity: FileIdentity, *, session: FilesystemSession
    ) -> LocalHostFile | None:
        record = self.device
        persistent_id = track.ipod.db_track_id if track.ipod else 0
        if (
            record.database_track_id != persistent_id
            or (
                record.sync is not None
                and record.sync.stream_selection_sha256 is not None
            )
            or (not persistent_id and record.track_id != track.track_id)
            or str(record.path) != track.metadata.location
            or record.size_bytes != identity.size
            or not session.modified_time_matches(
                identity.modified_ns, record.modified_ns
            )
        ):
            return None
        try:
            observed = LocalHostFile.observe(self.path)
        except (OSError, StorageError, ValueError):
            return None
        return (
            observed
            if (observed.size_bytes, observed.modified_ns)
            == (self.size_bytes, self.modified_ns)
            else None
        )


def committed_genius_sources(
    session: FilesystemSession,
    tracks: tuple[Track, ...],
    *,
    checkpoint: Callable[[], None],
) -> dict[int, GeniusHostSource]:
    sources: dict[int, GeniusHostSource] = {}
    for identity, record in read_track_sync_records(
        session, tracks, checkpoint=checkpoint
    ).items():
        checkpoint()
        sync = record.sync
        # A stream-selection digest cannot identify the actual chosen stream.
        # Analyze the prepared/device copy for those sources, never guess a stream.
        if sync is None or not sync.host_path_hint or sync.stream_selection_sha256:
            continue
        try:
            sources[identity] = GeniusHostSource(
                record,
                HostPath(sync.host_path_hint),
                sync.host_size_bytes,
                sync.host_modified_ns,
            )
        except (ValueError, StorageError):
            continue
    return sources
