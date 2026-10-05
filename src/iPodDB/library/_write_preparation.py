"""Atomic candidate preparation, resource checks, and independent reparse verification."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import fields, replace
from time import perf_counter
from typing import TYPE_CHECKING, cast

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import (
    EMPTY_ARTWORK_INDEX,
    build_artwork_index,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader as ArtworkImageHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.cdb import ITunesCDB, compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.iTunesDB.writer.signature import (
    sign_hash58,
    sign_hash72,
    sign_hashab,
    verify_hash58,
    verify_hash72,
    verify_hashab,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library._artwork_verification import verify_artwork
from iPodDB.library._artwork_writing import reconcile_artwork, validated_path
from iPodDB.library._group_verification import verify_browse_groups
from iPodDB.library._lyrics_resources import validate_lyrics
from iPodDB.library._photo_projection import project_photos
from iPodDB.library._photo_resources import validate_photos
from iPodDB.library._photo_writing import reconcile_photos
from iPodDB.library._playlist_projection import project_playlists
from iPodDB.library._playlist_verification import verify_playlists
from iPodDB.library._projection import link_artwork, project_tracks
from iPodDB.library._reconcile import reconcile
from iPodDB.library._track_verification import verify_native_tracks
from iPodDB.library._write_logging import log_resources, log_result
from iPodDB.library._write_verification import retained_artwork, verify_relationships
from iPodDB.library.file_content import content_sha256
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import (
    IssueSeverity,
    LibraryWritePlan,
    LibraryWriteResult,
    MediaContent,
    PreparedFile,
    PreparedLibrary,
    WriteChecksum,
    WriteIssue,
    WriteMeasurement,
    WritePhase,
    WriteResources,
    WriteTarget,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader as PhotoHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.shared.errors import iPodDBWriteError
from iPodDB.SQLiteDB.database import build_sqlite_databases

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.ArtworkDB.shared.artwork_index import ArtworkIndex
    from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
    from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
    from iPodDB.library._resolved_write import ResolvedWrite
    from iPodDB.library.database import IPodLibrary
    from iPodDB.library.photos import PhotoAlbum
    from iPodDB.library.writing import (
        IdentityMapping,
        LibraryDraft,
        PreparedLyrics,
        PreparedMedia,
    )
    from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader as PhotosMhfdHeader
    from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def _blocked(issues: list[WriteIssue]) -> bool:
    return any(i.severity is IssueSeverity.ERROR for i in issues)


def _finalize_itunes(
    logical: bytes, target: WriteTarget, framing: ITunesCDB | None = None
) -> bytes:
    if (
        not target.compressed_database
        and framing is not None
        and (framing.stream_trailing_data or framing.file_trailing_data)
    ):
        raise ValueError("Converting iTunesCDB framing would discard Unknown Data.")
    data = (
        compress_iTunesCDB(logical, framing=framing)
        if target.compressed_database
        else logical
    )
    if target.checksum is WriteChecksum.HASH58:
        data = sign_hash58(data, target.firewire_guid)
        valid = verify_hash58(data, target.firewire_guid)
    elif target.checksum is WriteChecksum.HASH72:
        material = target.hash72_material
        if material is None:
            raise ValueError("HASH72 output requires retained signing material")
        data = sign_hash72(data, material.iv, material.random_part)
        valid = verify_hash72(data, material.iv, material.random_part)
    elif target.checksum is WriteChecksum.HASHAB:
        data = sign_hashab(data, target.firewire_guid)
        valid = verify_hashab(data, target.firewire_guid)
    elif target.checksum is WriteChecksum.NONE:
        valid = True
    else:
        raise ValueError(f"Unsupported checksum target: {target.checksum}")
    if not valid:
        raise ValueError("Prepared database signature failed verification.")
    return data


def _sqlite_smart_criteria(
    document: DatabaseDocument[MhbdHeader],
) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    for selection in document.find_chunks(MhypHeader):
        rules = next(
            (
                child
                for child in selection.chunk.children
                if isinstance(child.header, MhodHeader)
                and isinstance(child.payload, MhodSmartRulesPayload)
            ),
            None,
        )
        if rules is not None:
            body, _header = encode_mhod_body(
                cast("ParsedChunk[MhodHeader]", rules),
                MhodPayloadKind.SMART_RULES,
            )
            result[selection.chunk.header.playlist_id] = body
    return result


def _record_context(
    document: ParsedChunk[ChunkHeader], path: tuple[int, ...], artifact: str
) -> tuple[str, int | None]:
    context: tuple[str, int | None] = ("library", None)
    chunk = document
    for index in (*path, -1):
        header = chunk.header
        if artifact == "PhotosDB" and isinstance(header, PhotoHeader):
            context = ("photo", header.image_id)
        elif artifact == "PhotosDB" and isinstance(header, MhbaHeader):
            context = ("photo_album", header.album_id)
        elif isinstance(header, MhitHeader):
            context = ("track", header.track_id)
        elif isinstance(header, MhypHeader):
            context = ("playlist", header.playlist_id)
        elif isinstance(header, ArtworkImageHeader):
            context = ("artwork", header.image_id)
        if index < 0 or index >= len(chunk.children):
            break
        chunk = chunk.children[index]
    return context


class _ObserverError(Exception):
    def __init__(self, error: Exception) -> None:
        self.error = error


def prepare(
    source: IPodLibrary,
    document: DatabaseDocument[MhbdHeader],
    artwork: DatabaseDocument[MhfdHeader] | None,
    artwork_index: ArtworkIndex,
    photos: DatabaseDocument[PhotosMhfdHeader] | None,
    requested_plan: LibraryWritePlan,
    resources: WriteResources,
    *,
    resolve: Callable[[LibraryDraft, WriteTarget], ResolvedWrite],
    source_revision: str,
    cdb_framing: ITunesCDB | None = None,
    progress: Callable[[WritePhase], None] | None = None,
) -> LibraryWriteResult:
    measurements: list[WriteMeasurement] = []
    entered: WritePhase | None = None
    started = perf_counter()
    log_resources(source_revision, resources)

    def notify(phase: WritePhase) -> None:
        nonlocal entered, started
        now = perf_counter()
        if entered is not None:
            measurements.append(WriteMeasurement(entered, (now - started) * 1000))
        entered, started = phase, now
        logger.debug("Library stage entered source=%s phase=%s", source_revision, phase)
        if progress is not None:
            try:
                progress(phase)
            except Exception as error:
                # Caller cancellation/observer failures are not encoding errors.
                raise _ObserverError(error) from error

    try:
        result = _prepare(
            source,
            document,
            artwork,
            artwork_index,
            photos,
            requested_plan,
            resources,
            notify,
            resolve=resolve,
            source_revision=source_revision,
            cdb_framing=cdb_framing,
        )
        if entered is not None:
            measurements.append(
                WriteMeasurement(entered, (perf_counter() - started) * 1000)
            )
        result = replace(result, measurements=tuple(measurements))
        log_result(source_revision, result)
        return result
    except _ObserverError as error:
        logger.debug(
            "Library preparation interrupted source=%s phase=%s reason=%r",
            source_revision,
            entered,
            error.error,
        )
        raise error.error from None


def _prepare(
    source: IPodLibrary,
    document: DatabaseDocument[MhbdHeader],
    artwork: DatabaseDocument[MhfdHeader] | None,
    artwork_index: ArtworkIndex,
    photos: DatabaseDocument[PhotosMhfdHeader] | None,
    requested_plan: LibraryWritePlan,
    resources: WriteResources,
    notify: Callable[[WritePhase], None],
    *,
    resolve: Callable[[LibraryDraft, WriteTarget], ResolvedWrite],
    source_revision: str,
    cdb_framing: ITunesCDB | None,
) -> LibraryWriteResult:
    # Revalidate public immutable plans: callers cannot bypass validation by
    # constructing a plan or replacing its issues/requirements themselves.
    notify(WritePhase.VALIDATION)
    resolved = resolve(requested_plan.draft, requested_plan.target)
    plan = resolved.plan
    issues = list(plan.issues)
    if any(issue.code == "draft.wrong_source" for issue in issues):
        return LibraryWriteResult(tuple(issues))
    notify(WritePhase.RESOURCES)
    media = {m.track_id: m for m in resources.media}
    lyrics = {item.track_id: item for item in resources.lyrics}
    issues.extend(validate_lyrics(plan, resources))
    issues.extend(validate_photos(plan, resources, source.snapshot.photos))
    assets = {a.artwork_id: a for a in resources.artwork}
    if len(media) != len(resources.media) or len(assets) != len(resources.artwork):
        issues.append(
            WriteIssue(
                "resources.duplicate_identity",
                "Prepared resources contain duplicate identities.",
            )
        )
    desired, generated_podcasts = resolved.desired, resolved.generated_podcasts
    tracks = {t.track_id: t for t in desired.tracks}
    deleted_owners = {
        t.ipod.db_track_id: t.track_id
        for t in source.snapshot.tracks
        if t.ipod and t.track_id not in tracks
    }
    if artwork is not None:
        issues.extend(
            WriteIssue(
                "artwork.photo_music_dependency",
                "A retained photo album references this Track for slideshow music. Keep the Track until that photo relationship can be edited explicitly.",
                subject="track",
                record_id=deleted_owners[selection.chunk.header.db_track_id_ref],
                field="ipod.db_track_id",
                offset=selection.chunk.offset,
                artifact="ArtworkDB",
            )
            for selection in artwork.find_chunks(MhbaHeader)
            if selection.chunk.header.db_track_id_ref
            and selection.chunk.header.db_track_id_ref in deleted_owners
        )
    issues.extend(
        WriteIssue(
            "resources.unrequested_media",
            "Media facts were supplied for a Track without a media change.",
            subject="track",
            record_id=identity,
        )
        for identity in media
        if identity not in plan.required_media
    )
    inventory_paths = [
        f.relative_path.casefold() for f in resources.file_inventory or ()
    ]
    dependencies = {
        f.relative_path.casefold(): f for f in resources.file_inventory or ()
    }
    for asset in resources.photos:
        for photo_file in asset.files:
            key = photo_file.dependency.relative_path.casefold()
            if key in dependencies:
                issues.append(
                    WriteIssue(
                        "resources.file_collision",
                        "A new Photo file collides with another captured resource.",
                        subject="photo",
                        record_id=asset.photo.photo_id,
                    )
                )
            else:
                dependencies[key] = photo_file.dependency
    captured_media: tuple[PreparedMedia | PreparedLyrics, ...] = (
        *resources.media,
        *resources.lyrics,
    )
    for prepared_media in captured_media:
        key = prepared_media.file.relative_path.casefold()
        existing = dependencies.get(key)
        if existing is not None and (
            existing.size != prepared_media.file.size
            or existing.sha256.lower() != prepared_media.file.sha256.lower()
        ):
            issues.append(
                WriteIssue(
                    "resources.conflicting_file",
                    "Captured identities disagree for the same media file. Refresh its prepared facts and inventory together.",
                    subject="track",
                    record_id=prepared_media.track_id,
                    detail=prepared_media.file.relative_path,
                )
            )
        else:
            dependencies.setdefault(key, prepared_media.file)
    source_paths = [f.dependency.relative_path.casefold() for f in resources.files]
    if len(set(inventory_paths)) != len(inventory_paths) or len(
        set(source_paths)
    ) != len(source_paths):
        issues.append(
            WriteIssue(
                "resources.file_collision",
                "Captured resource paths contain duplicate or case-insensitive file collisions.",
            )
        )
    for dependency in resources.file_inventory or ():
        try:
            validated_path(dependency.relative_path)
            if (
                dependency.size < 0
                or len(dependency.sha256) != 64
                or len(bytes.fromhex(dependency.sha256)) != 32
            ):
                raise ValueError(
                    "Captured files require a nonnegative size and SHA-256 fingerprint."
                )
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "resources.invalid_inventory",
                    str(error),
                    detail=dependency.relative_path,
                )
            )
    if (
        plan.requires_sidecar_inventory
        and resources.pending_playback_sidecars is not False
    ):
        issues.append(
            WriteIssue(
                "resources.playback_sidecars",
                "Track membership changes require a captured inventory with no pending positional playback sidecars. Preserve or reconcile them before preparing output.",
            )
        )
    for track_id in plan.required_media:
        item = media.get(track_id)
        if item is None:
            issues.append(
                WriteIssue(
                    "resources.missing_media",
                    "Supply prepared media facts and a captured file identity for this Track.",
                    subject="track",
                    record_id=track_id,
                )
            )
            continue
        track = tracks[track_id]
        try:
            validated_path(item.file.relative_path)
            if item.file.relative_path != track.metadata.location or item.file.size != (
                lyrics[track_id].file.size if track_id in lyrics else track.size_bytes
            ):
                raise ValueError(
                    "Prepared media identity does not match the Track location and size."
                )
            if (
                item.file.size <= 0
                or len(item.file.sha256) != 64
                or len(bytes.fromhex(item.file.sha256)) != 32
            ):
                raise ValueError(
                    "Prepared media requires a nonempty file and a SHA-256 fingerprint."
                )
            if not isinstance(cast("object", item.content), MediaContent):
                raise ValueError(
                    "Prepared media requires an explicit supported content kind."
                )
            if item.content is MediaContent.DOCUMENT:
                if track.length_ms != 0:
                    raise ValueError(
                        "Prepared documents require zero playback duration."
                    )
            elif track.length_ms <= 0:
                raise ValueError("Prepared audio/video requires a positive duration.")
            if item.content in (MediaContent.AUDIO, MediaContent.AUDIO_VIDEO):
                if track.metadata.sample_rate_hz <= 0:
                    raise ValueError("Prepared audio requires a positive sample rate.")
            elif any(
                (
                    track.metadata.sample_rate_hz,
                    track.metadata.sample_count,
                    track.metadata.pregap,
                    track.metadata.postgap,
                    track.metadata.gapless,
                    item.gapless_audio_payload_size,
                )
            ):
                raise ValueError(
                    "Prepared content without audio requires zero audio timing and gapless facts."
                )
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "resources.invalid_media",
                    str(error),
                    subject="track",
                    record_id=track_id,
                )
            )
    known_artwork: set[int] = (
        set() if artwork is None else {item.image_id for item in artwork_index.items}
    )
    issues.extend(
        WriteIssue(
            "resources.artwork_identity",
            "Replacement pixels require a new artwork identity referenced by a changed Track.",
            subject="artwork",
            record_id=artwork_id,
        )
        for artwork_id in assets
        if artwork_id in known_artwork
        or artwork_id not in plan.required_artwork
        or artwork_id == 0
    )
    issues.extend(
        WriteIssue(
            "resources.missing_artwork",
            f"Supply RGB888 pixels for artwork {artwork_id}.",
            subject="artwork",
            record_id=artwork_id,
        )
        for artwork_id in plan.required_artwork
        if artwork_id not in known_artwork and artwork_id not in assets
    )
    for source_file in resources.files:
        try:
            validated_path(source_file.dependency.relative_path)
            if (
                len(source_file.data) != source_file.dependency.size
                or content_sha256(source_file.data) != source_file.dependency.sha256
            ):
                raise ValueError("Source bytes do not match the captured fingerprint.")
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "resources.changed_file",
                    str(error),
                    detail=source_file.dependency.relative_path,
                )
            )
    # An unchanged draft still validates supplied evidence. Returning retained
    # bytes needs no reconciliation or signing, even for unsupported signatures.
    if not plan.changes:
        if _blocked(issues):
            return LibraryWriteResult(tuple(issues))
        try:
            notify(WritePhase.SERIALIZATION)
            output = source.serialize()
        except iPodDBWriteError as error:
            return LibraryWriteResult(
                (
                    *issues,
                    WriteIssue(
                        error.code,
                        "The retained source could not be serialized losslessly.",
                        phase="serialization",
                        field=error.field,
                        detail=str(error),
                        chunk_path=error.chunk_path,
                        offset=error.offset,
                    ),
                )
            )
        return LibraryWriteResult(
            tuple(issues),
            PreparedLibrary(
                output.itunes,
                output.artwork,
                (),
                (),
                source.snapshot,
                (),
                plan.draft.source_revision,
                retained_artwork(artwork_index),
                photos=output.photos,
            ),
        )
    if (
        plan.changes_itunes
        and document.header.hashing_scheme
        and plan.target.checksum is WriteChecksum.NONE
    ):
        issues.append(
            WriteIssue(
                "target.signature_required",
                "The source database is signed; supply its supported signature target before editing.",
            )
        )
    if plan.changes_itunes and document.header.hashing_scheme not in (0, 1, 2, 3, 4):
        issues.append(
            WriteIssue(
                "target.unsupported_source_signature",
                "The retained iTunesDB uses an unsupported signature scheme. Its signing requirements cannot be replaced implicitly.",
            )
        )
    if _blocked(issues):
        return LibraryWriteResult(tuple(issues))
    phase = "reconciliation"
    artifact = "iTunesDB"
    binary_document: ParsedChunk[ChunkHeader] = document
    mappings: tuple[IdentityMapping, ...] = ()
    try:
        notify(WritePhase.RECONCILIATION)
        candidate = document
        candidate_artwork = artwork
        artwork_files: tuple[PreparedFile, ...] = ()
        art_mappings: tuple[IdentityMapping, ...] = ()
        if plan.changes_itunes:
            candidate, mappings = reconcile(
                document,
                resolved,
                resources,
                issues,
                source.device_time,
            )
            if _blocked(issues):
                return LibraryWriteResult(tuple(issues))
            phase = "artwork"
            notify(WritePhase.ARTWORK)
            (
                candidate,
                candidate_artwork,
                artwork_files,
                art_mappings,
            ) = reconcile_artwork(
                candidate,
                artwork,
                resolved,
                mappings,
                plan.target,
                resources,
            )
            mappings = (*mappings, *art_mappings)
        candidate_photos = photos
        if plan.changes_photos:
            if resolved.desired.photos is None:
                raise ValueError(
                    "Photo edits require one retained and projected Photo Database."
                )
            candidate_photos = reconcile_photos(
                photos,
                source.snapshot.photos,
                resolved.desired.photos,
                dict(resolved.persistent_ids),
                plan.target,
                source.device_time,
            )
        phase = "serialization"
        notify(WritePhase.SERIALIZATION)
        binary_document = candidate
        logical_itunes = write_iTunesDB(candidate)
        retained_output = source.serialize()
        if plan.changes_itunes and plan.target.checksum is not WriteChecksum.NONE:
            phase = "signing"
            artifact = "iTunesCDB" if plan.target.compressed_database else "iTunesDB"
            notify(WritePhase.SIGNING)
        itunes = (
            _finalize_itunes(logical_itunes, plan.target, cdb_framing)
            if plan.changes_itunes
            else retained_output.itunes
        )
        artwork_bytes = None
        if candidate_artwork is not None:
            artifact = "ArtworkDB"
            binary_document = candidate_artwork
            artwork_bytes = write_ArtworkDB(candidate_artwork)
        photos_bytes = None
        if candidate_photos is not None:
            artifact = "PhotosDB"
            binary_document = candidate_photos
            photos_bytes = write_PhotosDB(candidate_photos)
        if (
            len(itunes) > plan.target.max_database_bytes
            or (
                artwork_bytes is not None
                and len(artwork_bytes) > plan.target.max_database_bytes
            )
            or (
                photos_bytes is not None
                and len(photos_bytes) > plan.target.max_database_bytes
            )
        ):
            raise ValueError("Prepared database exceeds the target's size limit.")
        phase = "verification"
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Library candidate source=%s iTunesDB_bytes=%d iTunesDB_sha256=%s ArtworkDB_bytes=%s ArtworkDB_sha256=%s PhotosDB_bytes=%s PhotosDB_sha256=%s artwork_files=%d checksum=%s",
                source_revision,
                len(itunes),
                hashlib.sha256(itunes).hexdigest(),
                None if artwork_bytes is None else len(artwork_bytes),
                None
                if artwork_bytes is None
                else hashlib.sha256(artwork_bytes).hexdigest(),
                None if photos_bytes is None else len(photos_bytes),
                None
                if photos_bytes is None
                else hashlib.sha256(photos_bytes).hexdigest(),
                len(artwork_files),
                plan.target.checksum,
            )
        notify(WritePhase.VERIFICATION)
        checked_logical_bytes = (
            decompress_iTunesCDB(itunes).logical_bytes
            if plan.target.compressed_database
            else itunes
        )
        checked_document = parse_iTunesDB(checked_logical_bytes)
        checked_artwork = (
            parse_ArtworkDB(artwork_bytes) if artwork_bytes is not None else None
        )
        checked_photos = (
            parse_PhotosDB(photos_bytes) if photos_bytes is not None else None
        )
        checked_index = (
            build_artwork_index(checked_artwork)
            if checked_artwork is not None
            else EMPTY_ARTWORK_INDEX
        )
        checked_tracks = project_tracks(checked_document, source.device_time)
        if checked_artwork is not None:
            checked_tracks = link_artwork(checked_tracks, checked_index)
        checked_playlists, checked_name = project_playlists(
            checked_document,
            frozenset(t.track_id for t in checked_tracks),
            source.device_time,
        )
        checked_photo_library = (
            project_photos(
                checked_photos,
                {
                    track.ipod.db_track_id: track.track_id
                    for track in checked_tracks
                    if track.ipod is not None and track.ipod.db_track_id
                },
                source.device_time,
            )
            if checked_photos is not None
            else None
        )
        checked = LibrarySnapshot(
            checked_tracks,
            checked_playlists,
            checked_name,
            checked_photo_library,
        )
        checked_logical = write_iTunesDB(checked_document)
        if (
            (
                _finalize_itunes(checked_logical, plan.target, cdb_framing)
                if plan.changes_itunes
                else retained_output.itunes
            )
            != itunes
            or (
                write_ArtworkDB(checked_artwork)
                if checked_artwork is not None
                else None
            )
            != artwork_bytes
            or (write_PhotosDB(checked_photos) if checked_photos is not None else None)
            != photos_bytes
        ):
            raise ValueError("Prepared databases failed lossless reparse verification.")
        original_bytes = retained_output
        original_logical = write_iTunesDB(document)
        issues.extend(
            verify_native_tracks(
                document,
                checked_document,
                source.snapshot,
                desired,
                mappings,
                resources,
                source.device_time,
            )
        )
        issues.extend(
            verify_browse_groups(
                document, checked_document, source.snapshot, desired, mappings
            )
        )
        if (
            not resolved.artwork_tracks
            and not resolved.deleted_tracks
            and (artwork_bytes != original_bytes.artwork or artwork_files)
        ):
            issues.append(
                WriteIssue(
                    "verification.unrequested_artwork",
                    "Prepared output changed artwork without an artwork selection or ownership change.",
                    phase="verification",
                    artifact="ArtworkDB",
                )
            )
        if not plan.changes_photos and photos_bytes != original_bytes.photos:
            issues.append(
                WriteIssue(
                    "verification.unrequested_photos",
                    "Prepared output changed PhotosDB without a Photo edit.",
                    phase="verification",
                    subject="photos",
                    artifact="PhotosDB",
                )
            )
        issues.extend(
            verify_playlists(
                document,
                checked_document,
                source.snapshot,
                desired,
                mappings,
                original_logical,
                checked_logical,
                generated_podcasts,
                source.device_time,
            )
        )
        if _blocked(issues):
            return LibraryWriteResult(tuple(issues))
        verify_relationships(
            document,
            checked_document,
            original_logical,
            checked_logical,
            artwork,
            checked_artwork,
            original_bytes.artwork,
            artwork_bytes,
            artwork_index,
            checked_index,
            artwork_files,
            resources,
            {m.output_id for m in art_mappings}
            | {i for i in plan.required_artwork if i in known_artwork},
        )
        verify_artwork(
            artwork,
            checked_artwork,
            checked_document,
            document,
            resolved,
            mappings,
            resources,
            artwork_files,
        )
        identity_maps = {
            kind: {
                m.draft_id: m.output_id
                for m in mappings
                if m.subject == kind and m.track_id is None
            }
            for kind in ("track", "playlist", "artwork")
        }
        actual_tracks = {t.track_id: t for t in checked.tracks}
        track_artwork = {
            m.track_id: m.output_id for m in art_mappings if m.track_id is not None
        }
        original_tracks = {t.track_id: t for t in source.snapshot.tracks}
        for wanted in desired.tracks:
            native_id = identity_maps["track"].get(wanted.track_id, wanted.track_id)
            actual = actual_tracks.get(native_id)
            if actual is None:
                issues.append(
                    WriteIssue(
                        "verification.missing_track",
                        "Prepared output omitted a desired Track.",
                        phase="verification",
                        subject="track",
                        record_id=wanted.track_id,
                    )
                )
                continue
            expected = replace(
                wanted,
                size_bytes=lyrics[wanted.track_id].file.size
                if wanted.track_id in lyrics
                else wanted.size_bytes,
                track_id=native_id,
                ipod=actual.ipod,
                artwork_id=track_artwork.get(
                    wanted.track_id,
                    identity_maps["artwork"].get(wanted.artwork_id, wanted.artwork_id),
                ),
            )
            metadata = expected.metadata
            prior = original_tracks.get(wanted.track_id)
            if (
                artwork is None
                and checked_artwork is not None
                and prior is not None
                and prior.artwork_id
                and prior.artwork_id == wanted.artwork_id
                and checked_index.item_for_image_id(prior.artwork_id) is None
            ):
                # Attaching the first index resolves previously unverified IDs.
                # Keep the native field; an absent image remains unavailable.
                expected = replace(expected, artwork_id=0)
                issues.append(
                    WriteIssue(
                        "artwork.unresolved_reference",
                        "This Track's retained artwork reference has no image in the new ArtworkDB and remains unavailable.",
                        severity=IssueSeverity.WARNING,
                        phase="verification",
                        subject="track",
                        record_id=wanted.track_id,
                        field="artwork_id",
                    )
                )
            if prior is None or prior.artwork_id != wanted.artwork_id:
                artwork_item = checked_index.item_for_image_id(expected.artwork_id)
                metadata = replace(
                    metadata,
                    artwork_count=len(artwork_item.locations) if artwork_item else 0,
                )
            expected = replace(expected, metadata=metadata)
            if actual != expected:
                differing = ", ".join(
                    f.name
                    for f in fields(actual)
                    if getattr(actual, f.name) != getattr(expected, f.name)
                )
                issues.append(
                    WriteIssue(
                        "verification.track_mismatch",
                        "Prepared Track does not match the desired values.",
                        phase="verification",
                        subject="track",
                        record_id=wanted.track_id,
                        field=differing,
                    )
                )
        if len(actual_tracks) != len(desired.tracks):
            issues.append(
                WriteIssue(
                    "verification.track_count",
                    "Prepared output has unexpected Track records.",
                    phase="verification",
                )
            )
        actual_playlists = {p.playlist_id: p for p in checked.playlists}
        for wanted_playlist in desired.playlists:
            native_id = identity_maps["playlist"].get(
                wanted_playlist.playlist_id, wanted_playlist.playlist_id
            )
            actual_playlist = actual_playlists.get(native_id)
            expected_playlist = replace(
                wanted_playlist,
                playlist_id=native_id,
                parent_id=identity_maps["playlist"].get(
                    wanted_playlist.parent_id, wanted_playlist.parent_id
                )
                if wanted_playlist.parent_id is not None
                else None,
            )
            expected_track_ids = tuple(
                identity_maps["track"].get(t, t) for t in wanted_playlist.track_ids
            )
            if (
                actual_playlist is None
                or replace(actual_playlist, entries=())
                != replace(expected_playlist, entries=())
                or actual_playlist.track_ids != expected_track_ids
            ):
                issues.append(
                    WriteIssue(
                        "verification.playlist_mismatch",
                        "Prepared Playlist does not match its desired values or occurrences.",
                        phase="verification",
                        subject="playlist",
                        record_id=wanted_playlist.playlist_id,
                    )
                )
        if (
            len(actual_playlists) != len(desired.playlists)
            or checked.device_name != desired.device_name
        ):
            issues.append(
                WriteIssue(
                    "verification.library_mismatch",
                    "Prepared Library does not match the desired Playlists or device name.",
                    phase="verification",
                )
            )
        expected_photos = desired.photos
        if expected_photos is not None:
            source_albums = (
                {}
                if source.snapshot.photos is None
                else {album.album_id: album for album in source.snapshot.photos.albums}
            )
            expected_albums: list[PhotoAlbum] = []
            persistent_ids = dict(resolved.persistent_ids)
            for album in expected_photos.albums:
                source_album = source_albums.get(album.album_id)
                ipod = album.ipod
                if ipod is not None and (
                    source_album is None
                    or album.music_track_id != source_album.music_track_id
                ):
                    ipod = replace(
                        ipod,
                        music_db_track_id=(
                            persistent_ids[album.music_track_id]
                            if album.music_track_id is not None
                            else 0
                        ),
                    )
                expected_albums.append(
                    replace(
                        album,
                        music_track_id=(
                            identity_maps["track"].get(
                                album.music_track_id,
                                album.music_track_id,
                            )
                            if album.music_track_id is not None
                            else None
                        ),
                        ipod=ipod,
                    )
                )
            expected_photos = replace(
                expected_photos,
                albums=tuple(expected_albums),
            )
        if checked.photos != expected_photos:
            issues.append(
                WriteIssue(
                    "verification.photos_mismatch",
                    "Prepared Photos do not match the desired Photo Library.",
                    phase="verification",
                    subject="photos",
                    artifact="PhotosDB",
                )
            )
        if _blocked(issues):
            return LibraryWriteResult(tuple(issues))
        sqlite = None
        if plan.target.sqlite_database and plan.changes_itunes:
            hash72_material = plan.target.hash72_material
            sqlite = build_sqlite_databases(
                checked,
                database_id=checked_document.header.db_id,
                checksum=plan.target.sqlite_checksum,
                firewire_guid=plan.target.firewire_guid,
                hash72_iv=(hash72_material.iv if hash72_material is not None else b""),
                hash72_random=(
                    hash72_material.random_part if hash72_material is not None else b""
                ),
                postprocess_commands=plan.target.sqlite_postprocess_commands,
                smart_criteria=_sqlite_smart_criteria(checked_document),
            )
        return LibraryWriteResult(
            tuple(issues),
            PreparedLibrary(
                itunes,
                artwork_bytes,
                artwork_files,
                tuple(dependencies.values()),
                checked,
                mappings,
                plan.draft.source_revision,
                retained_artwork(checked_index),
                photos=photos_bytes,
                sqlite=sqlite,
            ),
        )
    except iPodDBWriteError as error:
        subject, record_id = _record_context(
            binary_document, error.chunk_path, artifact
        )
        record_id = next(
            (
                mapping.draft_id
                for mapping in mappings
                if mapping.subject == subject and mapping.output_id == record_id
            ),
            record_id,
        )
        issues.append(
            WriteIssue(
                error.code,
                "A database field or structure cannot be encoded without data loss.",
                phase=phase,
                subject=subject,
                record_id=record_id,
                field=error.field,
                detail=str(error),
                chunk_path=error.chunk_path,
                offset=error.offset,
                artifact=artifact,
            )
        )
    except (ValueError, OverflowError, RecursionError) as error:
        issues.append(
            WriteIssue(
                "verification.failed"
                if phase == "verification"
                else "preparation.cannot_encode",
                str(error),
                phase=phase,
            )
        )
    return LibraryWriteResult(tuple(issues))
