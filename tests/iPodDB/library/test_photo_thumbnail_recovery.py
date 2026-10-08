"""A malformed thumbnail must not hide another usable retained representation."""

from dataclasses import replace

import pytest

from iPodDB.library import (
    Photo,
    PhotoPixelFormat,
    PhotoRepresentation,
    PhotoRepresentationKind,
    PhotoThumbnailFormat,
    select_photo_thumbnail,
)


@pytest.mark.parametrize(
    "field,value",
    (
        ("horizontal_padding", -1),
        ("vertical_padding", -1),
        ("horizontal_padding", 2),
        ("vertical_padding", 2),
        ("offset", -1),
        ("size_bytes", 0),
    ),
)
def test_photo_thumbnail_selection_falls_back_from_invalid_retained_range(
    field: str, value: int
) -> None:
    first = PhotoRepresentation(
        PhotoRepresentationKind.THUMBNAIL,
        1017,
        "Photos/Thumbs/F1017_1.ithmb",
        0,
        32,
        4,
        4,
    )
    bad = replace(
        first,
        horizontal_padding=value
        if field == "horizontal_padding"
        else first.horizontal_padding,
        vertical_padding=value
        if field == "vertical_padding"
        else first.vertical_padding,
        offset=value if field == "offset" else first.offset,
        size_bytes=value if field == "size_bytes" else first.size_bytes,
    )
    healthy = PhotoRepresentation(
        PhotoRepresentationKind.THUMBNAIL,
        1023,
        "Photos/Thumbs/F1023_1.ithmb",
        128,
        128,
        8,
        8,
    )
    photo = Photo(100, representations=(bad, healthy))
    formats = (
        PhotoThumbnailFormat(1017, 4, 4, 8, PhotoPixelFormat.RGB565_LE),
        PhotoThumbnailFormat(1023, 8, 8, 16, PhotoPixelFormat.RGB565_LE),
    )

    read = select_photo_thumbnail(photo, formats, 4)

    assert read is not None
    assert (read.format_id, read.offset, read.length) == (1023, 128, 128)
    assert read.decode(bytes(128)).rgb888 == bytes(8 * 8 * 3)
    assert select_photo_thumbnail(photo, formats, 4, format_id=1017) is None
    assert photo.representations == (bad, healthy)
