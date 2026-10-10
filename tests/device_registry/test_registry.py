"""Behavioral tests for evidence-based iPod identification."""

from dataclasses import replace

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    ConnectionMode,
    DatabaseChecksum,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    IdentificationIssueCode,
    IdentificationStatus,
    StorageTechnology,
    UsbIdentifier,
)


def _text_identifier(
    value: str,
    *,
    source: str,
    authority: EvidenceAuthority,
) -> DeviceIdentifier[str]:
    return DeviceIdentifier(value=value, source=source, authority=authority)


def _usb_identifier(
    product_id: int,
    *,
    vendor_id: int = 0x05AC,
    source: str = "host USB API",
    authority: EvidenceAuthority = EvidenceAuthority.CURRENT_HARDWARE,
) -> DeviceIdentifier[UsbIdentifier]:
    return DeviceIdentifier(
        value=UsbIdentifier(vendor_id=vendor_id, product_id=product_id),
        source=source,
        authority=authority,
    )


def test_catalog_matches_the_documented_release_families() -> None:
    families = {profile.family for profile in DEFAULT_DEVICE_REGISTRY.profiles}

    assert families == {"iPod", "iPod Classic", "iPod Mini", "iPod Nano"}
    assert all(profile.model_number for profile in DEFAULT_DEVICE_REGISTRY.profiles)


def test_catalog_covers_every_full_size_ipod_generation() -> None:
    profiles = DEFAULT_DEVICE_REGISTRY.profiles
    generations = {
        profile.generation for profile in profiles if profile.family == "iPod"
    }

    assert generations == {
        "1st Gen",
        "2nd Gen",
        "3rd Gen",
        "4th Gen (mono)",
        "4th Gen (photo)",
        "4th Gen (color)",
        "5th Gen",
        "5.5th Gen",
    }
    assert {
        "M8541",
        "M8737",
        "M8976",
        "M9282",
        "M9585",
        "MA079",
        "MA002",
        "MA444",
    }.issubset({profile.model_number for profile in profiles})


def test_early_ipod_usb_and_serial_evidence_remain_bounded() -> None:
    serial_result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            product_serials=(
                _text_identifier(
                    "U123456LG6",
                    source="host product serial",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            )
        )
    )
    usb_result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(usb_identifiers=(_usb_identifier(0x1202),))
    )

    assert serial_result.status is IdentificationStatus.EXACT
    assert serial_result.profile is not None
    assert serial_result.profile.model_number == "M8541"
    assert usb_result.status is IdentificationStatus.AMBIGUOUS
    assert {profile.generation for profile in usb_result.candidates} == {
        "1st Gen",
        "2nd Gen",
    }


def test_coarse_2006_through_2008_usb_ids_remain_bounded_to_full_size_ipods() -> None:
    expected_generations = {
        "1st Gen",
        "2nd Gen",
        "3rd Gen",
        "4th Gen (mono)",
        "4th Gen (photo)",
        "4th Gen (color)",
        "5th Gen",
        "5.5th Gen",
    }

    for product_id in (0x1206, 0x1207, 0x1208):
        result = DEFAULT_DEVICE_REGISTRY.identify(
            DeviceEvidence(usb_identifiers=(_usb_identifier(product_id),))
        )

        assert result.status is IdentificationStatus.AMBIGUOUS
        assert result.connection_mode is ConnectionMode.NORMAL
        assert {profile.family for profile in result.candidates} == {"iPod"}
        assert {
            profile.generation for profile in result.candidates
        } == expected_generations


def test_full_size_ipod_capabilities_preserve_generation_differences() -> None:
    first = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M8541")
    photo = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9585")
    video_30 = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MA444")
    video_80 = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MA450")

    assert first is not None
    assert not first.capabilities.audio.supports_podcasts
    assert not first.capabilities.artwork.supports_cover_art
    assert first.capabilities.database.binary_version == 0x13

    assert photo is not None
    assert {item.format_id for item in photo.capabilities.artwork.cover_formats} == {
        1016,
        1017,
    }
    assert photo.capabilities.artwork.supports_photos

    assert video_30 is not None
    assert video_30.capabilities.video.supported
    assert video_30.capabilities.audio.supports_gapless_playback
    assert video_30.capabilities.database.max_database_bytes == 32 * 1024 * 1024

    assert video_80 is not None
    assert video_80.capabilities.database.max_database_bytes == 64 * 1024 * 1024


def test_sysinfo_style_model_number_produces_an_exact_profile() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            model_numbers=(
                _text_identifier(
                    "xB565",
                    source="SysInfo",
                    authority=EvidenceAuthority.DEVICE_METADATA,
                ),
            )
        )
    )

    assert result.status is IdentificationStatus.EXACT
    assert result.connection_mode is ConnectionMode.UNKNOWN
    assert result.profile is not None
    assert result.profile.model_number == "MB565"


def test_product_serial_uses_the_longest_published_suffix() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            product_serials=(
                _text_identifier(
                    "YM12345F0GD",
                    source="host product serial",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            )
        )
    )

    assert result.status is IdentificationStatus.EXACT
    assert result.profile is not None
    assert result.profile.model_number == "MD475"


def test_transport_serial_is_not_mistaken_for_a_product_serial() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            transport_serials=(
                _text_identifier(
                    "000A270000002C7",
                    source="USB descriptor",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            )
        )
    )

    assert result.status is IdentificationStatus.UNKNOWN


def test_live_product_serial_overrides_disagreeing_cached_model_number() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            model_numbers=(
                _text_identifier(
                    "MB562",
                    source="SysInfo",
                    authority=EvidenceAuthority.DEVICE_METADATA,
                ),
            ),
            product_serials=(
                _text_identifier(
                    "8P840FN62C7",
                    source="host product serial",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            ),
        )
    )

    assert result.status is IdentificationStatus.EXACT
    assert result.profile is not None
    assert result.profile.model_number == "MB565"
    assert tuple(issue.code for issue in result.issues) == (
        IdentificationIssueCode.LOWER_AUTHORITY_IDENTIFIER_DISAGREES,
    )


def test_equally_authoritative_exact_identifiers_do_not_guess() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            model_numbers=(
                _text_identifier(
                    "MB562",
                    source="live vendor metadata",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            ),
            product_serials=(
                _text_identifier(
                    "8P840FN62C7",
                    source="host product serial",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            ),
        )
    )

    assert result.status is IdentificationStatus.CONFLICTING
    assert result.profile is None
    assert result.issues[0].code is IdentificationIssueCode.EXACT_IDENTIFIERS_DISAGREE


def test_current_normal_usb_identifier_corroborates_an_exact_profile() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            product_serials=(
                _text_identifier(
                    "8P840FN62C7",
                    source="host product serial",
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                ),
            ),
            usb_identifiers=(_usb_identifier(0x1261),),
        )
    )

    assert result.status is IdentificationStatus.EXACT
    assert result.connection_mode is ConnectionMode.NORMAL
    assert result.profile is not None
    assert result.profile.model_number == "MB565"


def test_current_usb_conflict_rejects_a_stale_exact_profile() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            model_numbers=(
                _text_identifier(
                    "MB565",
                    source="SysInfo",
                    authority=EvidenceAuthority.DEVICE_METADATA,
                ),
            ),
            usb_identifiers=(_usb_identifier(0x1262),),
        )
    )

    assert result.status is IdentificationStatus.CONFLICTING
    assert result.profile is None
    assert result.issues[0].code is IdentificationIssueCode.USB_IDENTITY_DISAGREES


def test_coarse_usb_identifier_returns_bounded_candidates() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(usb_identifiers=(_usb_identifier(0x1261),))
    )

    assert result.status is IdentificationStatus.AMBIGUOUS
    assert result.connection_mode is ConnectionMode.NORMAL
    assert {profile.family for profile in result.candidates} == {"iPod Classic"}
    assert {profile.generation for profile in result.candidates} == {
        "6th Gen",
        "6.5th Gen",
        "7th Gen",
    }
    assert len(result.candidates) == 8


def test_usb_product_id_is_only_meaningful_with_the_apple_vendor_id() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(usb_identifiers=(_usb_identifier(0x1261, vendor_id=0x1234),))
    )

    assert result.status is IdentificationStatus.UNKNOWN
    assert result.connection_mode is ConnectionMode.UNKNOWN


def test_unknown_current_usb_evidence_prevents_cached_usb_fallback() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(
            usb_identifiers=(
                _usb_identifier(
                    0x1261,
                    source="SysInfo",
                    authority=EvidenceAuthority.DEVICE_METADATA,
                ),
                _usb_identifier(0xFFFF),
            )
        )
    )

    assert result.status is IdentificationStatus.UNKNOWN
    assert result.candidates == ()


def test_recovery_usb_identifier_is_not_returned_as_a_normal_profile() -> None:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        DeviceEvidence(usb_identifiers=(_usb_identifier(0x1245),))
    )

    assert result.status is IdentificationStatus.RECOVERY_MODE
    assert result.connection_mode is ConnectionMode.RECOVERY
    assert result.profile is None
    assert {profile.model_number for profile in result.candidates} == {
        "MB562",
        "MB565",
    }


def test_profiles_expose_grouped_operational_capabilities() -> None:
    classic = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    nano5 = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC027")
    nano = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MD475")

    assert classic is not None
    assert classic.storage_technology is StorageTechnology.HARD_DISK
    assert classic.capabilities.display.width == 320
    assert classic.capabilities.database.checksum is DatabaseChecksum.HASH58
    assert classic.capabilities.database.music_directory_count == 50
    assert classic.capabilities.video.supported

    assert nano5 is not None
    assert nano5.capabilities.database.uses_sqlite_database
    assert nano5.capabilities.database.checksum is DatabaseChecksum.HASH72
    assert nano5.capabilities.database.sqlite_checksum is DatabaseChecksum.HASH72

    assert nano is not None
    assert nano.storage_technology is StorageTechnology.FLASH
    assert nano.capabilities.display.height == 432
    assert nano.capabilities.database.checksum is DatabaseChecksum.HASHAB
    assert nano.capabilities.database.uses_sqlite_database
    assert nano.capabilities.database.sqlite_checksum is DatabaseChecksum.HASHAB


def test_database_cannot_require_sqlite_checksum_without_sqlite_support() -> None:
    nano5 = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC027")
    assert nano5 is not None

    with pytest.raises(ValueError, match="SQLite checksum requires SQLite"):
        replace(
            nano5.capabilities.database,
            uses_sqlite_database=False,
        )
