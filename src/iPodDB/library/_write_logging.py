"""Debug observations of semantic preparation, without dumping binary resources."""

import hashlib
import logging
from reprlib import Repr

from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import LibraryWritePlan, LibraryWriteResult, WriteResources

logger = logging.getLogger(__name__)
_summary = Repr(maxstring=240, maxother=240, maxtuple=12)


def log_plan(plan: LibraryWritePlan, before: LibrarySnapshot) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    revision = plan.draft.source_revision
    logger.debug(
        "Library analysis source=%s requested=%d blocked=%s tracks=%d playlists=%d photos=%d photo_albums=%d "
        "delete_omissions=%s checksum=%s signing_identity_present=%s "
        "compressed=%s sqlite=%s max_database_bytes=%d",
        revision,
        len(plan.changes),
        plan.blocked,
        len(plan.draft.snapshot.tracks),
        len(plan.draft.snapshot.playlists),
        len(plan.draft.snapshot.photos.photos)
        if plan.draft.snapshot.photos is not None
        else 0,
        len(plan.draft.snapshot.photos.albums)
        if plan.draft.snapshot.photos is not None
        else 0,
        plan.draft.delete_omissions,
        plan.target.checksum,
        bool(plan.target.firewire_guid),
        plan.target.compressed_database,
        plan.target.sqlite_database,
        plan.target.max_database_bytes,
    )
    resolution = plan.resolution
    snapshots = [("requested", before, plan.draft.snapshot, plan.changes)]
    if resolution is not None:
        snapshots.append(
            (
                "generated",
                plan.draft.snapshot,
                resolution.snapshot,
                resolution.generated_changes,
            )
        )
    for origin, old, new, changes in snapshots:
        old_records: dict[tuple[str, int | None], object] = {
            **{("track", t.track_id): t for t in old.tracks},
            **{("playlist", p.playlist_id): p for p in old.playlists},
            **{
                ("photo", photo.photo_id): photo
                for photo in (old.photos.photos if old.photos is not None else ())
            },
            **{
                ("photo_album", album.album_id): album
                for album in (old.photos.albums if old.photos is not None else ())
            },
            ("photos", None): old.photos,
            ("library", None): old,
        }
        new_records: dict[tuple[str, int | None], object] = {
            **{("track", t.track_id): t for t in new.tracks},
            **{("playlist", p.playlist_id): p for p in new.playlists},
            **{
                ("photo", photo.photo_id): photo
                for photo in (new.photos.photos if new.photos is not None else ())
            },
            **{
                ("photo_album", album.album_id): album
                for album in (new.photos.albums if new.photos is not None else ())
            },
            ("photos", None): new.photos,
            ("library", None): new,
        }
        for change in changes:
            key = change.subject, change.record_id
            logger.debug(
                "Library change source=%s origin=%s subject=%s id=%s action=%s name=%r fields=%s",
                revision,
                origin,
                *key,
                change.action,
                change.name,
                change.fields,
            )
            for field in change.fields:
                prior, desired = old_records.get(key), new_records.get(key)
                for part in field.split("."):
                    prior = getattr(prior, part, None)
                    desired = getattr(desired, part, None)
                logger.debug(
                    "Library value source=%s origin=%s subject=%s id=%s field=%s before=%s after=%s",
                    revision,
                    origin,
                    *key,
                    field,
                    _summary.repr(prior),
                    _summary.repr(desired),
                )
    if resolution is not None:
        for effect in resolution.effects:
            logger.debug(
                "Library effect source=%s code=%s subject=%s id=%s dataset=%s causes=%s fields=%s reason=%s",
                revision,
                effect.code,
                effect.subject,
                effect.record_id,
                effect.dataset,
                effect.causes,
                effect.fields,
                effect.reason,
            )
    logger.debug(
        "Library requirements source=%s media=%s artwork=%s artwork_inventory=%s sidecar_inventory=%s",
        revision,
        plan.required_media,
        plan.required_artwork,
        plan.requires_artwork_inventory,
        plan.requires_sidecar_inventory,
    )
    for issue in plan.issues:
        logger.debug("Library analysis issue source=%s %s", revision, issue)


def log_resources(revision: str, resources: WriteResources) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Library resources source=%s media=%d artwork=%d supplied_files=%d inventory=%s pending_sidecars=%s",
        revision,
        len(resources.media),
        len(resources.artwork),
        len(resources.files),
        None if resources.file_inventory is None else len(resources.file_inventory),
        resources.pending_playback_sidecars,
    )
    for media in resources.media:
        logger.debug("Library media source=%s %s", revision, media)
    for asset in resources.artwork:
        logger.debug(
            "Library artwork asset source=%s id=%d width=%d height=%d bytes=%d",
            revision,
            asset.artwork_id,
            asset.pixels.width,
            asset.pixels.height,
            len(asset.pixels.rgb888),
        )
    for dependency in resources.file_inventory or ():
        logger.debug("Library file dependency source=%s %s", revision, dependency)


def log_result(revision: str, result: LibraryWriteResult) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Library preparation result source=%s prepared=%s issues=%d",
        revision,
        result.prepared is not None,
        len(result.issues),
    )
    for issue in result.issues:
        logger.debug("Library preparation issue source=%s %s", revision, issue)
    for measurement in result.measurements:
        logger.debug(
            "Library stage elapsed source=%s phase=%s elapsed_ms=%.3f",
            revision,
            measurement.phase,
            measurement.elapsed_ms,
        )
    prepared = result.prepared
    if prepared is None:
        return
    for artifact, data in (
        ("iTunesDB", prepared.itunes),
        ("ArtworkDB", prepared.artwork),
        ("PhotosDB", prepared.photos),
    ):
        logger.debug(
            "Library output source=%s artifact=%s bytes=%s sha256=%s",
            revision,
            artifact,
            None if data is None else len(data),
            None if data is None else hashlib.sha256(data).hexdigest(),
        )
    for mapping in prepared.identities:
        logger.debug("Library identity source=%s %s", revision, mapping)
    for file in prepared.artwork_files:
        logger.debug(
            "Library output source=%s artifact=%r bytes=%d sha256=%s",
            revision,
            file.relative_path,
            len(file.data),
            hashlib.sha256(file.data).hexdigest(),
        )
    for retained in prepared.retained_artwork:
        logger.debug("Library retained artwork source=%s %s", revision, retained)
