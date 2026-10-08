"""Photo viewing renditions preserve the whole source independently of grid fitting."""

from io import BytesIO

import pytest
from PIL import Image

from device_registry import DEFAULT_DEVICE_REGISTRY, ArtworkFormat, ArtworkUsage
from iOpenPod.app.media.photo_sync import prepare_sync_photo
from iPodDB.library import (
    PhotoPixelFormat,
    PhotoThumbnailFormat,
    select_photo_thumbnail,
)


@pytest.mark.parametrize("fit_thumbnails", [False, True])
def test_classic_screen_photo_preserves_edges(fit_thumbnails: bool) -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    formats = tuple(
        PhotoThumbnailFormat(
            item.format_id,
            item.width,
            item.height,
            item.row_bytes,
            PhotoPixelFormat(item.pixel_format.value),
        )
        for item in profile.capabilities.artwork.photo_formats
    )
    with Image.new("RGB", (40, 160), "green") as image:
        image.paste("red", (0, 0, 40, 40))
        image.paste("blue", (0, 120, 40, 160))
        output = BytesIO()
        image.save(output, format="PNG")
    asset = prepare_sync_photo(
        output.getvalue(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/portrait.png",
        thumbnail_shard=1,
        formats=formats,
        fit_thumbnails=fit_thumbnails,
    )

    representation = next(
        item for item in asset.photo.representations if item.format_id == 1024
    )
    assert representation.horizontal_padding > 0
    read = select_photo_thumbnail(asset.photo, formats, 320, format_id=1024)
    assert read is not None
    file = next(
        item
        for item in asset.files
        if item.dependency.relative_path == read.relative_path
    )
    assert isinstance(file.data, bytes)
    pixels = read.decode(file.data)
    assert pixels.rgb888[:3] == b"\xff\x00\x00"
    assert pixels.rgb888[-3:] == b"\x00\x00\xff"


_PHOTO_FORMAT_GROUPS = tuple(
    dict.fromkeys(
        profile.capabilities.artwork.photo_formats
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.capabilities.artwork.supports_photos
    )
)
_SMALL_FORMAT_IDS = {1005, 1009, 1032, 1036, 1066, 1079, 1092}


@pytest.mark.parametrize("catalog_formats", _PHOTO_FORMAT_GROUPS)
@pytest.mark.parametrize("fit_thumbnails", [False, True])
@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("landscape", [False, True])
def test_only_small_photo_formats_may_crop(
    catalog_formats: tuple[ArtworkFormat, ...],
    fit_thumbnails: bool,
    rotate: bool,
    landscape: bool,
) -> None:
    formats = tuple(
        PhotoThumbnailFormat(
            item.format_id,
            item.width,
            item.height,
            item.row_bytes,
            PhotoPixelFormat(item.pixel_format.value),
        )
        for item in catalog_formats
    )
    with Image.new("RGB", (40, 160), "green") as portrait:
        portrait.paste("red", (0, 0, 40, 40))
        portrait.paste("blue", (0, 120, 40, 160))
        image = portrait.transpose(Image.Transpose.ROTATE_90) if landscape else portrait
        output = BytesIO()
        image.save(output, format="PNG")
    data = output.getvalue()
    asset = prepare_sync_photo(
        data,
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/source.png",
        thumbnail_shard=1,
        formats=formats,
        fit_thumbnails=fit_thumbnails,
        rotate_tall_photos=rotate,
        crop_format_ids={
            item.format_id
            for item in catalog_formats
            if item.usage is ArtworkUsage.PHOTO_THUMBNAIL
        },
    )
    assert asset.files[0].data == data
    for representation, file in zip(
        asset.photo.representations[1:], asset.files[1:], strict=True
    ):
        cropped = not fit_thumbnails and representation.format_id in _SMALL_FORMAT_IDS
        padding = representation.horizontal_padding + representation.vertical_padding
        assert (padding == 0) is cropped, representation
        read = select_photo_thumbnail(
            asset.photo, formats, 1024, format_id=representation.format_id
        )
        assert read is not None
        assert isinstance(file.data, bytes)
        pixels = read.decode(file.data)
        corners = (pixels.rgb888[:3], pixels.rgb888[-3:])
        if cropped:
            assert all(red < 30 and blue < 30 for red, _, blue in corners)
        else:
            # Both source ends must survive, including rotated and YUV renditions.
            assert any(red > 200 and blue < 30 for red, _, blue in corners)
            assert any(blue > 200 and red < 30 for red, _, blue in corners)


@pytest.mark.parametrize("crop_format_ids", [(), (9998,)])
def test_crop_policy_is_explicit_even_for_a_single_small_format(
    crop_format_ids: tuple[int, ...],
) -> None:
    image_format = PhotoThumbnailFormat(9998, 8, 8, 16, PhotoPixelFormat.RGB565_LE)
    with Image.new("RGB", (40, 160), "red") as image:
        output = BytesIO()
        image.save(output, format="PNG")
    asset = prepare_sync_photo(
        output.getvalue(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/source.png",
        thumbnail_shard=1,
        formats=(image_format,),
        crop_format_ids=crop_format_ids,
    )
    representation = asset.photo.representations[1]
    assert representation.horizontal_padding == (0 if crop_format_ids else 3)
