"""Independent firmware qualification and byte-only Mix cover intent."""

import plistlib

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    FeatureSupport,
    parse_sysinfo_extended,
)
from iOpenPod.app.genius_mix_artwork import (
    mix_artwork_format,
    mix_artwork_updates,
)
from iOpenPod.app.genius_mixes import ManagedMix, MixState
from iPodDB.library import ArtworkPixels


@pytest.mark.parametrize(
    ("model", "version", "family", "supported"),
    [
        ("MB565", "2.0.5", 38, True),
        ("MB029", "2.0.5", 38, True),
        ("MC293", "2.0.4", 35, True),
        ("MC293", "2.0.5", 38, True),
        ("MC293", "2.0.3", 35, False),
        ("MC293", "2.0.5", 35, False),
        ("MC293", "2.0.5", None, False),
        ("MB565", "2.0.1", 33, False),
        ("MD479", "1.0.4", 37, True),
        ("MD479", "1.1.2", 39, True),
        ("MD479", "1.0.4", None, False),
        ("MD479", "1.0.4", 39, False),
        ("MC525", "1.2", 36, False),
        ("MC031", "1.0.2", 34, False),
    ],
)
def test_cover_gate_requires_qualified_running_firmware(
    model: str, version: str, family: int | None, supported: bool
) -> None:
    data: dict[str, object] = {"ModelNumStr": model, "VisibleBuildID": version}
    if family is not None:
        data["UpdaterFamilyID"] = family
    identified = DEFAULT_DEVICE_REGISTRY.identify(
        parse_sysinfo_extended(plistlib.dumps(data))
    )
    assert identified.profile is not None
    assert (mix_artwork_format(identified.profile) is not None) == supported
    assert (
        identified.profile.capabilities.genius.mix_artwork is FeatureSupport.SUPPORTED
    ) == supported


def test_owned_mix_backfill_and_removal_are_explicit() -> None:
    calls: list[tuple[str, int]] = []
    pixels = ArtworkPixels(1, 1, b"\x01\x02\x03")

    def render(key: str, size: int) -> ArtworkPixels:
        calls.append((key, size))
        return pixels

    before = MixState((ManagedMix(900, "rock"), ManagedMix(901, "pop")))
    after = MixState((ManagedMix(901, "pop"), ManagedMix(902, "jazz")))
    updates = mix_artwork_updates(before, after, render_cover=render, size=240)
    assert [(u.mix_id, u.pixels is not None) for u in updates] == [
        (901, True),
        (902, True),
        (900, False),
    ]
    assert updates[0].pixels is pixels
    assert calls == [("pop", 240), ("jazz", 240)]


def test_missing_renderer_is_explicit_only_when_pixels_are_needed() -> None:
    owned = MixState((ManagedMix(900, "rock"),))
    with pytest.raises(RuntimeError, match="rendering was not configured"):
        mix_artwork_updates(MixState(), owned, render_cover=None)
    removed = mix_artwork_updates(owned, MixState(), render_cover=None)
    assert [(u.mix_id, u.pixels) for u in removed] == [(900, None)]
