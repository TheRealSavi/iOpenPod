"""Cover intent and a byte-only rendering seam for qualified native Mix artwork."""

from collections.abc import Callable

from device_registry import DeviceProfile, FeatureSupport
from iOpenPod.app.genius_mixes import MixState
from iPodDB.library import (
    ArtworkPixels,
    CoverFormat,
    CoverPixelFormat,
    GeniusMixArtwork,
)

type MixCoverRenderer = Callable[[str, int], ArtworkPixels]


def mix_artwork_format(profile: DeviceProfile) -> CoverFormat | None:
    if (
        profile.capabilities.genius.mix_artwork is not FeatureSupport.SUPPORTED
        or profile.capabilities.genius.mixes is not FeatureSupport.SUPPORTED
    ):
        return None
    if profile.family == "iPod Classic":
        return CoverFormat(1069, 142, 142, 284, CoverPixelFormat.RGB565_LE)
    if profile.family == "iPod Nano" and profile.generation == "7th Gen":
        return CoverFormat(1010, 240, 240, 480, CoverPixelFormat.RGB565_LE)
    return None


def mix_artwork_updates(
    before: MixState,
    after: MixState,
    *,
    render_cover: MixCoverRenderer | None,
    size: int = 142,
) -> tuple[GeniusMixArtwork, ...]:
    """Refresh/backfill owned covers and retire only our removed Mix links."""
    if after.entries and render_cover is None:
        raise RuntimeError("Mix cover rendering was not configured")
    retained = {entry.container_id for entry in after.entries}
    return (
        *(
            GeniusMixArtwork(
                entry.container_id, render_cover(entry.definition_key, size)
            )
            for entry in after.entries
            if render_cover is not None
        ),
        *(
            GeniusMixArtwork(entry.container_id, None)
            for entry in before.entries
            if entry.container_id not in retained
        ),
    )
