"""Device artwork knowledge belongs to immutable Device Profiles."""

from dataclasses import replace

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    ArtworkPixelFormat,
    ArtworkUsage,
)


def test_device_profiles_assign_product_images_and_cover_formats() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    nano_7g = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MKMV2")

    assert classic is not None
    assert classic.product_image == "iPod11B-Black.png"
    assert {
        artwork_format.format_id
        for artwork_format in classic.capabilities.artwork.cover_formats
    } == {1055, 1060, 1061, 1068}
    small_classic = classic.capabilities.artwork.cover_format(1061)
    assert small_classic is not None
    assert (small_classic.width, small_classic.height, small_classic.row_bytes) == (
        56,
        56,
        112,
    )

    assert nano_7g is not None
    assert nano_7g.product_image == "iPod18A-Pink.png"
    nano_tiny = nano_7g.capabilities.artwork.cover_format(1013)
    assert nano_tiny is not None
    assert (nano_tiny.width, nano_tiny.height, nano_tiny.row_bytes) == (50, 50, 100)
    assert nano_tiny.pixel_format is ArtworkPixelFormat.RGB565_LE


def test_every_catalog_profile_has_a_safe_product_image_name() -> None:
    for profile in DEFAULT_DEVICE_REGISTRY.profiles:
        assert profile.product_image.endswith(".png")
        assert "/" not in profile.product_image
        assert "\\" not in profile.product_image


def test_only_classic_profiles_declare_the_source_supported_chapter_layouts() -> None:
    classic_generations: set[str] = set()
    for profile in DEFAULT_DEVICE_REGISTRY.profiles:
        artwork = profile.capabilities.artwork
        if profile.family != "iPod Classic":
            assert artwork.chapter_formats == ()
            continue
        classic_generations.add(profile.generation)
        assert artwork.supports_chapter_images
        assert tuple(f.format_id for f in artwork.cover_formats) == (
            1055,
            1060,
            1061,
            1068,
        )
        assert tuple(
            (f.format_id, f.width, f.height, f.row_bytes, f.pixel_format, f.usage)
            for f in artwork.chapter_formats
        ) == (
            (1055, 128, 128, 256, ArtworkPixelFormat.RGB565_LE, ArtworkUsage.CHAPTER),
            (1029, 200, 200, 400, ArtworkPixelFormat.RGB565_LE, ArtworkUsage.CHAPTER),
        )
        assert all(f.usage is ArtworkUsage.COVER for f in artwork.cover_formats)
    assert classic_generations == {"6th Gen", "6.5th Gen", "7th Gen"}


def test_chapter_layouts_require_support_and_the_chapter_role() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert classic is not None
    artwork = classic.capabilities.artwork
    with pytest.raises(ValueError, match="require chapter-image support"):
        replace(artwork, supports_chapter_images=False)
    with pytest.raises(ValueError, match="chapter artwork role"):
        replace(artwork, chapter_formats=artwork.cover_formats)
    with pytest.raises(ValueError, match="cover or chapter artwork roles"):
        replace(artwork, photo_formats=artwork.chapter_formats)


def test_screenless_profiles_do_not_claim_an_application_display_format() -> None:
    mini = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9160")

    assert mini is not None
    artwork = mini.capabilities.artwork
    assert not artwork.supports_cover_art
    assert artwork.cover_formats == ()
    assert artwork.cover_format(1060) is None


def test_catalog_has_a_creation_policy_for_every_cover_capable_profile() -> None:
    for profile in DEFAULT_DEVICE_REGISTRY.profiles:
        artwork = profile.capabilities.artwork
        nano_6 = profile.family == "iPod Nano" and profile.generation == "6th Gen"
        assert artwork.artwork_root_value == (
            (2 if nano_6 else 6) if artwork.supports_cover_art else None
        )
        assert artwork.include_auxiliary_image_records is not nano_6
        assert (
            artwork.photo_album_creation_type is not None
        ) is artwork.supports_photos
        if artwork.supports_photos:
            assert artwork.photo_album_creation_type == (
                6
                if profile.family == "iPod Nano"
                and profile.generation in {"6th Gen", "7th Gen"}
                else 2
            )


def test_f1019_catalog_format_declares_field_separated_uyvy() -> None:
    formats = {
        artwork_format.format_id: artwork_format
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        for artwork_format in profile.capabilities.artwork.photo_formats
    }

    assert formats[1019].pixel_format is ArtworkPixelFormat.UYVY_FIELDS


def test_catalog_marks_only_small_photo_grid_and_list_formats_as_thumbnails() -> None:
    formats = {
        artwork_format.format_id: artwork_format
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        for artwork_format in profile.capabilities.artwork.photo_formats
    }

    assert {
        format_id
        for format_id, artwork_format in formats.items()
        if artwork_format.usage is ArtworkUsage.PHOTO_THUMBNAIL
    } == {1005, 1009, 1032, 1036, 1066, 1079, 1092}
    assert formats[1015].usage is ArtworkUsage.PHOTO
    assert formats[1024].usage is ArtworkUsage.PHOTO


def test_nano_5g_identifies_both_small_photo_formats_as_thumbnails() -> None:
    profiles = tuple(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.family == "iPod Nano" and profile.generation == "5th Gen"
    )

    assert profiles
    for profile in profiles:
        assert {
            artwork_format.format_id
            for artwork_format in profile.capabilities.artwork.photo_formats
            if artwork_format.usage is ArtworkUsage.PHOTO_THUMBNAIL
        } == {1066, 1079}
        assert {
            artwork_format.format_id
            for artwork_format in profile.capabilities.artwork.photo_formats
            if artwork_format.usage is ArtworkUsage.PHOTO
        } == {1087}
