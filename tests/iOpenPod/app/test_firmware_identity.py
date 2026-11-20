"""Firmware reports, physical identity and bootloader markers are independent."""

import json
from dataclasses import replace
from importlib.resources import files

import pytest
from tests.iOpenPod.GUI.test_device_summary_page import summary_active_ipod

from iOpenPod.app.firmware.bootloader_identity import read_bootloader_identity
from iOpenPod.app.firmware.bootloader_install import (
    identity_from_record,
    supported_identity,
)
from iOpenPod.app.firmware.shared_bootloader import SharedBootloaderBundle


def marked_body(family: str = "shared") -> bytes:
    root = files("iOpenPod").joinpath(
        f"assets/bootloader/classic-{family}"
        if family == "shared"
        else f"assets/bootloader/classic{family}"
    )
    manifest = json.loads(root.joinpath("manifest.json").read_bytes())
    body = bytearray(0x1F800)
    offset = manifest["marker_offset"]
    body[offset : offset + 64] = bytes.fromhex(manifest["marker_hex"])
    return bytes(body)


@pytest.mark.parametrize("family", ["shared", "24", "33", "35", "38"])
def test_flag_is_decoded_but_cannot_certify_executable(family: str) -> None:
    body = marked_body(family)
    identity = read_bootloader_identity(body)
    assert identity is not None
    assert identity.version == ("2.1.0" if family == "shared" else "1.0.0")
    assert identity.schema == (2 if family == "shared" else 1)
    assert not SharedBootloaderBundle.is_current(body)


def test_absent_flag_is_unknown_not_proof_of_stock() -> None:
    assert read_bootloader_identity(bytes(0x1F800)) is None
    misplaced = bytearray(0x1F800)
    misplaced[128:192] = marked_body()[109952:110016]
    assert read_bootloader_identity(bytes(misplaced)) is None


def test_damaged_duplicate_and_truncated_flags_are_rejected() -> None:
    with pytest.raises(ValueError, match="Incomplete"):
        read_bootloader_identity(marked_body()[:-1])
    damaged = bytearray(marked_body())
    damaged[110015] = 1
    with pytest.raises(ValueError, match="Damaged"):
        read_bootloader_identity(bytes(damaged))
    duplicate = bytearray(marked_body())
    duplicate[109768:109832] = marked_body("33")[109768:109832]
    with pytest.raises(ValueError, match="Ambiguous"):
        read_bootloader_identity(bytes(duplicate))


def test_cached_reports_do_not_become_current_installation_identity() -> None:
    active = replace(
        summary_active_ipod(),
        firmware_version_current=False,
        updater_family_current=False,
    )
    identity = supported_identity(active, "windows")
    assert identity is not None  # DFU setup can still inspect this hardware.
    assert identity.reported_version == "" and identity.reported_family is None


def test_old_shared_receipt_can_still_be_decoded_for_recovery() -> None:
    identity = identity_from_record(
        {"serial": "8K123ABC9ZS", "model": "MC293", "family": 38, "shared_os": True}
    )
    assert identity.shared_os and identity.reported_family is None


@pytest.mark.parametrize("reported", [24, 33, 35, 38, 999, None])
def test_reported_updater_family_never_disambiguates_35_and_38(
    reported: int | None,
) -> None:
    active = summary_active_ipod()
    active = replace(
        active,
        profile=replace(active.profile, model_number="MC293"),
        updater_family_id=reported,
    )
    identity = supported_identity(active, "windows")
    assert identity is not None and identity.family is None
    assert not identity.shared_os
