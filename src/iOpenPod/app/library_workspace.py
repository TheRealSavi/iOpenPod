"""One session draft for Library metadata, Playlists, Photos, and device naming."""

from dataclasses import dataclass, replace
from itertools import pairwise
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from iOpenPod.app.media.importing import ImportedSong, LibraryMediaSource
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.smart_playlist_preview import preview_smart_playlist
from iOpenPod.app.track_conversion import convert_track_to_podcast, reclassify_track
from iOpenPod.app.track_playback_policy import enforce_track_playback_policy
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    IPodPhotoAlbumDetails,
    LibrarySnapshot,
    MediaType,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoLibrary,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    PlaylistSort,
    PlaylistSortOrder,
    SmartPlaylist,
    Track,
    TrackEditError,
    TrackFieldEdit,
    WriteIssue,
    edit_track_metadata,
    order_playlist_entries,
    playlist_entries,
    smart_playlist_references,
    validate_smart_playlist,
)


@dataclass(frozen=True, slots=True)
class EditRevision:
    generation: int
    revision: int


@dataclass(frozen=True, slots=True)
class TrackUpdate:
    track_id: int
    edits: tuple[TrackFieldEdit, ...]


@dataclass(frozen=True, slots=True)
class TrackArtworkEdit:
    """One explicit artwork assignment shared by a Track selection."""

    pixels: ArtworkPixels | None
    source_artwork_id: int | None = None

    def __post_init__(self) -> None:
        if self.pixels is not None and self.source_artwork_id is not None:
            raise ValueError(
                "Artwork edits cannot contain pixels and a source identity."
            )
        if self.source_artwork_id == 0:
            raise ValueError("Use an empty artwork edit to clear artwork.")


@dataclass(frozen=True, slots=True)
class PhotoUpdate:
    """Explicit editable values for one Photo; ``None`` leaves a field unchanged."""

    photo_id: int
    rating: int | None = None
    original_date: int | None = None
    taken_date: int | None = None


class LibraryWorkspace(QObject):
    """Own reversible Library drafts for one loaded Library Snapshot.

    Source records remain immutable. Loading or disconnecting an Active iPod
    discards every draft; nothing here authorizes or performs a device write.
    ``generation`` lets dialogs reject work started for an earlier Active iPod.
    """

    changed = Signal()
    tracksChanged = Signal(object)
    photosChanged = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._snapshot: LibrarySnapshot | None = None
        self._playlists: dict[int, Playlist] = {}
        self._children: dict[int | None, tuple[Playlist, ...]] = {}
        self._tracks: dict[int, Track] = {}
        self._artwork_assets: dict[int, ArtworkAsset] = {}
        self._media_sources: dict[int, LibraryMediaSource] = {}
        self._photos: PhotoLibrary | None = None
        self._photo_album_creation_type: int | None = None
        self._delete_omissions = False
        self._device_name = ""
        self._generation = 0
        self._revision = 0
        self._next_id = -1
        self._locked = False
        self.saved_playlist_ids: dict[int, int] | None = None

    @property
    def locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        """Hold edits during a physical commit, without changing the edit revision."""
        if self._locked != locked:
            self._locked = locked
            self.changed.emit()

    def _require_editable(self) -> None:
        if self._locked:
            raise ValueError("Wait for the current Library save to finish.")

    @property
    def edit_revision(self) -> EditRevision:
        return EditRevision(self._generation, self._revision)

    def require_revision(self, expected: EditRevision) -> None:
        self._require_editable()
        self._require_snapshot()
        if expected != self.edit_revision:
            raise ValueError(
                "The Library changed. Reopen this action to use the current selection."
            )

    @property
    def tracks(self) -> tuple[Track, ...]:
        return tuple(self._tracks.values())

    @property
    def device_name(self) -> str:
        return self._device_name

    def track(self, track_id: int) -> Track | None:
        return self._tracks.get(track_id)

    @property
    def photos(self) -> PhotoLibrary | None:
        return self._photos

    def photo(self, photo_id: int) -> Photo | None:
        photos = self._photos
        if photos is None:
            return None
        return next(
            (photo for photo in photos.photos if photo.photo_id == photo_id), None
        )

    def photo_album(self, album_id: int) -> PhotoAlbum | None:
        photos = self._photos
        if photos is None:
            return None
        return next(
            (album for album in photos.albums if album.album_id == album_id),
            None,
        )

    @property
    def supports_photo_album_creation(self) -> bool:
        """Whether the loaded Photo Library has an explicit native album policy."""

        return self._photos is not None and self._photo_album_creation_type is not None

    def replace_photo(self, photo: Photo, expected: EditRevision) -> None:
        """Stage supported Photo metadata while retaining source representations."""

        self.require_revision(expected)
        original = self.photo(photo.photo_id)
        if original is None:
            raise ValueError("This Photo is no longer in the Library.")
        if (
            photo.source_size_bytes != original.source_size_bytes
            or photo.representations != original.representations
        ):
            raise ValueError("Photo source data and representations are read-only.")
        self.apply_photo_edits(
            (
                PhotoUpdate(
                    photo.photo_id,
                    rating=photo.rating if photo.rating != original.rating else None,
                    original_date=(
                        photo.original_date
                        if photo.original_date != original.original_date
                        else None
                    ),
                    taken_date=(
                        photo.taken_date
                        if photo.taken_date != original.taken_date
                        else None
                    ),
                ),
            ),
            expected,
        )

    def apply_photo_edits(
        self,
        updates: tuple[PhotoUpdate, ...],
        expected: EditRevision,
    ) -> None:
        """Validate and stage one atomic batch of explicit Photo metadata edits."""

        self.require_revision(expected)
        photos = self._require_photos()
        current = {photo.photo_id: photo for photo in photos.photos}
        update_ids = tuple(update.photo_id for update in updates)
        if len(set(update_ids)) != len(update_ids) or any(
            photo_id not in current for photo_id in update_ids
        ):
            raise ValueError("The selection contains a missing or repeated Photo.")

        replacements: dict[int, Photo] = {}
        for update in updates:
            rating = update.rating
            dates = (update.original_date, update.taken_date)
            if rating is not None and (
                type(rating) is not int or not 0 <= rating <= 100
            ):
                raise ValueError(
                    "Photo ratings use 0-100; dates must be supported integer Unix seconds."
                )
            if any(value is not None and type(value) is not int for value in dates):
                raise ValueError(
                    "Photo ratings use 0-100; dates must be supported integer Unix seconds."
                )
            original = current[update.photo_id]
            replacements[update.photo_id] = replace(
                original,
                rating=original.rating if rating is None else rating,
                original_date=(
                    original.original_date
                    if update.original_date is None
                    else update.original_date
                ),
                taken_date=(
                    original.taken_date
                    if update.taken_date is None
                    else update.taken_date
                ),
            )

        edited = tuple(
            replacements.get(photo.photo_id, photo) for photo in photos.photos
        )
        if edited != photos.photos:
            self._photos = replace(photos, photos=edited)
            self._publish()
            self.photosChanged.emit(self._photos)

    def replace_photo_album(
        self,
        album: PhotoAlbum,
        expected: EditRevision,
    ) -> None:
        """Stage one retained Photo Album replacement as a reversible edit."""

        self.require_revision(expected)
        photos = self._require_photos()
        original = self.photo_album(album.album_id)
        if original is None:
            raise ValueError("This Photo Album is no longer in the Library.")
        if original.kind is PhotoAlbumKind.MASTER and album != original:
            raise ValueError("The master Photo Library album is read-only.")
        if album.kind is not original.kind or album.ipod != original.ipod:
            raise ValueError("Photo Album role and iPod diagnostics are read-only.")
        if album != original:
            self._photos = replace(
                photos,
                albums=tuple(
                    album if item.album_id == album.album_id else item
                    for item in photos.albums
                ),
            )
            self._publish()
            self.photosChanged.emit(self._photos)

    def create_photo_album(
        self,
        name: str,
        expected: EditRevision,
    ) -> PhotoAlbum:
        """Stage one empty user Photo Album using the active device's policy."""

        self.require_revision(expected)
        photos = self._require_photos()
        name = self._validate_photo_album_name(name)

        album_type = self._photo_album_creation_type
        if album_type is None:
            raise ValueError("This iPod has no Photo Album creation policy.")
        used_ids = {
            *(photo.photo_id for photo in photos.photos),
            *(album.album_id for album in photos.albums),
        }
        album_id = max((99, *used_ids)) + 1
        if album_id > 0xFFFFFFFF:
            raise ValueError("The Photo Album identity range is exhausted.")

        previous_album_id = 100
        if photos.albums:
            previous = photos.albums[-1]
            if previous.ipod is not None and previous.ipod.previous_album_id:
                previous_album_id = (
                    previous.ipod.previous_album_id + len(previous.photo_ids) + 1
                )
            else:
                previous_album_id = previous.album_id
        if not 0 <= previous_album_id <= 0xFFFFFFFF:
            raise ValueError("The Photo Album position range is exhausted.")
        album = PhotoAlbum(
            album_id=album_id,
            name=name,
            ipod=IPodPhotoAlbumDetails(
                album_type=album_type,
                previous_album_id=previous_album_id,
            ),
        )
        self._photos = replace(photos, albums=(*photos.albums, album))
        self._publish()
        self.photosChanged.emit(self._photos)
        return album

    def rename_photo_album(
        self,
        album_id: int,
        name: str,
        expected: EditRevision,
    ) -> PhotoAlbum:
        """Rename one user Photo Album as a reversible Library Draft edit."""

        self.require_revision(expected)
        album = self.photo_album(album_id)
        if album is None:
            raise ValueError("This Photo Album is no longer in the Library.")
        if album.kind is PhotoAlbumKind.MASTER:
            raise ValueError("The master Photo Library album cannot be renamed.")
        renamed = replace(album, name=self._validate_photo_album_name(name))
        if renamed != album:
            photos = self._require_photos()
            self._photos = replace(
                photos,
                albums=tuple(
                    renamed if item.album_id == album_id else item
                    for item in photos.albums
                ),
            )
            self._publish()
            self.photosChanged.emit(self._photos)
        return renamed

    def set_photo_album_membership(
        self,
        album_id: int,
        photo_ids: tuple[int, ...],
        *,
        included: bool,
        expected: EditRevision,
    ) -> None:
        """Add or remove retained Photos from one user Photo Album draft."""

        self.require_revision(expected)
        photos = self._require_photos()
        album = self.photo_album(album_id)
        if album is None:
            raise ValueError("This Photo Album is no longer in the Library.")
        if album.kind is PhotoAlbumKind.MASTER:
            raise ValueError("The master Photo Library album is read-only.")

        selected_ids = tuple(dict.fromkeys(photo_ids))
        available_ids = {photo.photo_id for photo in photos.photos}
        if not selected_ids or not set(selected_ids) <= available_ids:
            raise ValueError("Select Photos from the current Library.")

        selected = frozenset(selected_ids)
        if included:
            retained = set(album.photo_ids)
            membership = (
                *album.photo_ids,
                *(i for i in selected_ids if i not in retained),
            )
        else:
            membership = tuple(i for i in album.photo_ids if i not in selected)

        if membership != album.photo_ids:
            self._photos = replace(
                photos,
                albums=tuple(
                    replace(item, photo_ids=membership)
                    if item.album_id == album_id
                    else item
                    for item in photos.albums
                ),
            )
            self._publish()
            self.photosChanged.emit(self._photos)

    def remove_photo_album(self, album_id: int, expected: EditRevision) -> None:
        """Stage deletion of one user Photo Album without removing any Photos."""

        self.require_revision(expected)
        photos = self._require_photos()
        album = self.photo_album(album_id)
        if album is None:
            raise ValueError("This Photo Album is no longer in the Library.")
        if album.kind is PhotoAlbumKind.MASTER:
            raise ValueError("The master Photo Library album cannot be removed.")
        self._photos = replace(
            photos,
            albums=tuple(item for item in photos.albums if item.album_id != album_id),
        )
        self._delete_omissions = True
        self._publish()
        self.photosChanged.emit(self._photos)

    def remove_photos(
        self,
        photo_ids: tuple[int, ...],
        expected: EditRevision,
    ) -> None:
        """Draft explicit Photo deletions and remove every Album occurrence."""

        self.require_revision(expected)
        photos = self._require_photos()
        available_ids = {photo.photo_id for photo in photos.photos}
        if len(set(photo_ids)) != len(photo_ids) or any(
            photo_id not in available_ids for photo_id in photo_ids
        ):
            raise ValueError("The selection contains a missing or repeated Photo.")
        if not photo_ids:
            return

        removed = frozenset(photo_ids)
        self._photos = replace(
            photos,
            photos=tuple(
                photo for photo in photos.photos if photo.photo_id not in removed
            ),
            albums=tuple(
                replace(
                    album,
                    photo_ids=tuple(
                        photo_id
                        for photo_id in album.photo_ids
                        if photo_id not in removed
                    ),
                )
                for album in photos.albums
            ),
        )
        self._delete_omissions = True
        self._publish()
        self.photosChanged.emit(self._photos)

    @property
    def artwork_assets(self) -> tuple[ArtworkAsset, ...]:
        return tuple(self._artwork_assets.values())

    @property
    def media_sources(self) -> tuple[LibraryMediaSource, ...]:
        return tuple(self._media_sources.values())

    def add_songs(
        self, songs: tuple[ImportedSong, ...], expected: EditRevision
    ) -> None:
        """Apply one inspected batch atomically; all files remain on the Host."""
        self.require_revision(expected)
        self._require_snapshot()
        tracks = dict(self._tracks)
        media = dict(self._media_sources)
        assets = dict(self._artwork_assets)
        paths = {t.metadata.location.casefold() for t in tracks.values()}
        for song in songs:
            path = song.track.metadata.location.casefold()
            if not path or path in paths:
                raise ValueError(
                    "An imported destination is missing or already used in the Library."
                )
            if (song.track.size_bytes, song.track.metadata.location) != (
                song.source.media.file.size,
                song.source.media.file.relative_path,
            ) or song.source.fingerprint.sha256 != song.source.media.file.sha256:
                raise ValueError(
                    "Imported Track facts do not match the captured media."
                )
            paths.add(path)
            identity = min((0, *tracks)) - 1
            cover_id = 0
            if song.artwork is not None:
                cover_id = (
                    min((0, *(t.artwork_id for t in tracks.values()), *assets)) - 1
                )
                assets[cover_id] = ArtworkAsset(cover_id, song.artwork)
            tracks[identity] = replace(
                enforce_track_playback_policy(song.track),
                track_id=identity,
                artwork_id=cover_id,
            )
            media[identity] = replace(
                song.source, media=replace(song.source.media, track_id=identity)
            )
        if songs:
            self._tracks, self._media_sources, self._artwork_assets = (
                tracks,
                media,
                assets,
            )
            self._publish()
            self.tracksChanged.emit(self.tracks)

    @property
    def delete_omissions(self) -> bool:
        return self._delete_omissions

    def set_artwork(
        self,
        track_ids: tuple[int, ...],
        pixels: ArtworkPixels | None,
        expected: EditRevision,
    ) -> None:
        """Assign one captured cover to the selection, or explicitly clear it."""
        self.apply_track_edits(
            tuple(TrackUpdate(track_id, ()) for track_id in track_ids),
            expected,
            artwork=TrackArtworkEdit(pixels),
        )

    def remove_tracks(self, track_ids: tuple[int, ...], expected: EditRevision) -> None:
        """Draft explicit Track deletions and remove their Playlist occurrences."""
        self.require_revision(expected)
        selected = self._selected_tracks(track_ids)
        if not selected:
            return
        removed = {t.track_id for t in selected}
        self._tracks = {i: t for i, t in self._tracks.items() if i not in removed}
        self._media_sources = {
            i: s for i, s in self._media_sources.items() if i not in removed
        }
        self._playlists = {
            i: replace(
                p, entries=tuple(e for e in p.entries if e.track_id not in removed)
            )
            for i, p in self._playlists.items()
        }
        self._delete_omissions = True
        self._retain_artwork_assets()
        self._publish()
        self.tracksChanged.emit(self.tracks)

    def replace_tracks_with_chaptered_song(
        self,
        track_ids: tuple[int, ...],
        song: ImportedSong,
        expected: EditRevision,
    ) -> None:
        """Stage one verified media addition and the source omissions atomically."""
        self.require_revision(expected)
        selected = self._selected_tracks(track_ids)
        if len(selected) < 2 or any(t.track_id <= 0 for t in selected):
            raise ValueError("Choose at least two saved Tracks from one Album.")
        if len({t.album_key for t in selected}) != 1 or not selected[0].album:
            raise ValueError("Choose Tracks from one named Album.")
        album_ids = {
            t.track_id
            for t in self._tracks.values()
            if t.album_key == selected[0].album_key
        }
        if album_ids != set(track_ids):
            raise ValueError("Select the complete Album before converting its Tracks.")
        location = song.track.metadata.location
        if (
            not location
            or any(
                t.metadata.location.casefold() == location.casefold()
                for t in self._tracks.values()
            )
            or (song.track.size_bytes, location)
            != (song.source.media.file.size, song.source.media.file.relative_path)
            or song.source.fingerprint.sha256 != song.source.media.file.sha256
        ):
            raise ValueError("Chaptered media does not match its verified destination.")
        chapters = song.track.metadata.chapters
        if (
            len(chapters) != len(selected)
            or chapters[0].start_ms != 0
            or any(
                left.start_ms >= right.start_ms for left, right in pairwise(chapters)
            )
            or chapters[-1].start_ms >= song.track.length_ms
        ):
            raise ValueError("The chapter timeline does not match the Album Tracks.")

        removed = set(track_ids)
        identity = min((0, *self._tracks)) - 1
        merged = replace(
            enforce_track_playback_policy(song.track),
            track_id=identity,
            artwork_id=selected[0].artwork_id,
        )
        tracks: dict[int, Track] = {}
        for track_id, track in self._tracks.items():
            if track_id in removed:
                if identity not in tracks:
                    tracks[identity] = merged
            else:
                tracks[track_id] = track
        playlists: dict[int, Playlist] = {}
        for playlist_id, playlist in self._playlists.items():
            inserted = False
            entries: list[PlaylistEntry] = []
            for entry in playlist.entries:
                if entry.track_id in removed:
                    if not inserted:
                        entries.append(PlaylistEntry(uuid4().hex, identity))
                        inserted = True
                else:
                    entries.append(entry)
            playlists[playlist_id] = replace(playlist, entries=tuple(entries))
        self._tracks = tracks
        self._playlists = playlists
        if self._photos is not None:
            self._photos = replace(
                self._photos,
                albums=tuple(
                    replace(album, music_track_id=identity)
                    if album.music_track_id in removed
                    else album
                    for album in self._photos.albums
                ),
            )
        self._media_sources = {
            track_id: source
            for track_id, source in self._media_sources.items()
            if track_id not in removed
        }
        self._media_sources[identity] = replace(
            song.source, media=replace(song.source.media, track_id=identity)
        )
        self._delete_omissions = True
        self._retain_artwork_assets()
        self._refresh_field_sorted_playlists()
        self._publish()
        self.tracksChanged.emit(self.tracks)
        if self._photos is not None:
            self.photosChanged.emit(self._photos)

    def _selected_tracks(self, track_ids: tuple[int, ...]) -> tuple[Track, ...]:
        if len(set(track_ids)) != len(track_ids) or any(
            i not in self._tracks for i in track_ids
        ):
            raise ValueError("The selection contains a missing or repeated Track.")
        return tuple(self._tracks[i] for i in track_ids)

    def _retain_artwork_assets(self) -> None:
        retained = {t.artwork_id for t in self._tracks.values()}
        self._artwork_assets = {
            i: a for i, a in self._artwork_assets.items() if i in retained
        }

    def rename_device(self, name: str, expected: EditRevision) -> None:
        self.require_revision(expected)
        name = name.strip()
        if not name:
            raise ValueError("Enter a name for the iPod.")
        try:
            name.encode("utf-16-le")
        except UnicodeEncodeError:
            raise ValueError(
                "The name contains an invalid Unicode character."
            ) from None
        if "\x00" in name:
            raise ValueError("The name cannot contain a null character.")
        if name != self._device_name:
            self._device_name = name
            self._publish()

    def apply_track_edits(
        self,
        updates: tuple[TrackUpdate, ...],
        expected: EditRevision,
        *,
        artwork: TrackArtworkEdit | None = None,
        media_type: MediaType | None = None,
    ) -> None:
        """Validate metadata, classification, and artwork before one reversible edit."""
        self.require_revision(expected)
        replacements: dict[int, Track] = {}
        issues: list[WriteIssue] = []
        for update in updates:
            track = self._tracks.get(update.track_id)
            if track is None or update.track_id in replacements:
                raise ValueError("The selection contains a missing or repeated Track.")
            try:
                replacements[track.track_id] = edit_track_metadata(track, update.edits)
                if media_type is not None:
                    replacements[track.track_id] = reclassify_track(
                        replacements[track.track_id], media_type
                    )
                replacements[track.track_id] = enforce_track_playback_policy(
                    replacements[track.track_id]
                )
            except TrackEditError as error:
                issues.extend(error.issues)
        if issues:
            raise TrackEditError(tuple(issues))

        metadata_changed = any(
            track != self._tracks[key] for key, track in replacements.items()
        )
        new_asset: ArtworkAsset | None = None
        if artwork is not None and replacements:
            identity = artwork.source_artwork_id or 0
            selected_artwork = {
                self._tracks[track_id].artwork_id for track_id in replacements
            }
            if identity and identity not in selected_artwork:
                raise ValueError("The artwork is not part of the Track selection.")
            if artwork.pixels is not None:
                used = {
                    *(track.artwork_id for track in self._tracks.values()),
                    *self._artwork_assets,
                }
                identity = -1
                while identity in used:
                    identity -= 1
                new_asset = ArtworkAsset(identity, artwork.pixels)
            replacements = {
                track_id: replace(track, artwork_id=identity)
                for track_id, track in replacements.items()
            }

        if any(track != self._tracks[key] for key, track in replacements.items()):
            self._tracks.update(replacements)
            if new_asset is not None:
                self._artwork_assets[new_asset.artwork_id] = new_asset
            self._retain_artwork_assets()
            if metadata_changed:
                self._refresh_field_sorted_playlists()
            self._publish()
            self.tracksChanged.emit(self.tracks)

    def convert_tracks_to_podcasts(
        self, track_ids: tuple[int, ...], expected: EditRevision
    ) -> None:
        """Reclassify selected retained media as Podcasts in one draft edit."""

        self.require_revision(expected)
        selected = self._selected_tracks(track_ids)
        replacements = {
            track.track_id: convert_track_to_podcast(track) for track in selected
        }
        if any(
            track != self._tracks[track_id] for track_id, track in replacements.items()
        ):
            self._tracks.update(replacements)
            self._refresh_field_sorted_playlists()
            self._publish()
            self.tracksChanged.emit(self.tracks)

    @property
    def snapshot(self) -> LibrarySnapshot | None:
        return self._snapshot

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def revision(self) -> int:
        """Monotonic edit revision, including reloads and reverted edits."""
        return self._revision

    def desired_snapshot(self) -> LibrarySnapshot:
        self._require_snapshot()
        assert self._snapshot is not None
        return replace(
            self._snapshot,
            playlists=self.playlists,
            tracks=self.tracks,
            device_name=self._device_name,
            photos=self._photos,
        )

    @property
    def playlists(self) -> tuple[Playlist, ...]:
        return tuple(self._playlists.values())

    @property
    def dirty(self) -> bool:
        snapshot = self._snapshot
        return snapshot is not None and (
            self.playlists != snapshot.playlists
            or self.tracks != snapshot.tracks
            or self._device_name != snapshot.device_name
            or self._photos != snapshot.photos
        )

    def load(
        self,
        snapshot: LibrarySnapshot | None,
        *,
        saved_playlist_ids: dict[int, int] | None = None,
        photo_album_creation_type: int | None = None,
    ) -> None:
        """Begin a new session, including when the snapshot equals its predecessor."""

        if photo_album_creation_type is not None and (
            type(photo_album_creation_type) is not int
            or not 0 < photo_album_creation_type <= 0xFF
            or photo_album_creation_type == 1
        ):
            raise ValueError(
                "Photo Album creation requires a non-master unsigned 8-bit type."
            )
        self._generation += 1
        self.saved_playlist_ids = saved_playlist_ids
        self._snapshot = snapshot
        self._artwork_assets.clear()
        self._media_sources.clear()
        self._delete_omissions = False
        self._device_name = "" if snapshot is None else snapshot.device_name
        self._photos = None if snapshot is None else snapshot.photos
        retained_album_type = next(
            (
                album.ipod.album_type
                for album in (self._photos.albums if self._photos is not None else ())
                if album.kind is not PhotoAlbumKind.MASTER
                and album.ipod is not None
                and type(album.ipod.album_type) is int
                and 0 < album.ipod.album_type <= 0xFF
                and album.ipod.album_type != 1
            ),
            None,
        )
        self._photo_album_creation_type = (
            photo_album_creation_type
            if photo_album_creation_type is not None
            else retained_album_type
        )
        self._tracks = (
            {}
            if snapshot is None
            else {track.track_id: track for track in snapshot.tracks}
        )
        self._playlists = (
            {}
            if snapshot is None
            else {playlist.playlist_id: playlist for playlist in snapshot.playlists}
        )
        self._publish()
        self.photosChanged.emit(self._photos)

    @Slot(object)
    def active_ipod_changed(self, value: object) -> None:
        """Discard drafts whenever device selection changes or is disconnected."""

        if isinstance(value, ActiveIPod) and value.library is self._snapshot:
            # Discovery updates volume facts without loading a new source.
            return
        self.load(
            value.library if isinstance(value, ActiveIPod) else None,
            photo_album_creation_type=(
                value.profile.capabilities.artwork.photo_album_creation_type
                if isinstance(value, ActiveIPod)
                else None
            ),
        )

    def playlist(self, playlist_id: int) -> Playlist | None:
        return self._playlists.get(playlist_id)

    def children_of(self, parent_id: int | None = None) -> tuple[Playlist, ...]:
        return self._children.get(parent_id, ())

    def tracks_for(self, playlist_id: int) -> tuple[Track, ...]:
        """Preserve Playlist occurrences; a folder combines unique descendant Tracks."""

        playlist = self._require(playlist_id)
        if playlist.kind != PlaylistKind.FOLDER:
            return self._resolve_tracks(playlist.track_ids)
        result: list[Track] = []
        seen_tracks: set[int] = set()
        visited: set[int] = set()
        pending = [playlist]
        while pending:
            current = pending.pop()
            if current.playlist_id in visited:
                continue
            visited.add(current.playlist_id)
            if current.kind == PlaylistKind.FOLDER:
                pending.extend(reversed(self.children_of(current.playlist_id)))
            else:
                for track in self._resolve_tracks(current.track_ids):
                    if track.track_id not in seen_tracks:
                        seen_tracks.add(track.track_id)
                        result.append(track)
        return tuple(result)

    def create(
        self,
        kind: PlaylistKind,
        name: str,
        parent_id: int | None = None,
        *,
        smart: SmartPlaylist | None = None,
        description: str = "",
        track_ids: tuple[int, ...] = (),
        sort_order: PlaylistSort | None = None,
    ) -> Playlist:
        self._require_editable()
        self._require_snapshot()
        name = self._validate_name(name)
        self._validate_parent(parent_id)
        if kind not in tuple(PlaylistKind):
            raise ValueError("Choose a Playlist, Smart Playlist, or Playlist Folder.")
        if kind != PlaylistKind.SMART and smart is not None:
            raise ValueError("Only a Smart Playlist can have rules.")
        if track_ids and (
            kind is not PlaylistKind.PLAYLIST
            or any(i not in self._tracks for i in track_ids)
        ):
            raise ValueError("Choose current Tracks for a regular Playlist.")
        if kind == PlaylistKind.SMART:
            smart = SmartPlaylist() if smart is None else smart
        entries = (
            playlist_entries(track_ids)
            if smart is None
            else playlist_entries(t.track_id for t in self.preview(smart))
        )
        while self._next_id in self._playlists:
            self._next_id -= 1
        if kind is PlaylistKind.FOLDER:
            resolved_sort_order: PlaylistSort = PlaylistSortOrder.DEFAULT
        else:
            resolved_sort_order = (
                PlaylistSortOrder.MANUAL if sort_order is None else sort_order
            )
        entries = order_playlist_entries(entries, self.tracks, resolved_sort_order)
        playlist = Playlist(
            playlist_id=self._next_id,
            name=name,
            kind=kind,
            parent_id=parent_id,
            smart=smart,
            description=description,
            entries=entries,
            sort_order=resolved_sort_order,
        )
        self._next_id -= 1
        self._playlists[playlist.playlist_id] = playlist
        self._publish()
        return playlist

    def update(
        self,
        playlist_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        smart: SmartPlaylist | None = None,
        sort_order: PlaylistSort | None = None,
    ) -> Playlist:
        """Apply changed rules and their saved matches as one reversible edit."""

        self._require_editable()
        playlist = self._require(playlist_id)
        updated = replace(
            playlist,
            name=playlist.name if name is None else self._validate_name(name),
            description=playlist.description if description is None else description,
            sort_order=playlist.sort_order if sort_order is None else sort_order,
        )
        membership_changed = False
        if smart is not None:
            if playlist.kind != PlaylistKind.SMART:
                raise ValueError("Only a Smart Playlist can have rules.")
            if playlist.smart is not None:
                try:
                    validate_smart_playlist(playlist.smart)
                except ValueError:
                    raise ValueError(
                        "These Smart Playlist rules are read-only."
                    ) from None
            if smart != playlist.smart:
                membership_changed = True
                updated = replace(
                    updated,
                    smart=smart,
                    entries=playlist_entries(
                        (
                            t.track_id
                            for t in self.preview(
                                smart, current_playlist_id=playlist.playlist_id
                            )
                        ),
                        playlist.entries,
                    ),
                )
        if membership_changed or updated.sort_order != playlist.sort_order:
            updated = replace(
                updated,
                entries=order_playlist_entries(
                    updated.entries,
                    self.tracks,
                    updated.sort_order,
                ),
            )
        return self._replace(updated)

    def rename(self, playlist_id: int, name: str) -> Playlist:
        return self.update(playlist_id, name=name)

    def edit_smart(self, playlist_id: int, smart: SmartPlaylist) -> Playlist:
        return self.update(playlist_id, smart=smart)

    def evaluate_smart(self, playlist_id: int) -> Playlist:
        """Refresh one supported Smart Playlist's saved membership in the draft."""

        self._require_editable()
        playlist = self._require(playlist_id)
        if playlist.kind is not PlaylistKind.SMART or playlist.smart is None:
            raise ValueError("Only a Smart Playlist can be evaluated.")
        matches = self.preview(
            playlist.smart,
            current_playlist_id=playlist.playlist_id,
        )
        entries = playlist_entries(
            (track.track_id for track in matches),
            playlist.entries,
        )
        return self._replace(
            replace(
                playlist,
                entries=order_playlist_entries(
                    entries,
                    self.tracks,
                    playlist.sort_order,
                ),
            )
        )

    def remove_playlist(self, playlist_id: int, expected: EditRevision) -> Playlist:
        """Remove one user Playlist, including every descendant of a folder."""

        self.require_revision(expected)
        playlist = self._require(playlist_id)
        if playlist.system_managed:
            raise ValueError(
                "This Playlist is managed by the iPod and cannot be removed."
            )
        removed_ids = {playlist_id}
        if playlist.kind is PlaylistKind.FOLDER:
            pending = [playlist_id]
            while pending:
                parent_id = pending.pop()
                for child in self.children_of(parent_id):
                    if child.playlist_id not in removed_ids:
                        removed_ids.add(child.playlist_id)
                        pending.append(child.playlist_id)
        self._playlists = {
            item_id: item
            for item_id, item in self._playlists.items()
            if item_id not in removed_ids
        }
        snapshot = self._require_snapshot()
        if any(item.playlist_id in removed_ids for item in snapshot.playlists):
            self._delete_omissions = True
        self._publish()
        return playlist

    def set_tracks(self, playlist_id: int, track_ids: tuple[int, ...]) -> Playlist:
        self._require_editable()
        playlist = self._require(playlist_id)
        if playlist.kind != PlaylistKind.PLAYLIST:
            raise ValueError("Tracks can be arranged directly only in a Playlist.")
        if any(track_id not in self._tracks for track_id in track_ids):
            raise ValueError("A selected Track is no longer in this Library.")
        entries = playlist_entries(track_ids, playlist.entries)
        return self._replace(
            replace(
                playlist,
                entries=order_playlist_entries(
                    entries,
                    self.tracks,
                    playlist.sort_order,
                ),
            )
        )

    def edit_entries(
        self,
        playlist_id: int,
        entry_ids: tuple[str, ...],
        action: str,
        expected: EditRevision,
    ) -> None:
        """Remove or move exact occurrences, including duplicate Tracks."""
        self.require_revision(expected)
        playlist = self._require(playlist_id)
        if playlist.kind is not PlaylistKind.PLAYLIST:
            raise ValueError("Only regular Playlists allow membership edits.")
        selected = frozenset(entry_ids)
        if not selected or not selected <= {e.entry_id for e in playlist.entries}:
            raise ValueError("The selected Playlist entries are no longer available.")
        entries = list(playlist.entries)
        if action == "remove":
            entries = [e for e in entries if e.entry_id not in selected]
        elif action in ("up", "down"):
            if playlist.sort_order not in (
                PlaylistSortOrder.DEFAULT,
                PlaylistSortOrder.MANUAL,
            ):
                raise ValueError(
                    "Choose Manual Playlist sort order before moving entries."
                )
            if action == "down":
                entries.reverse()
            for i in range(1, len(entries)):
                if (
                    entries[i].entry_id in selected
                    and entries[i - 1].entry_id not in selected
                ):
                    entries[i - 1], entries[i] = entries[i], entries[i - 1]
            if action == "down":
                entries.reverse()
        else:
            raise ValueError("Choose Remove, Move Up, or Move Down.")
        self._replace(
            replace(
                playlist,
                entries=order_playlist_entries(
                    tuple(entries),
                    self.tracks,
                    playlist.sort_order,
                ),
            )
        )

    def can_move(self, playlist_id: int, parent_id: int | None) -> bool:
        if self._locked or playlist_id not in self._playlists:
            return False
        current_id = parent_id
        visited: set[int] = set()
        while current_id is not None:
            if current_id == playlist_id or current_id in visited:
                return False
            current = self._playlists.get(current_id)
            if current is None or current.kind != PlaylistKind.FOLDER:
                return False
            visited.add(current_id)
            current_id = current.parent_id
        return True

    def move(self, playlist_id: int, parent_id: int | None) -> bool:
        self._require_editable()
        playlist = self._require(playlist_id)
        if not self.can_move(playlist_id, parent_id):
            raise ValueError("Choose a folder outside this Playlist's own contents.")
        if playlist.parent_id == parent_id:
            return False
        self._replace(replace(playlist, parent_id=parent_id))
        return True

    def preview(
        self,
        smart: SmartPlaylist,
        *,
        current_playlist_id: int | None = None,
    ) -> tuple[Track, ...]:
        self._require_snapshot()
        if current_playlist_id in smart_playlist_references(smart):
            raise ValueError(
                "A Smart Playlist cannot use its own saved membership as a rule."
            )
        return preview_smart_playlist(self.tracks, smart, playlists=self.playlists)

    def reset_changes(self) -> None:
        if self._locked:
            return
        snapshot = self._snapshot
        if snapshot is None or not self.dirty:
            return
        self._playlists = {
            playlist.playlist_id: playlist for playlist in snapshot.playlists
        }
        self._tracks = {track.track_id: track for track in snapshot.tracks}
        self._artwork_assets.clear()
        self._media_sources.clear()
        self._delete_omissions = False
        self._device_name = snapshot.device_name
        self._photos = snapshot.photos
        self._publish()
        self.tracksChanged.emit(self.tracks)
        self.photosChanged.emit(self._photos)

    def _require_snapshot(self) -> LibrarySnapshot:
        if self._snapshot is None:
            raise ValueError("Select an iPod before changing the Library.")
        return self._snapshot

    def _require_photos(self) -> PhotoLibrary:
        self._require_snapshot()
        if self._photos is None:
            raise ValueError("This Library has no loaded Photo Database.")
        return self._photos

    @staticmethod
    def _validate_photo_album_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Enter a name for the Photo Album.")
        try:
            name.encode("utf-16-le")
        except UnicodeEncodeError:
            raise ValueError(
                "The Photo Album name contains an invalid Unicode character."
            ) from None
        if "\x00" in name:
            raise ValueError("The Photo Album name cannot contain a null character.")
        return name

    def _require(self, playlist_id: int) -> Playlist:
        self._require_snapshot()
        playlist = self._playlists.get(playlist_id)
        if playlist is None:
            raise ValueError("This Playlist is no longer in the Library.")
        return playlist

    @staticmethod
    def _validate_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Enter a name for the Playlist.")
        return name

    def _validate_parent(self, parent_id: int | None) -> None:
        if parent_id is not None:
            parent = self._require(parent_id)
            if parent.kind != PlaylistKind.FOLDER:
                raise ValueError("Only a Playlist Folder can contain Playlists.")

    def _replace(self, playlist: Playlist) -> Playlist:
        if playlist != self._playlists[playlist.playlist_id]:
            self._playlists[playlist.playlist_id] = playlist
            self._publish()
        return playlist

    def _refresh_field_sorted_playlists(self) -> None:
        """Keep saved order coherent when an edited Track changes a sort key."""

        for playlist_id, playlist in tuple(self._playlists.items()):
            # Firmware grouping and native episode positions belong to iPodDB.
            # Even an unrelated Track edit must leave this retained Playlist alone.
            if playlist.system_managed:
                continue
            if not isinstance(playlist.sort_order, PlaylistSortOrder) or (
                playlist.sort_order
                in (PlaylistSortOrder.DEFAULT, PlaylistSortOrder.MANUAL)
            ):
                continue
            self._playlists[playlist_id] = replace(
                playlist,
                entries=order_playlist_entries(
                    playlist.entries,
                    self.tracks,
                    playlist.sort_order,
                ),
            )

    def _resolve_tracks(self, track_ids: tuple[int, ...]) -> tuple[Track, ...]:
        return tuple(
            track
            for track_id in track_ids
            if (track := self._tracks.get(track_id)) is not None
        )

    def _publish(self) -> None:
        self._revision += 1
        children: dict[int | None, list[Playlist]] = {}
        for playlist in self._playlists.values():
            children.setdefault(playlist.parent_id, []).append(playlist)
        self._children = {
            parent_id: tuple(items) for parent_id, items in children.items()
        }
        self.changed.emit()
