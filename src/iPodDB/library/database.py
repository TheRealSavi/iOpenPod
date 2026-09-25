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
from iPodDB.iTunesDB.cdb import decompress_iTunesCDB, is_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.library._photo_projection import project_photos
from iPodDB.library._playlist_projection import project_playlists
from iPodDB.library._projection import link_artwork, project_tracks
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
        "_document",
        "_photos_document",
        "_snapshot",
        "_source_itunes",
        "_source_revision",
    )

    def __init__(self, data: bytes) -> None:
        self._source_revision = uuid4().hex
        self._source_itunes = bytes(data)
        logical = (
            decompress_iTunesCDB(data).logical_bytes if is_iTunesCDB(data) else data
        )
        self._document: DatabaseDocument[MhbdHeader] = parse_iTunesDB(logical)
        tracks = project_tracks(self._document)
        playlists, device_name = project_playlists(
            self._document, frozenset(track.track_id for track in tracks)
        )
        self._snapshot = LibrarySnapshot(tracks, playlists, device_name)
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

    @classmethod
    def parse(cls, data: bytes) -> IPodLibrary:
        """Parse iTunesDB bytes and translate records without filesystem access."""

        return cls(data)

    def with_artwork(self, data: bytes) -> IPodLibrary:
        """Return a new adapter with ArtworkDB relationships resolved once."""

        database = parse_ArtworkDB(data)
        index = build_artwork_index(database)
        tracks = link_artwork(self.snapshot.tracks, index)
        updated = copy(self)
        updated._snapshot = replace(self.snapshot, tracks=tracks)
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
        photos = project_photos(database, persistent_track_ids)
        updated = copy(self)
        updated._snapshot = replace(self.snapshot, photos=photos)
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

    def _resolve(self, draft: LibraryDraft, target: WriteTarget) -> ResolvedWrite:
        from iPodDB.library._resolve_write import resolve

        return resolve(
            self._document, self.snapshot, draft, target, self._source_revision
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

        return prepare(
            self,
            self._document,
            self._artwork_document,
            self._artwork_index,
            self._photos_document,
            plan,
            resources or WriteResources(),
            source_revision=self._source_revision,
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
