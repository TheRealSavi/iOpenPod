from __future__ import annotations

from iopenpod.device.artwork import ITHMB_FORMAT_MAP, resolve_cover_art_format_definitions


def test_standard_device_resolves_formats_from_global_registry() -> None:
    resolved = resolve_cover_art_format_definitions("iPod Classic", "6th Gen")

    assert list(resolved) == [1055, 1060, 1061, 1068]
    assert resolved[1055] == ITHMB_FORMAT_MAP[1055]


def test_ipod_5th_gen_resolves_shared_formats() -> None:
    resolved = resolve_cover_art_format_definitions("iPod", "5th Gen")

    assert list(resolved) == [1028, 1029]
    assert resolved[1028] == ITHMB_FORMAT_MAP[1028]
    assert resolved[1029] == ITHMB_FORMAT_MAP[1029]


def test_nano_7g_conflicting_ids_use_explicit_overrides() -> None:
    resolved = resolve_cover_art_format_definitions("iPod Nano", "7th Gen")

    assert resolved[1013].width == 50
    assert resolved[1015].width == 58
    assert resolved[1016].width == 57
    assert resolved[1016] != ITHMB_FORMAT_MAP[1016]


def test_observed_formats_keep_known_definition_when_dimensions_match() -> None:
    resolved = resolve_cover_art_format_definitions(
        "iPod Nano",
        "7th Gen",
        observed_formats={1016: (57, 57)},
    )

    assert resolved[1016].width == 57
    assert resolved[1016].height == 57
    assert resolved[1016].description == "Nano 7G album art small (aligned)"


def test_observed_formats_only_fall_back_when_known_dimensions_do_not_match() -> None:
    resolved = resolve_cover_art_format_definitions(
        "iPod Nano",
        "7th Gen",
        observed_formats={1016: (60, 60)},
    )

    assert resolved[1016].width == 60
    assert resolved[1016].height == 60
    assert resolved[1016].pixel_format == "RGB565_LE"
    assert resolved[1016].description == "Device artwork format 1016"
