"""Prepare bounded device Photo representations from captured bytes, without I/O."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from math import ceil
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from iPodDB.library import (
    FileDependency,
    IPodPhotoAlbumDetails,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoFileFormat,
    PhotoLibrary,
    PhotoPixels,
    PhotoRepresentation,
    PhotoRepresentationKind,
    PhotoThumbnailFormat,
    PreparedPhoto,
    SourceFile,
    encode_photo_thumbnail,
)
from iPodDB.shared.photo_image import photo_source_size, photo_viewing_image
from storage import DevicePath

if TYPE_CHECKING:
    from collections.abc import Collection
    from typing import BinaryIO

MAX_PHOTO_SOURCE_BYTES = 64 * 1024 * 1024


def photo_still_from_stream(source: BinaryIO) -> bytes:
    """Decode the first display frame into a bounded PNG for oversized Photos.

    Animated sources need only their first frame for the iPod Photo viewer. Read
    it through a seekable Storage stream instead of retaining the animation.
    """
    with photo_viewing_image(source, (4096, 4096)) as image:
        output = BytesIO()
        image.save(output, format="PNG")
    data = output.getvalue()
    if len(data) > MAX_PHOTO_SOURCE_BYTES:
        raise ValueError("Prepared Photo exceeds its bounded image size.")
    return data


def prepare_sync_photo(
    data: bytes,
    *,
    photo_id: int,
    original_relative_path: str,
    thumbnail_shard: int,
    formats: tuple[PhotoThumbnailFormat, ...],
    rotate_tall_photos: bool = False,
    fit_thumbnails: bool = False,
    crop_format_ids: Collection[int] = (),
    original: Photo | None = None,
) -> PreparedPhoto:
    """Build a complete Photo with fresh, individually verifiable device files.

    The caller allocates unused paths and Storage enforces absence at publication.
    Original bytes remain unchanged; EXIF orientation, rotation and fitting affect
    only the viewing copies. ``crop_format_ids`` identifies small grid/list
    thumbnails that may crop when fitting is disabled. Every other rendition
    always preserves the whole source. Each fresh shard avoids a read/rewrite of
    old USB data.
    """

    if not data or len(data) > MAX_PHOTO_SOURCE_BYTES:
        raise ValueError("Photo exceeds the 64 MiB source limit; resize it and retry.")
    if not 0 < photo_id < 0xFFFFFFFF or not 0 < thumbnail_shard <= 0xFFFFFFFF:
        raise ValueError(
            "Photo and thumbnail shard identities must be positive u32 values."
        )
    path = DevicePath(original_relative_path)
    if len(path.parts) < 3 or not path.is_relative_to(
        DevicePath("Photos/Full Resolution")
    ):
        raise ValueError("A Photo original must be inside Photos/Full Resolution.")
    if not formats or len({item.format_id for item in formats}) != len(formats):
        raise ValueError("The iPod requires an unambiguous set of Photo formats.")
    crop_ids: set[int] = set() if fit_thumbnails else set(crop_format_ids)
    try:
        width, height = photo_source_size(BytesIO(data))
        # A working raster needs only enough pixels for the largest rendition.
        # Keep source dimensions and bytes separately for the retained original.
        edge = max(max(item.width, item.height) for item in formats)
        if crop_ids:
            crop_edge = max(
                (
                    max(item.width, item.height)
                    for item in formats
                    if item.format_id in crop_ids
                ),
                default=0,
            )
            # A panorama's short edge must still contain enough pixels for a
            # cropped thumbnail, including when its display orientation rotates.
            edge = max(edge, ceil(crop_edge * max(width, height) / min(width, height)))
        image = photo_viewing_image(BytesIO(data), (edge, edge))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError(
            "Photo could not be decoded; repair or replace the source image."
        ) from error
    files = [_source_file(str(path), data)]
    representations = [
        PhotoRepresentation(
            PhotoRepresentationKind.FULL_RESOLUTION,
            1,
            str(path),
            0,
            len(data),
            width,
            height,
        )
    ]
    for image_format in formats:
        source = image
        target_size = (image_format.width, image_format.height)
        if rotate_tall_photos and _rotation_improves_fit(image.size, target_size):
            source = image.transpose(Image.Transpose.ROTATE_270)
        # Only explicitly identified small grid/list thumbnails may crop.
        if image_format.format_id not in crop_ids:
            source, horizontal_padding, vertical_padding = _fit_thumbnail(
                source, target_size
            )
        else:
            source = ImageOps.fit(source, target_size, Image.Resampling.LANCZOS)
            horizontal_padding = 0
            vertical_padding = 0
        encoded = encode_photo_thumbnail(
            PhotoPixels(source.width, source.height, source.tobytes()),
            image_format,
            horizontal_padding=horizontal_padding,
            vertical_padding=vertical_padding,
        )
        thumbnail_path = (
            f"Photos/Thumbs/F{image_format.format_id}_{thumbnail_shard}.ithmb"
        )
        files.append(_source_file(thumbnail_path, encoded))
        representations.append(
            PhotoRepresentation(
                PhotoRepresentationKind.THUMBNAIL,
                image_format.format_id,
                thumbnail_path,
                0,
                len(encoded),
                image_format.width - horizontal_padding,
                image_format.height - vertical_padding,
                horizontal_padding,
                vertical_padding,
            )
        )
    photo = replace(
        original or Photo(photo_id),
        photo_id=photo_id,
        source_size_bytes=len(data),
        representations=tuple(representations),
    )
    return PreparedPhoto(photo, tuple(files))


def photo_library_with_asset(
    original: PhotoLibrary | None,
    prepared: PreparedPhoto,
    *,
    master_album_id: int = 100,
) -> PhotoLibrary:
    """Replace or append one Photo while preserving retained Album memberships."""

    library = original or PhotoLibrary()
    photo = prepared.photo
    exists = any(item.photo_id == photo.photo_id for item in library.photos)
    photos = tuple(
        photo if item.photo_id == photo.photo_id else item for item in library.photos
    )
    if not exists:
        photos = (*photos, photo)
    masters = tuple(
        album for album in library.albums if album.kind is PhotoAlbumKind.MASTER
    )
    if not masters and original is not None:
        raise ValueError(
            "The Photo Library has no Master Album; repair it before Sync."
        )
    if len(masters) > 1:
        raise ValueError(
            "The Photo Library has multiple Master Albums; repair it before Sync."
        )
    if masters:
        albums = tuple(
            replace(album, photo_ids=(*album.photo_ids, photo.photo_id))
            if album.kind is PhotoAlbumKind.MASTER
            and photo.photo_id not in album.photo_ids
            else album
            for album in library.albums
        )
    else:
        albums = (
            PhotoAlbum(
                master_album_id,
                "Photo Library",
                (photo.photo_id,),
                PhotoAlbumKind.MASTER,
                ipod=IPodPhotoAlbumDetails(album_type=1),
            ),
        )
    formats = list(library.formats)
    known_formats = {item.format_id for item in formats}
    for representation in photo.representations:
        if (
            representation.kind is PhotoRepresentationKind.THUMBNAIL
            and representation.format_id not in known_formats
        ):
            formats.append(
                PhotoFileFormat(representation.format_id, representation.size_bytes)
            )
            known_formats.add(representation.format_id)
    return PhotoLibrary(photos, albums, tuple(formats))


def _rotation_improves_fit(source: tuple[int, int], target: tuple[int, int]) -> bool:
    width, height = source
    if height < width * 1.15:
        return False
    scale = min(target[0] / width, target[1] / height)
    rotated_scale = min(target[0] / height, target[1] / width)
    return rotated_scale * rotated_scale >= scale * scale * 1.2


def _fit_thumbnail(
    image: Image.Image, target: tuple[int, int]
) -> tuple[Image.Image, int, int]:
    """Resize a Photo to the visible symmetric region of a thumbnail frame."""

    target_width, target_height = target
    scale = min(target_width / image.width, target_height / image.height)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    # PhotosDB stores one equal margin on both sides. Adjust the fitted raster
    # by at most one pixel so the physical frame can be represented exactly.
    if (target_width - width) % 2:
        width = width - 1 if width > 1 else width + 1
    if (target_height - height) % 2:
        height = height - 1 if height > 1 else height + 1
    resized = image.resize((width, height), Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    return resized, (target_width - width) // 2, (target_height - height) // 2


def _source_file(path: str, data: bytes) -> SourceFile:
    return SourceFile(
        FileDependency(path, len(data), hashlib.sha256(data).hexdigest()), data
    )
