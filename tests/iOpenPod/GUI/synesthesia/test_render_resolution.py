"""Static pixel-throughput policy for the Synesthesia render surfaces."""

import math

import pytest

from iOpenPod.GUI.synesthesia.render_resolution import (
    MAX_RENDER_SCALE,
    MAX_TARGET_FRAME_RATE_HZ,
    MIN_RENDER_SCALE,
    PIXEL_THROUGHPUT_BUDGET,
    RenderScaleConstraint,
    select_render_resolution,
)


def test_reference_1080p_at_144_hz_retains_the_existing_scale() -> None:
    resolution = select_render_resolution(1920, 1080, 144.0)

    assert resolution.scale == MAX_RENDER_SCALE
    assert (resolution.width_pixels, resolution.height_pixels) == (1440, 810)
    assert resolution.target_frame_rate_hz == 144.0
    assert resolution.pixel_throughput == PIXEL_THROUGHPUT_BUDGET
    assert resolution.constraint is RenderScaleConstraint.MAXIMUM_QUALITY


@pytest.mark.parametrize(
    ("width_pixels", "height_pixels", "refresh_hz"),
    [
        (1280, 720, 144.0),
        (1920, 1080, 60.0),
        (2560, 1440, 60.0),
        (3840, 2160, 30.0),
    ],
)
def test_targets_within_the_reference_throughput_keep_maximum_quality(
    width_pixels: int,
    height_pixels: int,
    refresh_hz: float,
) -> None:
    resolution = select_render_resolution(
        width_pixels,
        height_pixels,
        refresh_hz,
    )

    assert resolution.scale == MAX_RENDER_SCALE
    assert resolution.constraint is RenderScaleConstraint.MAXIMUM_QUALITY


def test_display_refresh_above_144_hz_keeps_headroom_for_vsynced_updates() -> None:
    resolution = select_render_resolution(1920, 1080, 165.0)
    expected = math.sqrt(PIXEL_THROUGHPUT_BUDGET / (1920 * 1080 * 165.0))

    assert resolution.target_frame_rate_hz == MAX_TARGET_FRAME_RATE_HZ
    assert resolution.scale == pytest.approx(expected)
    assert resolution.scale < MAX_RENDER_SCALE
    assert resolution.pixel_throughput <= PIXEL_THROUGHPUT_BUDGET
    assert resolution.constraint is RenderScaleConstraint.PIXEL_THROUGHPUT


def test_scale_reduces_progressively_with_high_pixel_throughput() -> None:
    four_k_60 = select_render_resolution(3840, 2160, 60.0)
    four_k_120 = select_render_resolution(3840, 2160, 120.0)
    four_k_144 = select_render_resolution(3840, 2160, 144.0)

    assert MAX_RENDER_SCALE > four_k_60.scale > four_k_120.scale > MIN_RENDER_SCALE
    assert four_k_144.scale == MIN_RENDER_SCALE
    assert four_k_60.constraint is RenderScaleConstraint.PIXEL_THROUGHPUT
    assert four_k_120.constraint is RenderScaleConstraint.PIXEL_THROUGHPUT
    assert four_k_144.constraint is RenderScaleConstraint.QUALITY_FLOOR
    assert four_k_60.pixel_throughput <= PIXEL_THROUGHPUT_BUDGET
    assert four_k_120.pixel_throughput <= PIXEL_THROUGHPUT_BUDGET
    assert four_k_144.pixel_throughput == PIXEL_THROUGHPUT_BUDGET


def test_budget_scale_follows_the_square_root_of_pixel_throughput() -> None:
    resolution = select_render_resolution(3440, 1440, 144.0)
    expected = math.sqrt(PIXEL_THROUGHPUT_BUDGET / (3440 * 1440 * 144.0))

    assert resolution.scale == pytest.approx(expected)
    assert resolution.constraint is RenderScaleConstraint.PIXEL_THROUGHPUT
    assert resolution.pixel_throughput <= PIXEL_THROUGHPUT_BUDGET


def test_quality_floor_preserves_a_defensible_surface_on_extreme_targets() -> None:
    resolution = select_render_resolution(7680, 4320, 144.0)

    assert resolution.scale == MIN_RENDER_SCALE
    assert (resolution.width_pixels, resolution.height_pixels) == (2880, 1620)
    assert resolution.constraint is RenderScaleConstraint.QUALITY_FLOOR
    assert resolution.pixel_throughput > PIXEL_THROUGHPUT_BUDGET


def test_selection_is_deterministic_and_has_no_runtime_history() -> None:
    reference = select_render_resolution(3840, 2160, 120.0)

    select_render_resolution(7680, 4320, 144.0)
    repeated = select_render_resolution(3840, 2160, 120.0)

    assert repeated == reference


@pytest.mark.parametrize(
    ("width_pixels", "height_pixels", "refresh_hz"),
    [
        (0, 1080, 60.0),
        (1920, 0, 60.0),
        (-1, 1080, 60.0),
        (1920, 1080, 0.0),
        (1920, 1080, math.inf),
        (1920, 1080, math.nan),
    ],
)
def test_invalid_physical_targets_are_rejected(
    width_pixels: int,
    height_pixels: int,
    refresh_hz: float,
) -> None:
    with pytest.raises(ValueError):
        select_render_resolution(width_pixels, height_pixels, refresh_hz)
