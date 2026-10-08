"""Verify complete Photo asset resources before any PhotosDB reconciliation."""

from __future__ import annotations

import re
from io import BytesIO
from itertools import pairwise
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

from iPodDB.ArtworkDB.ithmb import IthmbLayout, IthmbPaddingMode, decode_ithmb
from iPodDB.library._artwork_writing import validated_path
from iPodDB.library.file_content import content_sha256, read_content
from iPodDB.library.photos import PhotoRepresentationKind
from iPodDB.library.writing import WriteIssue

if TYPE_CHECKING:
    from iPodDB.library.photos import PhotoLibrary
    from iPodDB.library.writing import (
        FileDependency,
        LibraryWritePlan,
        PreparedPhoto,
        SourceFile,
        WriteResources,
    )


def validate_photos(
    plan: LibraryWritePlan, resources: WriteResources, original: PhotoLibrary | None
) -> tuple[WriteIssue, ...]:
    desired = plan.draft.snapshot.photos
    photos = (
        {} if desired is None else {photo.photo_id: photo for photo in desired.photos}
    )
    assets = {asset.photo.photo_id: asset for asset in resources.photos}
    issues: list[WriteIssue] = []
    if len(assets) != len(resources.photos):
        issues.append(_issue("Prepared Photos repeat an identity."))
    if set(assets) != set(plan.required_photos):
        issues.append(
            _issue("Supply exactly the Photo assets requested by this draft.")
        )
    original_paths = {
        representation.relative_path.casefold()
        for photo in (() if original is None else original.photos)
        for representation in photo.representations
    }
    verified: dict[str, SourceFile] = {}
    prefixes: dict[str, FileDependency | None] = {}
    ranges: dict[str, list[tuple[int, int, int]]] = {}
    for photo_id, asset in assets.items():
        try:
            if photos.get(photo_id) != asset.photo:
                raise ValueError(
                    "Prepared Photo does not match the desired Library Photo."
                )
            asset_prefixes = {
                item.relative_path.casefold(): item for item in asset.file_prefixes
            }
            if len(asset_prefixes) != len(asset.file_prefixes) or not set(
                asset_prefixes
            ).issubset(
                item.dependency.relative_path.casefold() for item in asset.files
            ):
                raise ValueError(
                    "Photo shard prefixes must identify unique supplied files."
                )
            for source in asset.files:
                dependency = source.dependency
                validated_path(dependency.relative_path)
                normalized = dependency.relative_path.casefold()
                prefix = asset_prefixes.get(normalized)
                prior = verified.get(normalized)
                if prior is not None and (
                    prior.dependency != dependency or prefixes[normalized] != prefix
                ):
                    raise ValueError(
                        "Shared Photo files have conflicting content or prefix evidence."
                    )
                if normalized in original_paths and prefix is None:
                    raise ValueError(
                        "An existing Photo file requires verified prefix evidence."
                    )
                if prior is not source:
                    if (
                        not len(source.data)
                        or len(source.data) != dependency.size
                        or content_sha256(source.data) != dependency.sha256
                    ):
                        raise ValueError(
                            "Photo bytes do not match their captured size and SHA-256."
                        )
                    if prefix is not None and (
                        not re.fullmatch(
                            r"Photos/Thumbs/F[1-9][0-9]*_[1-9][0-9]*\.ithmb",
                            prefix.relative_path,
                            re.IGNORECASE,
                        )
                        or not 0 < prefix.size < len(source.data)
                        or content_sha256(source.data, length=prefix.size)
                        != prefix.sha256
                    ):
                        raise ValueError(
                            "A Photo shard must preserve its entire captured prefix."
                        )
                    verified[normalized] = source
                    prefixes[normalized] = prefix
            _validate_asset(asset, plan)
            for rep in asset.photo.representations:
                normalized = rep.relative_path.casefold()
                prefix = asset_prefixes.get(normalized)
                if prefix is not None and (
                    rep.kind is not PhotoRepresentationKind.THUMBNAIL
                    or rep.offset < prefix.size
                ):
                    raise ValueError(
                        "New Photo ranges must follow the retained shard prefix."
                    )
                extents = ranges.setdefault(normalized, [])
                end = rep.offset + rep.size_bytes
                extents.append((rep.offset, end, photo_id))
        except (ValueError, OverflowError) as error:
            issues.append(_issue(str(error), photo_id))
    for extents in ranges.values():
        for previous, following in pairwise(sorted(extents)):
            if previous[1] > following[0]:
                issues.append(
                    _issue(
                        "Prepared Photo representations overlap in a shared file.",
                        following[2],
                    )
                )
                break
    return tuple(issues)


def _validate_asset(asset: PreparedPhoto, plan: LibraryWritePlan) -> None:
    files = {source.dependency.relative_path: source for source in asset.files}
    photo = asset.photo
    formats = {
        image_format.format_id: image_format
        for image_format in plan.target.photo_formats
    }
    if not formats:
        raise ValueError("The Device Profile does not declare supported Photo formats.")
    if len(files) != len(asset.files):
        raise ValueError("A Prepared Photo repeats a file path.")
    required = {
        representation.relative_path for representation in photo.representations
    }
    if required != set(files):
        raise ValueError("Prepared Photo files must exactly cover its representations.")
    originals = tuple(
        rep
        for rep in photo.representations
        if rep.kind is PhotoRepresentationKind.FULL_RESOLUTION
    )
    thumbnails = tuple(
        rep
        for rep in photo.representations
        if rep.kind is PhotoRepresentationKind.THUMBNAIL
    )
    if (
        len(originals) != 1
        or len(thumbnails) != len(formats)
        or {rep.format_id for rep in thumbnails} != set(formats)
    ):
        raise ValueError(
            "A Prepared Photo requires one original and every device thumbnail format."
        )
    for representation in photo.representations:
        source = files[representation.relative_path]
        if (
            not 0 <= representation.offset <= 0xFFFFFFFF
            or not 0 < representation.size_bytes <= 0xFFFFFFFF
            or representation.offset + representation.size_bytes > len(source.data)
        ):
            raise ValueError(
                "Photo representations must fit within their captured file."
            )
        full_resolution = representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
        if (
            not 0 < representation.width <= (0xFFFF if full_resolution else 8192)
            or not 0 < representation.height <= (0xFFFF if full_resolution else 8192)
            or (
                not full_resolution
                and representation.width * representation.height > 32 * 1024 * 1024
            )
        ):
            raise ValueError(
                "Photo dimensions must fit their original or thumbnail representation."
            )
        if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION:
            if (
                representation.offset != 0
                or representation.size_bytes != len(source.data)
                or representation.horizontal_padding
                or representation.vertical_padding
                or representation.horizontal_padding < 0
                or representation.vertical_padding < 0
                or not representation.relative_path.startswith(
                    "Photos/Full Resolution/"
                )
                or representation.format_id != 1
                or photo.source_size_bytes != representation.size_bytes
                or representation.size_bytes > 64 * 1024 * 1024
            ):
                raise ValueError(
                    "Photo original must preserve the captured source size inside Photos/Full Resolution."
                )
            try:
                with Image.open(
                    BytesIO(read_content(source.data, 0, len(source.data)))
                ) as image:
                    if image.size != (representation.width, representation.height):
                        raise ValueError(
                            "Photo original dimensions differ from its captured metadata."
                        )
                    image.verify()
            except (
                UnidentifiedImageError,
                OSError,
                Image.DecompressionBombError,
            ) as error:
                raise ValueError("Photo original failed image verification.") from error
            continue
        image_format = formats[representation.format_id]
        if (
            not 0
            < len(source.data)
            <= min(plan.target.max_photo_file_bytes, 0xFFFFFFFF)
        ):
            raise ValueError("Photo thumbnail shard exceeds the configured byte limit.")
        horizontal_padding = representation.horizontal_padding
        vertical_padding = representation.vertical_padding
        if (
            horizontal_padding < 0
            or vertical_padding < 0
            or horizontal_padding * 2 >= image_format.width
            or vertical_padding * 2 >= image_format.height
        ):
            raise ValueError("Photo thumbnail padding leaves no visible raster.")
        pattern = rf"Photos/Thumbs/F{image_format.format_id}_[1-9][0-9]*\.ithmb"
        if not re.fullmatch(pattern, representation.relative_path, re.IGNORECASE):
            raise ValueError(
                "Photo thumbnails must use the device's F<format>_<shard>.ithmb namespace."
            )
        if (representation.width, representation.height) != (
            image_format.width - horizontal_padding,
            image_format.height - vertical_padding,
        ):
            raise ValueError(
                "Photo dimensions do not match the Device Profile format and padding."
            )
        symmetric = bool(horizontal_padding or vertical_padding)
        decoded = decode_ithmb(
            read_content(source.data, representation.offset, representation.size_bytes),
            IthmbLayout(
                representation.width,
                representation.height,
                image_format.row_bytes,
                image_format.pixel_format,
                horizontal_padding=horizontal_padding,
                vertical_padding=vertical_padding,
                padding_mode=(
                    IthmbPaddingMode.SYMMETRIC
                    if symmetric
                    else IthmbPaddingMode.TRAILING
                ),
            ),
        )
        if (decoded.width, decoded.height) != (
            representation.width - horizontal_padding,
            representation.height - vertical_padding,
        ):
            raise ValueError("Decoded Photo thumbnail has unexpected dimensions.")
        desired = plan.draft.snapshot.photos
        declared = (
            None
            if desired is None
            else next(
                (
                    item
                    for item in desired.formats
                    if item.format_id == representation.format_id
                ),
                None,
            )
        )
        if declared is None:
            raise ValueError(
                f"Photo format {representation.format_id} is missing from the "
                "prepared PhotosDB metadata."
            )
        if declared.image_size_bytes != representation.size_bytes:
            raise ValueError(
                f"Photo format {representation.format_id} declares "
                f"{declared.image_size_bytes} bytes, but the prepared "
                f"representation contains {representation.size_bytes} bytes."
            )


def _issue(message: str, identity: int | None = None) -> WriteIssue:
    return WriteIssue(
        "resources.invalid_photo",
        message,
        subject="photo",
        record_id=identity,
        artifact="PhotosDB",
    )
