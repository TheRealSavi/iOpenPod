"""Public iPod Library translation while retaining lossless source documents."""

from __future__ import annotations

import logging
from copy import copy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import (
    EMPTY_ARTWORK_INDEX,
    build_artwork_index,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.device_time import DeviceTimeContext
from iPodDB.iTunesDB.cdb import decompress_iTunesCDB, is_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.library._photo_projection import project_photos
from iPodDB.library._playlist_projection import project_playlists
from iPodDB.library._projection import link_artwork, project_tracks
from iPodDB.library._sidecar_projection import project_sidecars
from iPodDB.library._write_logging import log_plan
from iPodDB.library.artwork import ArtworkRead, CoverFormat, select_artwork
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.photos import (
    PhotoRead,
    PhotoThumbnailFormat,
    select_photo_thumbnail,
)
from iPodDB.library.writing import (
    LibraryDraft,
    LibraryWritePlan,
    LibraryWriteResult,
    WriteIssue,
    WritePhase,
    WriteResources,
    WriteTarget,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
    from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
    from iPodDB.library._resolved_write import ResolvedWrite
    from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader as PhotosMhfdHeader
    from iPodDB.shared.chunk import DatabaseDocument
    from iPodDB.sidecars import PlaybackSidecar


@dataclass(frozen=True, slots=True)
class LibraryDatabaseBytes:
    """Lossless database output; persistence remains the caller's responsibility."""

    itunes: bytes
    artwork: bytes | None
    photos: bytes | None = None


class IPodLibrary:
    """An iPod source adapter; only its semantic snapshot enters application state."""

    __slots__ = (
        "_artwork_document",
        "_artwork_index",
        "_cdb_framing",
        "_consumed_sidecars",
        "_database_snapshot",
        "_device_time",
        "_document",
        "_photos_document",
        "_sidecar_issues",
        "_sidecars",
        "_snapshot",
        "_source_itunes",
        "_source_revision",
    )

    def __init__(
        self, data: bytes, *, device_time: DeviceTimeContext | None = None
    ) -> None:
        self._source_revision = uuid4().hex
        self._source_itunes = bytes(data)
        self._cdb_framing = decompress_iTunesCDB(data) if is_iTunesCDB(data) else None
        logical = (
            self._cdb_framing.logical_bytes if self._cdb_framing is not None else data
        )
        self._document: DatabaseDocument[MhbdHeader] = parse_iTunesDB(logical)
        self._device_time = (device_time or DeviceTimeContext()).for_database(
            self._document.header.timezone_offset
        )
        tracks = project_tracks(self._document, self._device_time)
        playlists, device_name = project_playlists(
            self._document,
            frozenset(track.track_id for track in tracks),
            self._device_time,
        )
        self._snapshot = LibrarySnapshot(tracks, playlists, device_name)
        self._database_snapshot = self._snapshot
        self._sidecars: tuple[PlaybackSidecar, ...] = ()
        self._consumed_sidecars: tuple[PlaybackSidecar, ...] = ()
        self._sidecar_issues: tuple[WriteIssue, ...] = ()
        self._artwork_document: DatabaseDocument[MhfdHeader] | None = None
        self._photos_document: DatabaseDocument[PhotosMhfdHeader] | None = None
        self._artwork_index = EMPTY_ARTWORK_INDEX
        logger.debug(
            "Library loaded source=%s iTunesDB_bytes=%d tracks=%d playlists=%d",
            self._source_revision,
            len(data),
            len(tracks),
            len(playlists),
        )

    @property
    def snapshot(self) -> LibrarySnapshot:
        """Return the read-only projection of this adapter's retained documents."""

        return self._snapshot

    @property
    def consumed_sidecars(self) -> tuple[PlaybackSidecar, ...]:
        """Evidence that must be retired with a successfully prepared Library."""
        return self._consumed_sidecars

    @property
    def sidecar_issues(self) -> tuple[WriteIssue, ...]:
        return self._sidecar_issues

    def with_sidecars(self, sidecars: tuple[PlaybackSidecar, ...]) -> IPodLibrary:
        """Replace the firmware overlay; repeated calls never accumulate deltas."""
        updated = copy(self)
        updated._sidecars = tuple(sidecars)
        updated._refresh_sidecars()
        updated._source_revision = uuid4().hex
        return updated

    def _refresh_sidecars(self) -> None:
        projection = project_sidecars(
            self._database_snapshot, self._sidecars, self._device_time
        )
        self._snapshot = projection.snapshot
        self._consumed_sidecars = projection.consumed
        self._sidecar_issues = projection.issues

    @classmethod
    def parse(
        cls, data: bytes, *, device_time: DeviceTimeContext | None = None
    ) -> IPodLibrary:
        """Parse iTunesDB bytes and translate records without filesystem access."""

        return cls(data, device_time=device_time)

    @property
    def device_time(self) -> DeviceTimeContext:
        return self._device_time

    def with_device_time(self, context: DeviceTimeContext) -> IPodLibrary:
        """Reproject with captured evidence before publishing a Library snapshot."""
        updated = copy(self)
        updated._device_time = context.for_database(
            self._document.header.timezone_offset
        )
        tracks = project_tracks(self._document, updated._device_time)
        if self._artwork_document is not None:
            tracks = link_artwork(tracks, self._artwork_index)
        playlists, name = project_playlists(
            self._document, frozenset(t.track_id for t in tracks), updated._device_time
        )
        photos = None
        if self._photos_document is not None:
            photos = project_photos(
                self._photos_document,
                {
                    t.ipod.db_track_id: t.track_id
                    for t in tracks
                    if t.ipod is not None and t.ipod.db_track_id
                },
                updated._device_time,
            )
        updated._database_snapshot = LibrarySnapshot(tracks, playlists, name, photos)
        updated._refresh_sidecars()
        updated._source_revision = uuid4().hex
        return updated

    def with_artwork(self, data: bytes) -> IPodLibrary:
        """Return a new adapter with ArtworkDB relationships resolved once."""

        database = parse_ArtworkDB(data)
        index = build_artwork_index(database)
        tracks = link_artwork(self._database_snapshot.tracks, index)
        updated = copy(self)
        updated._database_snapshot = replace(self._database_snapshot, tracks=tracks)
        updated._refresh_sidecars()
        updated._artwork_document = database
        updated._source_revision = uuid4().hex
        updated._artwork_index = index
        logger.debug(
            "Library artwork loaded source=%s ArtworkDB_bytes=%d images=%d",
            updated._source_revision,
            len(data),
            len(index.items),
        )
        return updated

    def with_photos(self, data: bytes) -> IPodLibrary:
        """Return a new adapter exposing the retained Photo Database semantically."""

        database = parse_PhotosDB(data)
        persistent_track_ids = {
            track.ipod.db_track_id: track.track_id
            for track in self.snapshot.tracks
            if track.ipod is not None and track.ipod.db_track_id
        }
        photos = project_photos(database, persistent_track_ids, self._device_time)
        updated = copy(self)
        updated._database_snapshot = replace(self._database_snapshot, photos=photos)
        updated._refresh_sidecars()
        updated._photos_document = database
        updated._source_revision = uuid4().hex
        logger.debug(
            "Library photos loaded source=%s PhotosDB_bytes=%d photos=%d albums=%d",
            updated._source_revision,
            len(data),
            len(photos.photos),
            len(photos.albums),
        )
        return updated

    def begin_draft(
        self,
        snapshot: LibrarySnapshot | None = None,
        *,
        delete_omissions: bool = False,
        replace_media: tuple[int, ...] = (),
        replace_photos: tuple[int, ...] = (),
    ) -> LibraryDraft:
        """Bind desired state to this source, rejecting omissions unless opted in.

        ``delete_omissions`` authorizes deletion of omitted source Tracks and
        Playlists in this draft only. Other validation still applies.
        ``replace_media`` requests replacement content for retained Track IDs,
        including when their projected metadata stays unchanged. Preparation
        requires matching Prepared Media; it does not publish any files.
        """
        return LibraryDraft(
            self._source_revision,
            self.snapshot if snapshot is None else snapshot,
            delete_omissions=delete_omissions,
            replace_media=tuple(replace_media),
            replace_photos=tuple(replace_photos),
        )

    def analyze(
        self, draft: LibraryDraft, target: WriteTarget | None = None
    ) -> LibraryWritePlan:
        plan = self._resolve(draft, target or WriteTarget()).plan
        log_plan(plan, self.snapshot)
        return plan

    @property
    def time_warnings(self) -> tuple[WriteIssue, ...]:
        from iPodDB.library._time_warnings import time_warnings

        return time_warnings(self._document, self._photos_document, self._device_time)

    def _resolve(self, draft: LibraryDraft, target: WriteTarget) -> ResolvedWrite:
        from iPodDB.library._resolve_write import resolve

        resolved = resolve(
            self._document,
            self._database_snapshot,
            draft,
            target,
            self._source_revision,
            self._device_time,
        )
        additional_issues = self.time_warnings
        if not draft.delete_omissions:
            persisted = {p.playlist_id for p in self._database_snapshot.playlists}
            desired = {p.playlist_id for p in draft.snapshot.playlists}
            additional_issues += tuple(
                WriteIssue(
                    "draft.deletion_not_enabled",
                    "An imported On-The-Go Playlist was removed without deletion being authorized.",
                    subject="playlist",
                    record_id=playlist.playlist_id,
                )
                for playlist in self.snapshot.playlists
                if playlist.playlist_id not in persisted
                and playlist.playlist_id not in desired
            )
        if (
            resolved.plan.changes_itunes
            and target.sqlite_database
            and any(
                issue.code == "source.unavailable_dates"
                and issue.artifact == "iTunesDB"
                for issue in additional_issues
            )
        ):
            additional_issues = (
                *additional_issues,
                WriteIssue(
                    "source.sqlite_unavailable_dates",
                    "SQLite regeneration requires resolved Track dates. Reload with a known timezone before saving this Library.",
                    phase="source",
                ),
            )
        return replace(
            resolved,
            plan=replace(
                resolved.plan,
                requires_sidecar_inventory=resolved.plan.requires_sidecar_inventory
                or bool(self._consumed_sidecars),
                issues=(
                    *resolved.plan.issues,
                    *additional_issues,
                    *self._sidecar_issues,
                ),
            ),
        )

    def prepare(
        self,
        plan: LibraryWritePlan,
        resources: WriteResources | None = None,
        *,
        progress: Callable[[WritePhase], None] | None = None,
    ) -> LibraryWriteResult:
        """Return a verified candidate without modifying this source or doing I/O.

        ``progress`` receives entered stages synchronously. It may raise to stop
        preparation; caller exceptions propagate without becoming format errors.
        No-op preparation only enters validation and lossless serialization.
        """
        from iPodDB.library._write_preparation import prepare

        baseline = copy(self)
        baseline._snapshot = self._database_snapshot
        return prepare(
            baseline,
            self._document,
            self._artwork_document,
            self._artwork_index,
            self._photos_document,
            plan,
            resources or WriteResources(),
            resolve=self._resolve,
            source_revision=self._source_revision,
            cdb_framing=self._cdb_framing,
            progress=progress,
        )

    def artwork_read(
        self, artwork_id: int, formats: tuple[CoverFormat, ...], target_px: int
    ) -> ArtworkRead | None:
        """Plan one lazy byte-range read near the requested physical size."""

        if artwork_id <= 0 or target_px <= 0:
            return None
        item = self._artwork_index.item_for_image_id(artwork_id)
        return None if item is None else select_artwork(item, formats, target_px)

    def photo_read(
        self,
        photo_id: int,
        formats: tuple[PhotoThumbnailFormat, ...],
        target_px: int,
        *,
        format_id: int | None = None,
    ) -> PhotoRead | None:
        """Plan one lazy Photo thumbnail read without opening a device path."""

        photos = self.snapshot.photos
        if photos is None or photo_id <= 0 or target_px <= 0:
            return None
        photo = next(
            (item for item in photos.photos if item.photo_id == photo_id),
            None,
        )
        return (
            None
            if photo is None
            else select_photo_thumbnail(
                photo,
                formats,
                target_px,
                format_id=format_id,
            )
        )

    def serialize(self) -> LibraryDatabaseBytes:
        """Reproduce retained databases, including Unknown Data, without I/O.

        Snapshots are read projections, not substitutes for the lossless document.
        Editing or constructing a snapshot alone does not edit retained databases.
        """

        return LibraryDatabaseBytes(
            itunes=self._source_itunes,
            artwork=(
                write_ArtworkDB(self._artwork_document)
                if self._artwork_document is not None
                else None
            ),
            photos=(
                write_PhotosDB(self._photos_document)
                if self._photos_document is not None
                else None
            ),
        )
