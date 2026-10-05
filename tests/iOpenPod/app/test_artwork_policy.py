"""Application artwork layouts remain distinct from native Device capabilities."""

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.artwork_policy import (
    application_artwork_formats,
    application_artwork_root_value,
    application_cover_formats,
)


def test_non_cover_profiles_receive_one_iopenpod_display_layout() -> None:
    mini = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9802")

    assert mini is not None
    assert not mini.capabilities.artwork.supports_cover_art
    assert tuple(f.format_id for f in application_artwork_formats(mini)) == (1060,)
    assert tuple(f.format_id for f in application_cover_formats(mini)) == (1060,)
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
