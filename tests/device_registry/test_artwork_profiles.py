"""Device artwork knowledge belongs to immutable Device Profiles."""

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    ArtworkPixelFormat,
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
        assert artwork.artwork_root_value == (6 if artwork.supports_cover_art else None)
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
