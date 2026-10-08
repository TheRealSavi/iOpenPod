"""Translate a retained PhotosDB document into the common Photo interface."""

from collections.abc import Mapping

from iPodDB.device_time import TimeConversion, project_mac
from iPodDB.library.photos import (
    IPodPhotoAlbumDetails,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoFileFormat,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.shared.chunk import DatabaseDocument, ParsedChunk


def project_photos(
    document: DatabaseDocument[MhfdHeader],
    persistent_track_ids: Mapping[int, int],
    device_time: TimeConversion = 0,
) -> PhotoLibrary:
    """Project PhotosDB records without exposing Chunks or device paths as authority."""

    photos = tuple(
        _project_photo(selection.chunk, device_time)
        for selection in document.find_chunks(MhiiHeader)
    )
    albums = tuple(
        _project_album(selection.chunk, persistent_track_ids)
        for selection in document.find_chunks(MhbaHeader)
    )
    formats = tuple(
        _project_format(selection.chunk)
        for selection in document.find_chunks(MhifHeader)
    )
    return PhotoLibrary(photos, albums, formats)


def _project_photo(
    chunk: ParsedChunk[MhiiHeader], device_time: TimeConversion
) -> Photo:
    representations: list[PhotoRepresentation] = []
    for child in chunk.children:
        if not isinstance(child.header, MhodHeader) or not isinstance(
            child.payload, MhodContainerPayload
        ):
            continue
        if child.header.mhod_type == PhotosMhodType.FULL_RES_IMAGE:
            kind = PhotoRepresentationKind.FULL_RESOLUTION
        elif child.header.mhod_type == PhotosMhodType.THUMBNAIL_IMAGE:
            kind = PhotoRepresentationKind.THUMBNAIL
        else:
            continue
        location = child.payload.child
        representations.append(
            PhotoRepresentation(
                kind=kind,
                format_id=location.header.format_id,
                relative_path=_location_path(location),
                offset=location.header.ithmb_offset,
                size_bytes=location.header.image_size,
                width=location.header.image_width,
                height=location.header.image_height,
                horizontal_padding=location.header.horizontal_padding,
                vertical_padding=location.header.vertical_padding,
            )
        )
    return Photo(
        photo_id=chunk.header.image_id,
        rating=chunk.header.rating,
        original_date=project_mac(chunk.header.original_date, device_time),
        taken_date=project_mac(chunk.header.exif_taken_date, device_time),
        source_size_bytes=chunk.header.source_image_size,
        representations=tuple(representations),
    )


def _project_album(
    chunk: ParsedChunk[MhbaHeader],
    persistent_track_ids: Mapping[int, int],
    device_time: TimeConversion = 0,
) -> PhotoAlbum:
    name = next(
        (
            child.payload.value
            for child in chunk.children
            if isinstance(child.header, MhodHeader)
            and isinstance(child.payload, MhodStringPayload)
            and child.header.mhod_type
            in (PhotosMhodType.ALBUM_NAME, PhotosMhodType.THUMBNAIL_IMAGE)
        ),
        "",
    )
    header = chunk.header
    return PhotoAlbum(
        album_id=header.album_id,
        name=name,
        photo_ids=tuple(
            child.header.image_id
            for child in chunk.children
            if isinstance(child.header, MhiaHeader)
        ),
        kind=(
            PhotoAlbumKind.MASTER if header.album_type == 1 else PhotoAlbumKind.ALBUM
        ),
        play_music=bool(header.play_music),
        repeat=bool(header.repeat),
        random=bool(header.random),
        show_titles=bool(header.show_titles),
        slide_duration_ms=header.slide_duration,
        transition_duration_ms=header.transition_duration,
        music_track_id=persistent_track_ids.get(header.db_track_id_ref),
        ipod=IPodPhotoAlbumDetails(
            album_type=header.album_type,
            transition_direction=header.transition_direction,
            music_db_track_id=header.db_track_id_ref,
            previous_album_id=header.previous_album_id,
        ),
    )


def _project_format(chunk: ParsedChunk[MhifHeader]) -> PhotoFileFormat:
    return PhotoFileFormat(
        format_id=chunk.header.format_id,
        image_size_bytes=chunk.header.image_size,
        relative_path=next(
            (
                normalize_photo_path(child.payload.value)
                for child in chunk.children
                if isinstance(child.header, MhodHeader)
                and isinstance(child.payload, MhodStringPayload)
                and child.header.mhod_type == PhotosMhodType.FILE_NAME
            ),
            "",
        ),
    )


def _location_path(location: ParsedChunk[MhniHeader]) -> str:
    return next(
        (
            normalize_photo_path(child.payload.value)
            for child in location.children
            if isinstance(child.header, MhodHeader)
            and isinstance(child.payload, MhodStringPayload)
            and child.header.mhod_type == PhotosMhodType.FILE_NAME
        ),
        "",
    )


def normalize_photo_path(value: str) -> str:
    """Normalize a retained filename without granting filesystem access."""
    raw = value.strip().replace("\\", "/").replace(":", "/")
    parts = tuple(part for part in raw.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    if parts[0].casefold() == "photos":
        return "/".join(("Photos", *parts[1:]))
    return "/".join(("Photos", *parts))


__all__ = ["normalize_photo_path", "project_photos"]
