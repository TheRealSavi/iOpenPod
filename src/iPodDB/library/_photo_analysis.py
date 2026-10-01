"""Validate Photo Library draft changes before retained-document reconciliation."""

from iPodDB.device_time import TimeConversion, unix_to_mac
from iPodDB.library._field_policy import (
    PHOTO_ALBUM_POLICY,
    PHOTO_POLICY,
    FieldOwnership,
    FieldPolicy,
    changed_fields,
)
from iPodDB.library.models import Track
from iPodDB.library.photos import PhotoAlbum, PhotoAlbumKind, PhotoLibrary
from iPodDB.library.writing import LibraryChange, WriteIssue, WriteTarget


def analyze_photos(
    original: PhotoLibrary | None,
    desired: PhotoLibrary | None,
    *,
    delete_omissions: bool,
    tracks: tuple[Track, ...],
    target: WriteTarget | None = None,
    replace_photos: tuple[int, ...] = (),
    device_time: TimeConversion = 0,
) -> tuple[tuple[LibraryChange, ...], tuple[WriteIssue, ...]]:
    """Return observable Photo changes and fail-closed editing diagnostics."""

    creating = original is None and desired is not None
    if (
        creating
        and target is not None
        and target.photos_root_value is not None
        and target.photo_formats
    ):
        original = PhotoLibrary()
    if original is None or desired is None:
        if original is desired:
            return (), ()
        action = "add" if original is None else "delete"
        return (
            (LibraryChange("photos", None, action, "Photo Library", ("photos",)),),
            (
                WriteIssue(
                    "photos.unsupported_artifact_change",
                    "Attaching or removing the Photo Database is not supported.",
                    subject="photos",
                    field="photos",
                    artifact="PhotosDB",
                ),
            ),
        )

    changes: list[LibraryChange] = []
    issues: list[WriteIssue] = []
    if creating and not desired.photos:
        issues.append(
            WriteIssue(
                "photos.empty_creation",
                "Create a Photo Database by adding a prepared Photo.",
                subject="photos",
                artifact="PhotosDB",
            )
        )
    desired_ids = {photo.photo_id for photo in desired.photos}
    asset_change = (
        creating
        or bool(replace_photos)
        or bool(desired_ids - {photo.photo_id for photo in original.photos})
    )
    if asset_change:
        masters = tuple(
            album for album in desired.albums if album.kind is PhotoAlbumKind.MASTER
        )
        if (
            len(masters) != 1
            or set(masters[0].photo_ids) != desired_ids
            or len(masters[0].photo_ids) != len(desired_ids)
        ):
            issues.append(
                WriteIssue(
                    "photo_album.master_required",
                    "Photo asset changes require one Master Album containing every Photo exactly once.",
                    subject="photos",
                    artifact="PhotosDB",
                )
            )
    _analyze_photo_records(
        original,
        desired,
        changes,
        issues,
        delete_omissions=delete_omissions,
        replace_photos=replace_photos,
        allow_assets=bool(target and target.photo_formats),
        device_time=device_time,
    )
    _analyze_albums(
        original,
        desired,
        changes,
        issues,
        delete_omissions=delete_omissions,
        tracks=tracks,
        creating=creating,
    )
    if original.formats != desired.formats:
        changes.append(
            LibraryChange(
                "photos",
                None,
                "edit",
                "Photo formats",
                ("formats",),
            )
        )
        original_formats = {item.format_id: item for item in original.formats}
        target_formats: set[int] = (
            set()
            if target is None
            else {item.format_id for item in target.photo_formats}
        )
        legal_additions = tuple(
            item for item in desired.formats if item.format_id in original_formats
        ) == original.formats and all(
            item.format_id in target_formats
            for item in desired.formats
            if item.format_id not in original_formats
        )
        if not legal_additions:
            issues.append(
                WriteIssue(
                    "photos.read_only_formats",
                    "Photo file formats are retained device metadata and cannot be edited.",
                    subject="photos",
                    field="formats",
                    artifact="PhotosDB",
                )
            )
    return tuple(changes), tuple(issues)


def _analyze_photo_records(
    original: PhotoLibrary,
    desired: PhotoLibrary,
    changes: list[LibraryChange],
    issues: list[WriteIssue],
    *,
    delete_omissions: bool,
    replace_photos: tuple[int, ...],
    allow_assets: bool,
    device_time: TimeConversion,
) -> None:
    previous = {photo.photo_id: photo for photo in original.photos}
    wanted = {photo.photo_id: photo for photo in desired.photos}
    if len(set(replace_photos)) != len(replace_photos) or any(
        identity not in previous or identity not in wanted
        for identity in replace_photos
    ):
        issues.append(
            WriteIssue(
                "photo.invalid_replacement",
                "Photo replacements require unique retained Photo identities.",
                subject="photos",
                artifact="PhotosDB",
            )
        )
    for photo_id in previous:
        if photo_id not in wanted:
            changes.append(
                LibraryChange("photo", photo_id, "delete", f"Photo {photo_id}")
            )
            if not delete_omissions:
                _photo_issue(
                    issues,
                    "draft.deletion_not_enabled",
                    "This Photo was removed without deletion being authorized. Restore it or explicitly authorize deletion.",
                    photo_id,
                    "photo_id",
                    detail="Authorize deletion only when this removal is intentional.",
                )
    for photo_id, photo in wanted.items():
        prior = previous.get(photo_id)
        if prior is None:
            changes.append(LibraryChange("photo", photo_id, "add", f"Photo {photo_id}"))
            if not allow_assets:
                _photo_issue(
                    issues,
                    "photo.unsupported_record_change",
                    "Adding or removing Photos requires a separate asset workflow.",
                    photo_id,
                    "photo_id",
                )
        if prior == photo and photo_id not in replace_photos:
            continue
        fields = (
            changed_fields(prior, photo)
            if prior is not None
            else ("rating", "original_date", "taken_date")
        )
        if prior is not None:
            changes.append(
                LibraryChange(
                    "photo",
                    photo_id,
                    "edit",
                    f"Photo {photo_id}",
                    fields or ("representations",),
                )
            )
        retained = _retained_changes(PHOTO_POLICY, fields)
        if allow_assets and photo_id in replace_photos:
            retained = tuple(
                name
                for name in retained
                if name not in {"source_size_bytes", "representations"}
            )
        if retained:
            _photo_issue(
                issues,
                "photo.unsupported_edit",
                "Photo source size and stored representations are read-only.",
                photo_id,
                ", ".join(retained),
            )
        if not _u32(photo_id) or photo_id == 0 or not _u32(photo.source_size_bytes):
            _photo_issue(
                issues,
                "photo.invalid_identity",
                "Photos require a positive u32 identity and u32 source size.",
                photo_id,
                "photo_id",
            )
        for field in ("rating", "original_date", "taken_date"):
            value = getattr(photo, field)
            valid = _u32(value) and value <= 100 if field == "rating" else True
            if field != "rating" and field in fields:
                try:
                    unix_to_mac(value, device_time)
                except ValueError:
                    valid = False
            if field in fields and not valid:
                _photo_issue(
                    issues,
                    "photo.invalid_value",
                    "Photo ratings use 0-100; dates need a known timezone and a unique instant in the iPod date range.",
                    photo_id,
                    field,
                )
    retained_ids = set(previous).intersection(wanted)
    original_order = tuple(
        photo.photo_id for photo in original.photos if photo.photo_id in retained_ids
    )
    desired_order = tuple(
        photo.photo_id for photo in desired.photos if photo.photo_id in retained_ids
    )
    if original_order != desired_order:
        changes.append(
            LibraryChange("photos", None, "edit", "Photo order", ("photos",))
        )
        issues.append(
            WriteIssue(
                "photos.read_only_order",
                "Photo source order is retained and cannot be rearranged.",
                subject="photos",
                field="photos",
                artifact="PhotosDB",
            )
        )


def _analyze_albums(
    original: PhotoLibrary,
    desired: PhotoLibrary,
    changes: list[LibraryChange],
    issues: list[WriteIssue],
    *,
    delete_omissions: bool,
    tracks: tuple[Track, ...],
    creating: bool,
) -> None:
    previous = {album.album_id: album for album in original.albums}
    wanted = {album.album_id: album for album in desired.albums}
    photo_ids = {photo.photo_id for photo in desired.photos}
    removed_photo_ids = {
        photo.photo_id for photo in original.photos if photo.photo_id not in photo_ids
    }
    track_ids = {track.track_id for track in tracks}
    original_photo_ids = {photo.photo_id for photo in original.photos}
    if creating:
        masters = tuple(
            album for album in desired.albums if album.kind is PhotoAlbumKind.MASTER
        )
        if len(masters) != 1 or masters[0].photo_ids != tuple(
            photo.photo_id for photo in desired.photos
        ):
            issues.append(
                WriteIssue(
                    "photo_album.master_required",
                    "A new Photo Library requires one Master Album containing every Photo in order.",
                    subject="photos",
                    artifact="PhotosDB",
                )
            )
    for album_id, album in previous.items():
        if album_id in wanted:
            continue
        changes.append(LibraryChange("photo_album", album_id, "delete", album.name))
        if album.kind is PhotoAlbumKind.MASTER:
            _album_issue(
                issues,
                "photo_album.master_required",
                "The master Photo Library album cannot be removed.",
                album_id,
                "kind",
            )
        elif not delete_omissions:
            _album_issue(
                issues,
                "draft.deletion_not_enabled",
                "This Photo Album was removed without deletion being authorized. Restore it or explicitly authorize deletion.",
                album_id,
                "album_id",
                detail="Authorize deletion only when this removal is intentional.",
            )
    for album_id, album in wanted.items():
        prior = previous.get(album_id)
        if prior is None:
            changes.append(LibraryChange("photo_album", album_id, "add", album.name))
            if (
                type(album_id) is not int
                or not 0 < album_id <= 0xFFFFFFFF
                or (
                    album.kind is not PhotoAlbumKind.ALBUM
                    and not (creating and album.kind is PhotoAlbumKind.MASTER)
                )
                or album.ipod is None
                or type(album.ipod.album_type) is not int
                or not 0 < album.ipod.album_type <= 0xFF
                or (album.kind is PhotoAlbumKind.MASTER and album.ipod.album_type != 1)
                or (
                    album.ipod.album_type == 1
                    and not (creating and album.kind is PhotoAlbumKind.MASTER)
                )
                or type(album.ipod.transition_direction) is not int
                or not 0 <= album.ipod.transition_direction <= 0xFF
                or not _u32(album.ipod.previous_album_id)
            ):
                _album_issue(
                    issues,
                    "photo_album.invalid_creation_policy",
                    "Creating a Photo Album requires a unique u32 identity and a device-specific non-master album type.",
                    album_id,
                    "album_id",
                )
            _validate_music_reference(album, track_ids, issues)
            _validate_album(
                album,
                (
                    "name",
                    "photo_ids",
                    "play_music",
                    "repeat",
                    "random",
                    "show_titles",
                    "slide_duration_ms",
                    "transition_duration_ms",
                ),
                photo_ids,
                issues,
            )
            continue
        _validate_music_reference(album, track_ids, issues)
        if prior == album:
            if removed_photo_ids.intersection(album.photo_ids):
                _validate_album(album, ("photo_ids",), photo_ids, issues)
            continue
        fields = changed_fields(prior, album)
        changes.append(
            LibraryChange("photo_album", album_id, "edit", album.name, fields)
        )
        if prior.kind is PhotoAlbumKind.MASTER:
            expected_membership = tuple(
                photo_id
                for photo_id in prior.photo_ids
                if photo_id not in removed_photo_ids
            ) + tuple(
                photo.photo_id
                for photo in desired.photos
                if photo.photo_id not in original_photo_ids
            )
            if fields != ("photo_ids",) or album.photo_ids != expected_membership:
                _album_issue(
                    issues,
                    "photo_album.master_read_only",
                    "The master Photo Library album changes only as a consequence of deleting Photos.",
                    album_id,
                    ", ".join(fields),
                )
            continue
        retained = _retained_changes(PHOTO_ALBUM_POLICY, fields)
        if retained:
            _album_issue(
                issues,
                "photo_album.unsupported_edit",
                "Photo Album identity, role, and iPod diagnostics are read-only.",
                album_id,
                ", ".join(retained),
            )
        _validate_album(album, fields, photo_ids, issues)

    retained_ids = set(previous).intersection(wanted)
    original_order = tuple(
        album.album_id for album in original.albums if album.album_id in retained_ids
    )
    desired_order = tuple(
        album.album_id for album in desired.albums if album.album_id in retained_ids
    )
    if original_order != desired_order:
        changes.append(
            LibraryChange("photos", None, "edit", "Photo Album order", ("albums",))
        )
        issues.append(
            WriteIssue(
                "photo_album.read_only_order",
                "Retained Photo Albums cannot be rearranged.",
                subject="photos",
                field="albums",
                artifact="PhotosDB",
            )
        )
    desired_retained_prefix = tuple(
        album.album_id for album in desired.albums[: len(original_order)]
    )
    if desired_retained_prefix != original_order:
        issues.append(
            WriteIssue(
                "photo_album.addition_order",
                "New Photo Albums must follow the retained Photo Albums.",
                subject="photos",
                field="albums",
                artifact="PhotosDB",
            )
        )


def _validate_album(
    album: PhotoAlbum,
    changed: tuple[str, ...],
    photo_ids: set[int],
    issues: list[WriteIssue],
) -> None:
    if "name" in changed:
        try:
            album.name.encode("utf-16-le")
        except UnicodeEncodeError:
            valid_name = False
        else:
            valid_name = bool(album.name.strip()) and "\x00" not in album.name
        if not valid_name:
            _album_issue(
                issues,
                "photo_album.invalid_name",
                "Give the Photo Album a nonempty Unicode name without null characters.",
                album.album_id,
                "name",
            )
    if "photo_ids" in changed:
        missing = tuple(
            identity for identity in album.photo_ids if identity not in photo_ids
        )
        if missing:
            _album_issue(
                issues,
                "photo_album.missing_photo",
                f"The Photo Album references missing Photo {missing[0]}.",
                album.album_id,
                "photo_ids",
            )
    for field in ("play_music", "repeat", "random", "show_titles"):
        if field in changed and type(getattr(album, field)) is not bool:
            _album_issue(
                issues,
                "photo_album.invalid_value",
                "Photo Album slideshow flags must be boolean values.",
                album.album_id,
                field,
            )
    for field in ("slide_duration_ms", "transition_duration_ms"):
        if field in changed and not _u32(getattr(album, field)):
            _album_issue(
                issues,
                "photo_album.invalid_value",
                "Photo Album slideshow durations must fit unsigned 32-bit fields.",
                album.album_id,
                field,
            )


def _validate_music_reference(
    album: PhotoAlbum,
    track_ids: set[int],
    issues: list[WriteIssue],
) -> None:
    if album.music_track_id is not None and (
        type(album.music_track_id) is not int or album.music_track_id not in track_ids
    ):
        _album_issue(
            issues,
            "photo_album.missing_music_track",
            "Choose a current Library Track for Photo slideshow music.",
            album.album_id,
            "music_track_id",
        )


def _retained_changes(
    policies: tuple[FieldPolicy, ...], changed: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(
        policy.path
        for policy in policies
        if policy.path in changed
        and policy.ownership in (FieldOwnership.RETAINED, FieldOwnership.IDENTITY)
    )


def _u32(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def _photo_issue(
    issues: list[WriteIssue],
    code: str,
    message: str,
    photo_id: int,
    field: str,
    *,
    detail: str = "",
) -> None:
    issues.append(
        WriteIssue(
            code,
            message,
            subject="photo",
            record_id=photo_id,
            field=field,
            detail=detail,
            artifact="PhotosDB",
        )
    )


def _album_issue(
    issues: list[WriteIssue],
    code: str,
    message: str,
    album_id: int,
    field: str,
    *,
    detail: str = "",
) -> None:
    issues.append(
        WriteIssue(
            code,
            message,
            subject="photo_album",
            record_id=album_id,
            field=field,
            detail=detail,
            artifact="PhotosDB",
        )
    )


__all__ = ["analyze_photos"]
