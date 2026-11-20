"""Stable receipts and completion of acknowledged uploads from older releases."""

import json
from dataclasses import asdict, replace

import pytest

from iOpenPod.app.firmware.bootloader_install import UnlockIdentity
from iOpenPod.app.firmware.bootloader_targets import bootloader_target
from iOpenPod.app.firmware.shared_records import (
    REBOOT_COMMAND_HEX,
    InstallRecord,
    InstallRecordState,
    VisibleLayout,
    decode_record,
    finish_uploaded,
)
from iOpenPod.app.firmware.shared_release import MOD_VERSION, RELEASE_BYTES


def uploaded() -> InstallRecord:
    return InstallRecord(
        UnlockIdentity("TEST12345678", bootloader_target(33).models[0]),
        "volume",
        VisibleLayout("capacity", "0" * 64, 63, "1" * 64),
        {"iPod_Control/iTunes/iTunesDB": "2" * 64},
        state=InstallRecordState.AWAITING_BOOT,
        acknowledged_bytes=RELEASE_BYTES[MOD_VERSION],
        acknowledged_commands=5,
        command_count=5,
    )


@pytest.mark.parametrize("state", list(InstallRecordState))
def test_saved_state_strings_stay_compatible(state: InstallRecordState) -> None:
    record = replace(uploaded(), state=state)
    raw = json.dumps(asdict(record)).encode()
    assert json.loads(raw)["state"] == state.value
    restored = decode_record(raw)
    assert restored == record and restored.state is state


@pytest.mark.parametrize("state", list(InstallRecordState))
def test_only_finished_upload_states_are_completed(state: InstallRecordState) -> None:
    record = replace(uploaded(), state=state)
    completed = finish_uploaded(record)
    if state in {
        InstallRecordState.AWAITING_BOOT,
        InstallRecordState.REBOOT_IN_FLIGHT,
        InstallRecordState.BOOT_VERIFIED,
    }:
        assert completed == replace(record, state=InstallRecordState.COMPLETE)
    else:
        assert completed is record


@pytest.mark.parametrize("command", ["", REBOOT_COMMAND_HEX, "c20000000000"])
def test_legacy_completion_requires_only_restart_command_pending(command: str) -> None:
    record = replace(
        uploaded(), state=InstallRecordState.REBOOT_IN_FLIGHT, pending_command=command
    )
    completed = finish_uploaded(record)
    if command in ("", REBOOT_COMMAND_HEX):
        assert completed == replace(record, state=InstallRecordState.COMPLETE)
    else:
        assert completed is record


def test_missing_or_partial_upload_cannot_be_completed() -> None:
    full = uploaded()
    for record in (
        None,
        replace(full, acknowledged_bytes=full.acknowledged_bytes - 1),
        replace(full, acknowledged_commands=4),
        replace(full, acknowledged_commands=2, command_count=2),
    ):
        assert finish_uploaded(record) is record


def test_unknown_saved_state_is_rejected() -> None:
    wire = asdict(uploaded())
    wire["state"] = "retry-upload"
    with pytest.raises(ValueError):
        decode_record(json.dumps(wire).encode())


def test_older_receipt_without_library_observation_remains_readable() -> None:
    wire = asdict(uploaded())
    del wire["verified_library"]
    del wire["reported_mod_version"]
    assert decode_record(json.dumps(wire).encode()) == uploaded()


def test_library_observation_preserves_both_hashes() -> None:
    record = replace(
        uploaded(),
        state=InstallRecordState.COMPLETE,
        verified_library={"iPod_Control/iTunes/iTunesDB": "3" * 64},
        reported_mod_version=MOD_VERSION,
    )
    restored = decode_record(json.dumps(asdict(record)).encode())
    assert restored == record and restored.library_changed
    assert restored.library == uploaded().library


@pytest.mark.parametrize(
    "field,value",
    [
        ("verified_library", {}),
        ("verified_library", {"outside": "3" * 64}),
        ("verified_library", {"iPod_Control/iTunes/iTunesDB": "bad"}),
        ("reported_mod_version", "0.0.0"),
    ],
)
def test_invalid_verification_observations_are_rejected(
    field: str, value: object
) -> None:
    wire = asdict(uploaded())
    wire[field] = value
    with pytest.raises(ValueError):
        decode_record(json.dumps(wire).encode())
