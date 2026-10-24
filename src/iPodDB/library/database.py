"""Public iPod Library translation while retaining lossless source documents."""

from __future__ import annotations

import logging
from copy import copy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from iPodDB.ArtworkDB.parser.repair_ArtworkDB import repair_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import (
    EMPTY_ARTWORK_INDEX,
    build_artwork_index,
)
from iPodDB.device_time import DeviceTimeContext
from iPodDB.iTunesDB.cdb import decompress_iTunesCDB, is_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.library._genius_reconciliation import reconcile_genius_playlists
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
    IssueSeverity,
    LibraryChange,
    LibraryDraft,
    LibraryWritePlan,
    LibraryWriteResult,
    WriteChecksum,
    WriteIssue,
    WritePhase,
    WriteResources,
    WriteTarget,
)
from iPodDB.PhotosDB.parser.repair_PhotosDB import repair_PhotosDB

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.ArtworkDB.parser.repair_ArtworkDB import ArtworkDBCountRepair
    from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
    from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
    from iPodDB.library._resolved_write import ResolvedWrite
    from iPodDB.library.genius import GeniusUpdate
    from iPodDB.library.writing import RetainedArtworkFile
    from iPodDB.PhotosDB.parser.repair_PhotosDB import PhotosDBCountRepair
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
        "_artwork_repairs",
        "_cdb_framing",
        "_consumed_sidecars",
        "_database_snapshot",
        "_device_time",
        "_document",
        "_photos_document",
        "_photos_repairs",
        "_sidecar_issues",
        "_sidecars",
        "_snapshot",
        "_source_artwork",
        "_source_itunes",
        "_source_photos",
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
        self._source_artwork: bytes | None = None
        self._artwork_repairs: tuple[ArtworkDBCountRepair, ...] = ()
        self._photos_document: DatabaseDocument[PhotosMhfdHeader] | None = None
        self._source_photos: bytes | None = None
        self._photos_repairs: tuple[PhotosDBCountRepair, ...] = ()
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
        """Resolve artwork, recovering evidenced counts while retaining source bytes."""

        recovered = repair_ArtworkDB(data)
        database = recovered.document
        index = build_artwork_index(database)
        tracks = link_artwork(self._database_snapshot.tracks, index)
        updated = copy(self)
        updated._database_snapshot = replace(self._database_snapshot, tracks=tracks)
        updated._refresh_sidecars()
        updated._artwork_document = database
        updated._source_artwork = bytes(data)
        updated._artwork_repairs = recovered.repairs
        updated._source_revision = uuid4().hex
        updated._artwork_index = index
        logger.debug(
            "Library artwork loaded source=%s ArtworkDB_bytes=%d images=%d",
            updated._source_revision,
            len(data),
            len(index.items),
        )
        return updated

    @property
    def artwork_repairs(self) -> tuple[ArtworkDBCountRepair, ...]:
        """Verified structural repairs awaiting ordinary Library publication."""
        return self._artwork_repairs

    def with_photos(self, data: bytes) -> IPodLibrary:
        """Return a new adapter exposing the retained Photo Database semantically."""

        recovered = repair_PhotosDB(data)
        database = recovered.document
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
        updated._source_photos = bytes(data)
        updated._photos_repairs = recovered.repairs
        updated._source_revision = uuid4().hex
        logger.debug(
            "Library photos loaded source=%s PhotosDB_bytes=%d photos=%d albums=%d",
            updated._source_revision,
            len(data),
            len(photos.photos),
            len(photos.albums),
        )
        return updated

    @property
    def photos_repairs(self) -> tuple[PhotosDBCountRepair, ...]:
        """Evidenced Photo image-list repairs awaiting verified publication."""
        return self._photos_repairs

    @property
    def photo_thumbnail_files(self) -> tuple[RetainedArtworkFile, ...]:
        """Raw retained thumbnail allocations, including optional allocation padding."""
        from iPodDB.library._photo_extents import retained_photo_thumbnail_files

        return (
            ()
            if self._photos_document is None
            else retained_photo_thumbnail_files(self._photos_document)
        )

    def begin_draft(
        self,
        snapshot: LibrarySnapshot | None = None,
        *,
        delete_omissions: bool = False,
        replace_media: tuple[int, ...] = (),
        replace_photos: tuple[int, ...] = (),
        retag_tracks: tuple[int, ...] = (),
        regenerate_sqlite: bool = False,
        rebuild_album_indexes: bool = False,
        repair_podcast_links: bool = False,
        normalize_podcasts: bool = False,
        genius_update: GeniusUpdate | None = None,
    ) -> LibraryDraft:
        """Bind desired state to this source, rejecting omissions unless opted in.

        ``delete_omissions`` authorizes deletion of omitted source Tracks and
        Playlists in this draft only. Other validation still applies.
        ``replace_media`` requests replacement content for retained Track IDs,
        including when their projected metadata stays unchanged. Preparation
        requires matching Prepared Media; it does not publish any files.
        ``retag_tracks`` requests verified file-tag rewrites at retained locations;
        PreparedLyrics evidence derives the final size without new codec facts.
        ``regenerate_sqlite`` requests a fresh firmware projection even when the
        desired Library is unchanged. It does not authorize file publication.
        ``rebuild_album_indexes`` repairs retained Albums browse indexes without
        requiring metadata edits. Other indexes and Master occurrences remain.
        ``normalize_podcasts`` converges Podcast relationships, albums, Playlist
        settings and traversal indexes on the 12.6 authoring policy (ADR-0152).
        ``genius_update`` replaces the native graph and Track assignments.
        Its ``mixes=None`` preserves native Mixes, while an explicit tuple
        replaces them. Omission preserves all Genius state. Classic preparation
        requires captured
        Extras bytes when changing existing Genius identities; callers publish
        the resulting companion together with iTunesDB (ADR-0176).
        """
        desired = self.snapshot if snapshot is None else snapshot
        if delete_omissions:
            desired = reconcile_genius_playlists(self.snapshot, desired)
        return LibraryDraft(
            self._source_revision,
            desired,
            delete_omissions=delete_omissions,
            replace_media=tuple(replace_media),
            replace_photos=tuple(replace_photos),
            retag_tracks=tuple(retag_tracks),
            regenerate_sqlite=regenerate_sqlite,
            rebuild_album_indexes=rebuild_album_indexes,
            repair_podcast_links=repair_podcast_links,
            normalize_podcasts=normalize_podcasts,
            genius_update=genius_update,
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
        if draft.genius_update is not None:
            from iPodDB.SQLiteDB.genius_projection import validate_genius_update

            try:
                validate_genius_update(
                    draft.genius_update,
                    {
                        t.track_id: t.ipod.db_track_id if t.ipod else t.track_id
                        for t in draft.snapshot.tracks
                    },
                )
            except ValueError as error:
                additional_issues += (WriteIssue("genius.invalid_update", str(error)),)
            resolved = replace(
                resolved,
                plan=replace(
                    resolved.plan,
                    changes=(
                        *resolved.plan.changes,
                        LibraryChange("genius", None, "update", "Native Genius data"),
                    ),
                ),
            )
            if (
                draft.genius_update.mixes
                or draft.genius_update.mix_additions
                or draft.genius_update.mix_removals
            ) and not target.sqlite_database:
                additional_issues += (
                    WriteIssue(
                        "genius.mix_requires_sqlite",
                        "Native Genius Mix authoring requires a SQLite artifact target.",
                    ),
                )
        if self._photos_repairs:
            resolved = replace(
                resolved,
                plan=replace(
                    resolved.plan,
                    changes=(
                        *resolved.plan.changes,
                        LibraryChange(
                            "photos_database",
                            None,
                            "repair",
                            "Photo Database image count",
                            ("image_count",),
                        ),
                    ),
                ),
            )
            additional_issues += tuple(
                WriteIssue(
                    "photos.repaired_image_count",
                    "The Photo Database image count was recovered from complete retained records and will be corrected when saved.",
                    severity=IssueSeverity.INFO,
                    phase="source",
                    subject="photos_database",
                    field="image_count",
                    detail=f"{repair.previous_count} -> {repair.corrected_count}",
                    offset=repair.list_offset,
                    artifact="PhotosDB",
                )
                for repair in self._photos_repairs
            )
        if self._artwork_repairs:
            resolved = replace(
                resolved,
                plan=replace(
                    resolved.plan,
                    changes=(
                        *resolved.plan.changes,
                        LibraryChange(
                            "artwork_database",
                            None,
                            "repair",
                            "ArtworkDB image count",
                            ("image_count",),
                        ),
                    ),
                ),
            )
            additional_issues += tuple(
                WriteIssue(
                    "artwork.repaired_image_count",
                    "The ArtworkDB image count was recovered from complete retained records and will be corrected when saved.",
                    severity=IssueSeverity.INFO,
                    phase="source",
                    subject="artwork_database",
                    field="image_count",
                    detail=f"{repair.previous_count} -> {repair.corrected_count}",
                    offset=repair.list_offset,
                    artifact="ArtworkDB",
                )
                for repair in self._artwork_repairs
            )
            if target.artwork_checksum is not WriteChecksum.NONE and not any(
                issue.code == "target.unsupported_artwork_signature"
                for issue in resolved.plan.issues
            ):
                additional_issues += (
                    WriteIssue(
                        "target.unsupported_artwork_signature",
                        "The ArtworkDB artifact requires an unsupported signature.",
                    ),
                )
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
        if resolved.plan.changes_sqlite and any(
            issue.code == "source.unavailable_dates" and issue.artifact == "iTunesDB"
            for issue in additional_issues
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

    def artwork_display_times(self, artwork_id: int) -> tuple[int, ...]:
        """List retained group keys, including groups without a readable raster."""
        item = self._artwork_index.item_for_image_id(artwork_id)
        return item.display_times if item is not None else ()

    def artwork_read(
        self,
        artwork_id: int,
        formats: tuple[CoverFormat, ...],
        target_px: int,
        *,
        display_time_ms: int | None = None,
    ) -> ArtworkRead | None:
        """Plan a lazy cover read, or an exact time-group read when specified."""

        if artwork_id <= 0 or target_px <= 0:
            return None
        item = self._artwork_index.item_for_image_id(artwork_id)
        return (
            None
            if item is None
            else select_artwork(
                item, formats, target_px, display_time_ms=display_time_ms
            )
        )

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
            artwork=self._source_artwork,
            photos=self._source_photos,
        )
