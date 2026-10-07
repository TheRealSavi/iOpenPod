"""Capture device dependencies and compose one reviewed Library transaction."""

from __future__ import annotations

import logging
import re
from contextlib import ExitStack
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING

from iOpenPod.app.artwork_policy import rockbox_artwork
from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.library_write import LibraryFileChange
from iOpenPod.app.media.lyrics import rewrite_lyrics_stream
from iOpenPod.app.services import volume_presentation
from iPodDB.library import (
    MAX_SIDECAR_BYTES,
    FileContentData,
    FileDependency,
    PhotoRepresentationKind,
    PlaybackSidecar,
    PreparedLyrics,
    SourceFile,
    WriteIssue,
    WriteResources,
    content_sha256,
    is_playback_sidecar,
    remap_playback_sidecar,
)
from storage import (
    DeviceEntryKind,
    DevicePath,
    FileContent,
    FilePrecondition,
    FilePreconditionError,
    HostPath,
    StorageError,
    StorageTransaction,
    TransactionRemoval,
    TransactionWrite,
)
from storage.content_workspace import ContentWorkspace, StagedContent, content_workspace
from storage.host_input import LocalHostFile
from storage.media_processing import media_workspace

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_write import LibraryPreparationRequest
    from iPodDB.library import ArtworkPixels, LibraryWritePlan, PreparedLibrary
    from storage import FilesystemSession

logger = logging.getLogger(__name__)
ITUNESDB = DevicePath("iPod_Control/iTunes/iTunesDB")
ITUNESCDB = DevicePath("iPod_Control/iTunes/iTunesCDB")
ARTWORKDB = DevicePath("iPod_Control/Artwork/ArtworkDB")
PHOTOSDB = DevicePath("Photos/Photo Database")
_ARTWORK = DevicePath("iPod_Control/Artwork")
_ITUNES = DevicePath("iPod_Control/iTunes")
_MUSIC = DevicePath("iPod_Control/Music")
_PHOTO_FULL_RESOLUTION = DevicePath("Photos/Full Resolution")
_PHOTO_THUMBNAILS = DevicePath("Photos/Thumbs")
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024 * 1024
_SQLITE_DIRECTORY = "iPod_Control/iTunes/iTunes Library.itlp"
SQLITE_DATABASE_PATHS = tuple(
    DevicePath(f"{_SQLITE_DIRECTORY}/{name}")
    for name in (
        "Library.itdb",
        "Locations.itdb",
        "Dynamic.itdb",
        "Extras.itdb",
        "Genius.itdb",
        "Locations.itdb.cbk",
    )
)


def database_path(database_name: str) -> DevicePath:
    if database_name == "iTunesDB":
        return ITUNESDB
    if database_name == "iTunesCDB":
        return ITUNESCDB
    raise ValueError(f"Unsupported Library database name: {database_name}")


def sqlite_database_path(artifact_name: str) -> DevicePath:
    """Map an iPodDB SQLite artifact name into the device namespace."""

    path = DevicePath(f"{_SQLITE_DIRECTORY}/{artifact_name}")
    if path not in SQLITE_DATABASE_PATHS:
        raise ValueError(f"Unsupported SQLite Library artifact: {artifact_name}")
    return path


@dataclass(frozen=True, slots=True)
class CapturedLibraryResources:
    resources: WriteResources
    files: tuple[FilePrecondition, ...]
    removals: tuple[TransactionRemoval, ...]
    media_writes: tuple[TransactionWrite, ...] = ()
    presentation_writes: tuple[TransactionWrite, ...] = ()
    issues: tuple[WriteIssue, ...] = ()


def pending_sidecars(
    session: FilesystemSession, preserved: tuple[DevicePath, ...] = ()
) -> bool:
    return any(
        _is_pending_sidecar(entry.path) and entry.path not in preserved
        for entry in session.list_directory(_ITUNES)
    )


def _is_pending_sidecar(path: DevicePath) -> bool:
    return is_playback_sidecar(path.name)


def load_sidecars(
    session: FilesystemSession,
) -> tuple[tuple[PlaybackSidecar, ...], tuple[FilePrecondition, ...]]:
    """Capture a bounded firmware inventory alongside the source Library."""
    sidecars: list[PlaybackSidecar] = []
    files: list[FilePrecondition] = []
    total = 0
    for entry in session.list_directory(_ITUNES):
        if not _is_pending_sidecar(entry.path):
            continue
        if len(sidecars) >= 256:
            raise ValueError("Too many playback sidecar files to capture safely.")
        snapshot = session.read_snapshot(entry.path, max_bytes=MAX_SIDECAR_BYTES)
        total += len(snapshot.data)
        if total > 64 * 1024 * 1024:
            raise ValueError("Playback sidecars exceed the total capture limit.")
        sidecars.append(PlaybackSidecar(entry.path.name, snapshot.data))
        files.append(FilePrecondition(entry.path, snapshot.fingerprint))
    recheck(session, tuple(files))
    if pending_sidecars(session, tuple(file.path for file in files)):
        raise FilePreconditionError(
            "Playback sidecars changed while loading. Reload the iPod."
        )
    return tuple(sidecars), tuple(files)


def _capture_sidecars(
    session: FilesystemSession,
    request: LibraryPreparationRequest,
    checkpoint: Callable[[], None],
    consumed: tuple[PlaybackSidecar, ...],
    loaded: tuple[FilePrecondition, ...],
) -> tuple[
    tuple[FilePrecondition, ...],
    tuple[TransactionWrite, ...],
    tuple[TransactionRemoval, ...],
]:
    original = tuple(t.track_id for t in request.source.library.tracks)
    desired = tuple(t.track_id for t in request.snapshot.tracks)
    files: list[FilePrecondition] = []
    writes: list[TransactionWrite] = []
    removals: list[TransactionRemoval] = []
    expected = {item.name.casefold(): item for item in consumed}
    found: set[str] = set()
    loaded_paths = {file.path for file in loaded}
    for entry in session.list_directory(_ITUNES):
        if not _is_pending_sidecar(entry.path):
            continue
        if consumed and entry.path not in loaded_paths:
            raise FilePreconditionError(
                "Playback sidecars appeared after loading; reload before reconciling them."
            )
        checkpoint()
        snapshot = session.read_snapshot(entry.path, max_bytes=16 * 1024 * 1024)
        name = entry.path.name.casefold()
        if name in expected:
            if snapshot.data != expected[name].data:
                raise FilePreconditionError(
                    f"{entry.path.name} changed after loading; reload the iPod."
                )
            found.add(name)
            backup = DevicePath(f"{_ITUNES}/{entry.path.name}.bak")
            prior = session.fingerprint(backup) if session.exists(backup) else None
            files.extend(
                (
                    FilePrecondition(entry.path, snapshot.fingerprint),
                    FilePrecondition(backup, prior),
                )
            )
            writes.append(
                TransactionWrite(backup, snapshot.data, _content(snapshot.data), prior)
            )
            removals.append(TransactionRemoval(entry.path, snapshot.fingerprint))
            continue
        if name == "play counts" or re.fullmatch(r"otgplaylistinfo(?:_[0-9]+)?", name):
            try:
                output = remap_playback_sidecar(snapshot.data, original, desired)
            except ValueError as error:
                raise ValueError(
                    f"Could not preserve {entry.path.name}: {error}"
                ) from error
        elif desired[: len(original)] == original:
            # Appending new Tracks leaves every existing positional reference intact.
            output = snapshot.data
        else:
            raise ValueError(
                f"{entry.path.name} has an unsupported playback format. Existing Track positions must be retained to preserve it."
            )
        files.append(FilePrecondition(entry.path, snapshot.fingerprint))
        if output != snapshot.data:
            writes.append(
                TransactionWrite(
                    entry.path, output, _content(output), snapshot.fingerprint
                )
            )
    if found != expected.keys():
        raise FilePreconditionError(
            "A loaded playback sidecar disappeared; reload the iPod."
        )
    return tuple(files), tuple(writes), tuple(removals)


def recheck(session: FilesystemSession, files: tuple[FilePrecondition, ...]) -> None:
    for file in files:
        actual = session.fingerprint(file.path) if session.exists(file.path) else None
        if actual != file.fingerprint:
            raise FilePreconditionError(
                f"Captured Library resource changed: {file.path}"
            )


def capture(
    session: FilesystemSession,
    request: LibraryPreparationRequest,
    plan: LibraryWritePlan,
    checkpoint: Callable[[], None],
    *,
    temporary_files: ExitStack,
    additional_preconditions: tuple[FilePrecondition, ...] = (),
    volume_presentation_enabled: bool = True,
    consumed_sidecars: tuple[PlaybackSidecar, ...] = (),
    loaded_sidecars: tuple[FilePrecondition, ...] = (),
) -> CapturedLibraryResources:
    primary = database_path(request.source.database_name)
    files = [
        FilePrecondition(primary, request.source.database_fingerprint),
        FilePrecondition(ARTWORKDB, request.source.artwork_database_fingerprint),
        FilePrecondition(PHOTOSDB, request.source.photos_database_fingerprint),
        *additional_preconditions,
    ]
    if plan.target.sqlite_database and plan.changes_itunes:
        files.extend(
            FilePrecondition(
                path,
                session.fingerprint(path) if session.exists(path) else None,
            )
            for path in SQLITE_DATABASE_PATHS
        )
    if primary == ITUNESCDB and plan.changes_itunes:
        files.append(
            FilePrecondition(
                ITUNESDB,
                session.fingerprint(ITUNESDB) if session.exists(ITUNESDB) else None,
            )
        )
    inventory: list[FileDependency] = []
    staging = temporary_files.enter_context(
        content_workspace(memory_budget=_MAX_CAPTURE_BYTES, checkpoint=checkpoint)
    )
    sources: list[SourceFile] = []
    media_writes: list[TransactionWrite] = []
    sidecar_removals: tuple[TransactionRemoval, ...] = ()
    presentation_writes: tuple[TransactionWrite, ...] = ()
    if (
        volume_presentation_enabled
        and request.snapshot.device_name != request.source.library.device_name
    ):
        presentation = volume_presentation.capture(
            session, request.snapshot.device_name, request.source.profile.product_image
        )
        files.extend(presentation.files)
        presentation_writes = presentation.writes
    if plan.requires_sidecar_inventory:
        sidecar_files, sidecar_writes, sidecar_removals = _capture_sidecars(
            session, request, checkpoint, consumed_sidecars, loaded_sidecars
        )
        files.extend(sidecar_files)
        media_writes.extend(sidecar_writes)
    if len({m.media.track_id for m in request.media}) != len(request.media):
        raise ValueError("Incoming media repeats a Track identity.")
    for incoming in request.media:
        checkpoint()
        media_file = incoming.media.file
        path = DevicePath(media_file.relative_path)
        if (
            incoming.media.track_id not in plan.required_media
            or not path.is_relative_to(_MUSIC)
        ):
            raise ValueError(
                "Incoming media is unrequested or outside iPod_Control/Music."
            )
        if (incoming.fingerprint.size, incoming.fingerprint.sha256) != (
            media_file.size,
            media_file.sha256,
        ):
            raise ValueError(
                "Incoming media facts differ from the captured source content."
            )
        if session.exists(path):
            raise ValueError(f"Incoming media destination already exists: {path}")
        # An absence precondition prevents a later file from being overwritten.
        files.append(FilePrecondition(path, None))
        media_writes.append(
            TransactionWrite(
                path, incoming.source, FileContent(media_file.size, media_file.sha256)
            )
        )
    if len({asset.photo.photo_id for asset in request.photos}) != len(request.photos):
        raise ValueError("Incoming Photos repeat a Photo identity.")
    incoming_photo_paths: set[DevicePath] = set()
    for asset in request.photos:
        if asset.photo.photo_id not in plan.required_photos:
            raise ValueError("Incoming Photo was not requested by the Library draft.")
        for photo_file in asset.files:
            checkpoint()
            dependency = photo_file.dependency
            path = DevicePath(dependency.relative_path)
            if not path.is_relative_to(_PHOTO_FULL_RESOLUTION) and not (
                path.is_relative_to(_PHOTO_THUMBNAILS)
                and re.fullmatch(r"F[1-9][0-9]*_[1-9][0-9]*\.ithmb", path.name)
            ):
                raise ValueError(
                    f"Incoming Photo is outside the supported Photo namespace: {path}"
                )
            if path in incoming_photo_paths or session.exists(path):
                raise ValueError(f"Incoming Photo destination is not unused: {path}")
            content = _content(photo_file.data)
            if (content.size, content.sha256) != (dependency.size, dependency.sha256):
                raise ValueError(
                    "Incoming Photo bytes do not match the captured content."
                )
            incoming_photo_paths.add(path)
            files.append(FilePrecondition(path, None))
            media_writes.append(
                TransactionWrite(path, _transaction_source(photo_file.data), content)
            )
    cover_prefixes = tuple(f"f{f.format_id}_" for f in plan.target.cover_formats)
    if plan.requires_artwork_inventory and session.exists(_ARTWORK):
        for entry in session.list_directory(_ARTWORK):
            if entry.path.name.startswith(
                "._"
            ) or not entry.path.name.casefold().endswith(".ithmb"):
                # AppleDouble companions belong to the host filesystem. macOS
                # may replace them when we publish their corresponding artwork.
                # They are neither thumbnail payloads nor Library dependencies.
                continue
            checkpoint()
            if entry.kind is not DeviceEntryKind.FILE:
                raise ValueError(
                    f"Artwork resource is not a regular file: {entry.path}"
                )
            # Encoding appends to existing prefixes. Reference-only edits need
            # their fingerprints and sizes, without retaining all thumbnail bytes.
            if (
                request.artwork
                and entry.path.name.casefold().startswith(cover_prefixes)
                and entry.size < plan.target.max_artwork_file_bytes
            ):
                fingerprint = session.fingerprint(entry.path)
                try:
                    data, content = staging.capture_device(session, entry.path)
                except StorageError as error:
                    raise StorageError(
                        f"Could not capture artwork file {entry.path}: {error}"
                    ) from error
                except OSError as error:
                    raise OSError(
                        f"Could not capture artwork file {entry.path}: {error}"
                    ) from error
                if content != FileContent.from_fingerprint(fingerprint):
                    raise FilePreconditionError(
                        f"Artwork file changed during capture: {entry.path}"
                    )
                dependency = FileDependency(
                    str(entry.path), fingerprint.size, fingerprint.sha256
                )
                sources.append(SourceFile(dependency, data))
            else:
                fingerprint = session.fingerprint(entry.path)
                dependency = FileDependency(
                    str(entry.path), fingerprint.size, fingerprint.sha256
                )
            files.append(FilePrecondition(entry.path, fingerprint))
            inventory.append(dependency)
    lyrics, lyric_writes, lyric_issues = _capture_file_tags(
        session,
        request,
        plan,
        checkpoint,
        temporary_files,
        staging=staging,
        file_preconditions=files,
    )
    tagged = {item.track_id: item for item in lyrics}
    media = tuple(
        replace(m.media, file=tagged[m.media.track_id].file)
        if m.media.track_id in tagged
        else m.media
        for m in request.media
    )
    tagged_paths = {write.path for write in lyric_writes}
    media_writes = [write for write in media_writes if write.path not in tagged_paths]
    media_writes.extend(lyric_writes)
    files.extend(
        FilePrecondition(w.path, w.expected)
        for w in lyric_writes
        if w.expected is not None
    )
    retained = {
        t.metadata.location.casefold()
        for t in request.snapshot.tracks
        if t.metadata.location
    }
    desired_ids = {t.track_id for t in request.snapshot.tracks}
    removed_paths: set[str] = set()
    removals: list[TransactionRemoval] = list(sidecar_removals)
    for track in request.source.library.tracks:
        location = track.metadata.location
        if (
            (
                track.track_id in desired_ids
                and track.track_id not in request.replace_media
            )
            or not location
            or location.casefold() in retained
            or location.casefold() in removed_paths
        ):
            continue
        checkpoint()
        path = DevicePath(location)
        if not path.is_relative_to(_MUSIC):
            raise ValueError(f"Removed media is outside iPod_Control/Music: {path}")
        media_fingerprint = session.fingerprint(path) if session.exists(path) else None
        files.append(FilePrecondition(path, media_fingerprint))
        if media_fingerprint is not None:
            removals.append(TransactionRemoval(path, media_fingerprint))
        removed_paths.add(location.casefold())
    source_photos = request.source.library.photos
    desired_photos = request.snapshot.photos
    if source_photos is not None and desired_photos is not None:
        desired_photo_ids = {photo.photo_id for photo in desired_photos.photos}
        retained_photo_paths = {
            representation.relative_path.casefold()
            for photo in desired_photos.photos
            for representation in photo.representations
            if representation.relative_path
        }
        removed_photo_paths: set[str] = set()
        for photo in source_photos.photos:
            if (
                photo.photo_id in desired_photo_ids
                and photo.photo_id not in request.replace_photos
            ):
                continue
            for representation in photo.representations:
                if not representation.relative_path:
                    continue
                normalized = representation.relative_path.casefold()
                if (
                    normalized in retained_photo_paths
                    or normalized in removed_photo_paths
                ):
                    continue
                checkpoint()
                path = DevicePath(representation.relative_path)
                allowed_root = (
                    _PHOTO_FULL_RESOLUTION
                    if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
                    else _PHOTO_THUMBNAILS
                )
                if len(path.parts) <= len(allowed_root.parts) or tuple(
                    part.casefold() for part in path.parts[: len(allowed_root.parts)]
                ) != tuple(part.casefold() for part in allowed_root.parts):
                    raise ValueError(
                        f"Removed Photo representation is outside its allowed namespace: {path}"
                    )
                if (
                    representation.kind is PhotoRepresentationKind.THUMBNAIL
                    and not re.fullmatch(
                        r"F[1-9][0-9]*_[1-9][0-9]*\.ithmb", path.name, re.IGNORECASE
                    )
                ):
                    raise ValueError(
                        f"Removed thumbnail does not use an expected iTHMB filename: {path}"
                    )
                photo_fingerprint = (
                    session.fingerprint(path) if session.exists(path) else None
                )
                files.append(FilePrecondition(path, photo_fingerprint))
                if photo_fingerprint is not None:
                    removals.append(TransactionRemoval(path, photo_fingerprint))
                removed_photo_paths.add(normalized)
    recheck(session, tuple(files))
    resources = WriteResources(
        media=media,
        lyrics=lyrics,
        artwork=request.artwork,
        photos=request.photos,
        files=tuple(sources),
        file_inventory=tuple(inventory) if plan.requires_artwork_inventory else None,
        pending_playback_sidecars=False if plan.requires_sidecar_inventory else None,
        create_file_buffer=staging.new_buffer,
    )
    logger.debug(
        "Captured Library resources files=%d artwork_bytes=%d removals=%d",
        len(files),
        sum(len(source.data) for source in sources if isinstance(source.data, bytes)),
        len(removals),
    )
    return CapturedLibraryResources(
        resources,
        tuple(files),
        tuple(removals),
        tuple(media_writes),
        presentation_writes,
        lyric_issues,
    )


def _capture_file_tags(
    session: FilesystemSession,
    request: LibraryPreparationRequest,
    plan: LibraryWritePlan,
    checkpoint: Callable[[], None],
    temporary_files: ExitStack,
    *,
    staging: ContentWorkspace,
    file_preconditions: list[FilePrecondition],
) -> tuple[
    tuple[PreparedLyrics, ...], tuple[TransactionWrite, ...], tuple[WriteIssue, ...]
]:
    if plan.blocked or not plan.required_lyrics:
        return (), (), ()
    desired = {t.track_id: t for t in request.snapshot.tracks}
    original = {t.track_id: t for t in request.source.library.tracks}
    incoming = {m.media.track_id: m for m in request.media}
    owners_by_path: dict[str, set[int]] = {}
    for track in (*request.source.library.tracks, *request.snapshot.tracks):
        owners_by_path.setdefault(track.metadata.location.casefold(), set()).add(
            track.track_id
        )
    rockbox = {update.track_id: update for update in request.rockbox_media}
    if len(rockbox) != len(request.rockbox_media) or not rockbox.keys() <= set(
        plan.required_lyrics
    ):
        raise ValueError(
            "Rockbox tag updates must be unique and requested by the Library plan."
        )
    lyrics: list[PreparedLyrics] = []
    writes: list[TransactionWrite] = []
    issues: list[WriteIssue] = []
    covers: dict[int, ArtworkPixels] = {}
    artwork_files = {file.path: file.fingerprint for file in file_preconditions}
    for identity in plan.required_lyrics:
        checkpoint()
        track = desired[identity]
        path = DevicePath(track.metadata.location)
        if not path.is_relative_to(_MUSIC) or len(path.parts) <= len(_MUSIC.parts):
            raise ValueError(f"Lyrics media is outside iPod_Control/Music: {path}")
        if owners_by_path.get(str(path).casefold()) != {identity}:
            raise ValueError(
                f"Lyrics cannot change a media file shared by multiple Tracks: {path}"
            )
        selected = incoming.get(identity)
        expected = None
        remaining = staging.remaining_bytes
        source_name = (
            selected.display_path or str(selected.source)
            if selected is not None
            else str(path)
        )
        try:
            with ExitStack() as owned:
                workspace = owned.enter_context(media_workspace(checkpoint=checkpoint))
                if selected is not None:
                    captured = workspace.capture(
                        selected.source, expected=selected.fingerprint
                    )
                    private_source = captured.snapshot
                else:
                    prior = original.get(identity)
                    if (
                        prior is None
                        or prior.metadata.location != track.metadata.location
                    ):
                        raise ValueError(
                            "Lyrics require captured media at the retained Track location."
                        )
                    expected = session.fingerprint(path)
                    private_source = workspace.output_path(".media")
                    copied = session.copy_to_host(
                        path, private_source, progress=lambda _copied: checkpoint()
                    )
                    if (copied.bytes_copied, copied.sha256) != (
                        expected.size,
                        expected.sha256,
                    ):
                        raise FilePreconditionError(
                            "Lyrics media changed during capture."
                        )
                update = rockbox.get(identity)
                artwork = update.artwork if update is not None else None
                if update is not None and update.artwork_read is not None:
                    if track.artwork_id not in covers:
                        read = update.artwork_read
                        cover_path = DevicePath(read.relative_path)
                        if (
                            not cover_path.is_relative_to(_ARTWORK)
                            or not 0 < read.length <= 32 * 1024 * 1024
                        ):
                            raise ValueError(
                                "The selected artwork declares an unsafe file range."
                            )
                        if cover_path not in artwork_files:
                            fingerprint = session.fingerprint(cover_path)
                            artwork_files[cover_path] = fingerprint
                            file_preconditions.append(
                                FilePrecondition(cover_path, fingerprint)
                            )
                        pixels = read.decode(
                            session.read_range(
                                cover_path, offset=read.offset, length=read.length
                            )
                        )
                        covers[track.artwork_id] = rockbox_artwork(
                            request.source.profile, pixels
                        )
                    artwork = covers[track.artwork_id]
                transform = (
                    partial(
                        rewrite_lyrics_stream,
                        file_name=str(path),
                        lyrics=track.metadata.lyrics,
                    )
                    if update is None
                    else partial(
                        ExportMediaTagger().prepare_stream,
                        file_name=str(path),
                        track=track,
                        artwork=artwork,
                        preserve_artwork=update.preserve_artwork,
                    )
                )
                output = workspace.transform_stream(private_source, transform)
                content = FileContent.from_fingerprint(output.fingerprint)
                if content.size <= remaining:
                    payload = LocalHostFile.observe(output.snapshot).read_bytes(
                        max_bytes=remaining, checkpoint=checkpoint
                    )
                    retained = staging.store(payload)
                    writes.append(
                        TransactionWrite(
                            path, _transaction_source(retained), content, expected
                        )
                    )
                else:
                    writes.append(
                        TransactionWrite(path, output.snapshot, content, expected)
                    )
                    temporary_files.enter_context(owned.pop_all())
        except StorageError as error:
            raise StorageError(
                f'Could not prepare lyrics for "{source_name}" (iPod file: {path}): {error}'
            ) from error
        except (ValueError, OSError) as error:
            raise ValueError(
                f'Could not prepare lyrics for "{source_name}" (iPod file: {path}): {error}'
            ) from error
        lyrics.append(
            PreparedLyrics(
                identity,
                track.metadata.lyrics,
                FileDependency(str(path), content.size, content.sha256),
            )
        )
    return tuple(lyrics), tuple(writes), tuple(issues)


def transaction(
    session: FilesystemSession,
    captured: CapturedLibraryResources,
    prepared: PreparedLibrary,
    original_itunes: bytes,
    original_artwork: bytes | None,
    original_photos: bytes | None,
    *,
    primary_database: DevicePath = ITUNESDB,
    allow_unchanged: bool = False,
) -> StorageTransaction | None:
    before = {f.path: f.fingerprint for f in captured.files}
    writes: list[TransactionWrite] = list(captured.media_writes)
    for file in prepared.artwork_files:
        path = DevicePath(file.relative_path)
        if not path.is_relative_to(_ARTWORK) or not path.name.casefold().endswith(
            ".ithmb"
        ):
            raise ValueError(
                f"Prepared artwork is outside its allowed namespace: {path}"
            )
        writes.append(
            TransactionWrite(
                path,
                _transaction_source(file.data),
                _content(file.data),
                before.get(path),
            )
        )
    if prepared.artwork != original_artwork:
        if prepared.artwork is None:
            raise ValueError("A Library save cannot discard the retained ArtworkDB")
        writes.append(
            TransactionWrite(
                ARTWORKDB,
                prepared.artwork,
                _content(prepared.artwork),
                before[ARTWORKDB],
            )
        )
    if prepared.photos != original_photos:
        if prepared.photos is None:
            raise ValueError("A Library save cannot discard the retained PhotosDB")
        writes.append(
            TransactionWrite(
                PHOTOSDB,
                prepared.photos,
                _content(prepared.photos),
                before[PHOTOSDB],
            )
        )
    if prepared.itunes != original_itunes:
        writes.append(
            TransactionWrite(
                primary_database,
                prepared.itunes,
                _content(prepared.itunes),
                before[primary_database],
            )
        )
        if primary_database == ITUNESCDB:
            writes.append(
                TransactionWrite(ITUNESDB, b"", _content(b""), before[ITUNESDB])
            )
    if prepared.sqlite is not None:
        for artifact_name, data in prepared.sqlite.artifacts():
            path = sqlite_database_path(artifact_name)
            writes.append(TransactionWrite(path, data, _content(data), before[path]))
    # Names follow the Library's publication, with icons before their text references.
    writes.extend(captured.presentation_writes)
    changed = {w.path for w in writes} | {r.path for r in captured.removals}
    # Prepared dependencies are content assertions, never authority to open a new path.
    for dependency in prepared.retained_files:
        path = DevicePath(dependency.relative_path)
        incoming = next((w for w in captured.media_writes if w.path == path), None)
        if incoming is not None:
            if (incoming.content.size, incoming.content.sha256) != (
                dependency.size,
                dependency.sha256,
            ):
                raise ValueError(
                    f"Prepared media differs from the captured transaction: {path}"
                )
            continue
        fingerprint = before.get(path)
        if fingerprint is None or (fingerprint.size, fingerprint.sha256) != (
            dependency.size,
            dependency.sha256,
        ):
            raise ValueError(f"Prepared dependency was not captured: {path}")
    if allow_unchanged and not writes and not captured.removals:
        # Sync may establish an association without changing Library bytes. Keep
        # dependency verification, but never invent an empty Storage transaction.
        return None
    plan = StorageTransaction(
        tuple(writes),
        captured.removals,
        tuple(f for f in captured.files if f.path not in changed),
    )
    session.validate_transaction(plan)
    return plan


def preparation_issues(
    captured: CapturedLibraryResources, prepared: PreparedLibrary | None
) -> tuple[WriteIssue, ...]:
    return captured.issues


def _content(data: FileContentData) -> FileContent:
    return FileContent(len(data), content_sha256(data))


def _transaction_source(data: FileContentData) -> bytes | HostPath:
    if isinstance(data, bytes):
        return data
    if isinstance(data, StagedContent):
        return data.path
    raise ValueError("Prepared content must belong to a Storage workspace.")


def describe(plan: StorageTransaction) -> tuple[LibraryFileChange, ...]:
    return (
        *(
            LibraryFileChange(str(w.path), "write", w.content.size, w.content.sha256)
            for w in plan.writes
        ),
        *(
            LibraryFileChange(str(r.path), "remove", r.expected.size, r.expected.sha256)
            for r in plan.removals
        ),
    )
