"""Choose a stable Synesthesia render resolution for one display target.

The policy budgets scaled offscreen pixels rather than reacting to measured frame
times.  That keeps a given physical target and refresh rate on one deterministic
scale, so a slow frame cannot resize the feedback surfaces and erase their history.

The budget is calibrated to the existing 0.75 scale at 1920 x 1080 and 144 Hz::

    1920 * 1080 * 144 * 0.75**2 = 167_961_600 scaled pixels / second

``QRhiWidget`` schedules continuous updates at the display's presentation rate, so
the workload calculation uses the full display refresh even when the performance
target is capped at 144 Hz. Scale 0.375 is the quality floor because a 4K target at
144 Hz then uses the same
1440 x 810 offscreen field surface as that reference case.  The final presentation
pass still runs at the physical target size, retaining native output edges and
dither.  More extreme targets may exceed the budget rather than degrading the
field below that floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

MAX_RENDER_SCALE: Final = 0.75
MIN_RENDER_SCALE: Final = 0.375
MAX_TARGET_FRAME_RATE_HZ: Final = 144.0
PIXEL_THROUGHPUT_BUDGET: Final = (
    1920 * 1080 * MAX_TARGET_FRAME_RATE_HZ * MAX_RENDER_SCALE**2
)


class RenderScaleConstraint(StrEnum):
    """Explain which part of the static policy selected the render scale."""

    MAXIMUM_QUALITY = "maximum-quality"
    PIXEL_THROUGHPUT = "pixel-throughput"
    QUALITY_FLOOR = "quality-floor"


@dataclass(frozen=True, slots=True)
class RenderResolution:
    """An immutable offscreen-resolution choice and its compact diagnostics."""

    scale: float
    width_pixels: int
    height_pixels: int
    target_frame_rate_hz: float
    pixel_throughput: float
    constraint: RenderScaleConstraint


def select_render_resolution(
    width_pixels: int,
    height_pixels: int,
    display_refresh_hz: float,
) -> RenderResolution:
    """Select one history-free render resolution for a physical display target.

    ``width_pixels`` and ``height_pixels`` are the QRhi render target's physical
    pixel dimensions. ``display_refresh_hz`` must be a finite positive refresh
    rate. The returned performance target never exceeds either the display refresh
    or 144 Hz, while the workload budget accounts for the full vsynced display rate.
    """

    if width_pixels <= 0 or height_pixels <= 0:
        raise ValueError("Render-target dimensions must be positive physical pixels")
    if not math.isfinite(display_refresh_hz) or display_refresh_hz <= 0.0:
        raise ValueError("Display refresh rate must be finite and positive")

    target_frame_rate_hz = min(
        display_refresh_hz,
        MAX_TARGET_FRAME_RATE_HZ,
    )
    physical_pixel_throughput = width_pixels * height_pixels * display_refresh_hz
    budget_scale = math.sqrt(PIXEL_THROUGHPUT_BUDGET / physical_pixel_throughput)

    if budget_scale >= MAX_RENDER_SCALE:
        scale = MAX_RENDER_SCALE
        constraint = RenderScaleConstraint.MAXIMUM_QUALITY
    elif budget_scale <= MIN_RENDER_SCALE:
        scale = MIN_RENDER_SCALE
        constraint = RenderScaleConstraint.QUALITY_FLOOR
    else:
        scale = budget_scale
        constraint = RenderScaleConstraint.PIXEL_THROUGHPUT

    # Floor budget-constrained dimensions so integer texture sizes do not push the
    # actual offscreen workload above the continuous pixel-throughput calculation.
    render_width_pixels = max(2, math.floor(width_pixels * scale))
    render_height_pixels = max(2, math.floor(height_pixels * scale))
    pixel_throughput = render_width_pixels * render_height_pixels * display_refresh_hz

    return RenderResolution(
        scale=scale,
        width_pixels=render_width_pixels,
        height_pixels=render_height_pixels,
        target_frame_rate_hz=target_frame_rate_hz,
        pixel_throughput=pixel_throughput,
        constraint=constraint,
    )
