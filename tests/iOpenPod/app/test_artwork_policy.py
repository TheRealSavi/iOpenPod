"""Application artwork layouts remain distinct from native Device capabilities."""

from dataclasses import replace

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY, ArtworkUsage
from iOpenPod.app.artwork_policy import (
    application_artwork_formats,
    application_artwork_read_formats,
    application_artwork_root_value,
    application_chapter_formats,
    application_cover_formats,
    rockbox_artwork,
)
from iPodDB.library import ArtworkPixels


def test_non_cover_profiles_receive_one_iopenpod_display_layout() -> None:
    mini = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9802")

    assert mini is not None
    assert not mini.capabilities.artwork.supports_cover_art
    assert tuple(f.format_id for f in application_artwork_formats(mini)) == (1060,)
    assert tuple(f.format_id for f in application_cover_formats(mini)) == (1060,)
    assert application_chapter_formats(mini) == ()
    assert application_artwork_read_formats(mini) == application_cover_formats(mini)
    assert application_artwork_root_value(mini) == 2


def test_native_cover_profiles_keep_their_declared_layouts_and_root() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")

    assert classic is not None
    assert tuple(f.format_id for f in application_artwork_formats(classic)) == (
        1055,
        1060,
        1061,
        1068,
    )
    assert application_artwork_root_value(classic) == 6


def test_classic_chapter_layouts_are_separate_writes_and_combined_reads() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert classic is not None
    assert tuple(f.format_id for f in application_cover_formats(classic)) == (
        1055,
        1060,
        1061,
        1068,
    )
    assert tuple(f.format_id for f in application_chapter_formats(classic)) == (
        1055,
        1029,
    )
    assert tuple(f.format_id for f in application_artwork_read_formats(classic)) == (
        1055,
        1060,
        1061,
        1068,
        1029,
    )
    chapter = application_chapter_formats(classic)[1]
    assert (chapter.width, chapter.height, chapter.row_bytes) == (200, 200, 400)


def test_read_layouts_reject_conflicting_cover_and_chapter_definitions() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert classic is not None
    original = classic.capabilities.artwork
    profile = classic.with_capabilities(
        replace(
            classic.capabilities,
            artwork=replace(
                original,
                chapter_formats=(
                    replace(
                        original.cover_formats[0], width=100, usage=ArtworkUsage.CHAPTER
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="layouts conflict"):
        application_artwork_read_formats(profile)


def test_non_cover_profiles_get_a_compact_grayscale_rockbox_cover() -> None:
    mini = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9802")
    assert mini is not None
    pixels = ArtworkPixels(
        240,
        240,
        bytes(
            component
            for index in range(240 * 240)
            for component in (index % 256, (index * 3) % 256, 255 - index % 256)
        ),
    )

    compact = rockbox_artwork(mini, pixels)

    assert (compact.width, compact.height) == (120, 120)
    assert all(
        compact.rgb888[offset]
        == compact.rgb888[offset + 1]
        == compact.rgb888[offset + 2]
        for offset in range(0, len(compact.rgb888), 3)
    )
    assert len(compact.rgb888) == 120 * 120 * 3


def test_native_profiles_keep_the_full_color_rockbox_cover() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert classic is not None
    pixels = ArtworkPixels(2, 2, bytes((20, 80, 140)) * 4)

    assert rockbox_artwork(classic, pixels) is pixels
