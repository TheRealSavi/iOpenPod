"""Preparation stays offline, exact-target, bounded and free of restore commands."""

import hashlib
import io
import plistlib
from dataclasses import replace
from zipfile import ZIP_STORED, ZipFile

import pytest

from iOpenPod.app.firmware import classic_update
from iOpenPod.app.firmware.classic_update import (
    BLOCK_BYTES,
    CLASSIC_33,
    ClassicUpdateObservation,
    prepare_classic_update,
)

OBSERVATION = ClassicUpdateObservation(33, "2.0.1", 3, 196608, 16, 4096, False, False)


def fixture_package(
    monkeypatch: pytest.MonkeyPatch,
    *,
    change_metadata: dict[str, object] | None = None,
    additional_member: bool = False,
    bad_payload: bool = False,
) -> tuple[bytes, bytes]:
    """Synthetic archive with independently pinned fixture digests; no Apple bytes."""
    payload = bytes(range(256)) * (BLOCK_BYTES * 18 // 256) + b"final"
    metadata: dict[str, object] = {
        "FamilyID": 11,
        "UpdaterFamilyID": 33,
        "VisibleBuildID": CLASSIC_33.visible_build_id,
        "BuildID": CLASSIC_33.build_id,
        "FirmwareName": CLASSIC_33.member_name,
    }
    metadata.update(change_metadata or {})
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr(
            "manifest.plist", plistlib.dumps({"FirmwarePayload": metadata})
        )
        archive.writestr(CLASSIC_33.member_name, b"wrong" if bad_payload else payload)
        if additional_member:
            archive.writestr("extra", b"unexpected")
    package = buffer.getvalue()
    monkeypatch.setattr(
        classic_update,
        "CLASSIC_33",
        replace(
            CLASSIC_33,
            package_sha256=hashlib.sha256(package).hexdigest(),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_bytes=len(payload),
        ),
    )
    return package, payload


def test_stream_is_complete_padded_bounded_and_has_only_three_update_subcommands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, payload = fixture_package(monkeypatch)
    plan = prepare_classic_update(package, OBSERVATION)
    transfers = list(plan.transfers())
    assert plan.payload == payload
    assert plan.firmware_partition_bytes == 201326592
    assert plan.chunk_bytes == 32768
    assert len(transfers) == plan.transfer_count + 2
    assert transfers[0].cdb[:3] == bytes.fromhex("c69000")
    assert int.from_bytes(transfers[0].cdb[3:7], "big") == len(payload)
    assert len(transfers[0].cdb) == len(transfers[-1].cdb) == 16
    assert transfers[0].data == transfers[-1].data == b""
    assert transfers[-1].cdb == bytes.fromhex("c692") + bytes(14)
    for transfer in transfers[1:-1]:
        assert transfer.cdb[:2] == bytes.fromhex("c691")
        assert len(transfer.cdb) == 10
        assert len(transfer.data) % BLOCK_BYTES == 0
        assert 0 < len(transfer.data) <= plan.chunk_bytes
        assert int.from_bytes(transfer.cdb[2:4], "big") * BLOCK_BYTES == len(
            transfer.data
        )
    restored = b"".join(transfer.data for transfer in transfers)
    assert restored[: len(payload)] == payload
    assert restored[len(payload) :] == bytes(-len(payload) % BLOCK_BYTES)
    assert {transfer.cdb[1] for transfer in transfers} == {0x90, 0x91, 0x92}


def test_smaller_advertised_transfer_limit_is_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _ = fixture_package(monkeypatch)
    plan = prepare_classic_update(package, replace(OBSERVATION, max_firmware_blocks=1))
    assert plan.chunk_bytes == 4096
    assert all(len(transfer.data) <= 4096 for transfer in plan.transfers())


@pytest.mark.parametrize(
    "observation",
    [
        replace(OBSERVATION, updater_family_id=38),
        replace(OBSERVATION, updater_family_id=26),
        replace(OBSERVATION, firmware_version="2.0"),
        replace(OBSERVATION, update_method=2),
        replace(OBSERVATION, logical_block_bytes=512),
        replace(OBSERVATION, forced_disk_mode=True),
        replace(OBSERVATION, corrupt_data_partition=True),
        replace(OBSERVATION, max_firmware_blocks=0),
        replace(OBSERVATION, max_firmware_blocks=17),
        replace(OBSERVATION, max_firmware_blocks=True),
        replace(OBSERVATION, firmware_partition_kib=0),
        replace(OBSERVATION, firmware_partition_kib=-1),
        replace(OBSERVATION, firmware_partition_kib=True),
        replace(OBSERVATION, firmware_partition_kib=256 * 1024 + 1),
    ],
)
def test_refuses_unqualified_device_observations(
    observation: ClassicUpdateObservation,
) -> None:
    with pytest.raises(ValueError):
        prepare_classic_update(b"not read", observation)


def test_refuses_truncated_or_changed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    package, _ = fixture_package(monkeypatch)
    with pytest.raises(ValueError, match="pinned original Apple IPSW"):
        prepare_classic_update(package[:-1], OBSERVATION)


def test_refuses_payload_larger_than_hidden_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _ = fixture_package(monkeypatch)
    with pytest.raises(ValueError, match="exceed"):
        prepare_classic_update(package, replace(OBSERVATION, firmware_partition_kib=1))


def test_partition_bound_includes_last_block_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, payload = fixture_package(monkeypatch)
    capacity_kib = (len(payload) + 1023) // 1024
    assert len(payload) <= capacity_kib * 1024
    assert capacity_kib * 1024 % BLOCK_BYTES != 0
    with pytest.raises(ValueError, match="exceed"):
        prepare_classic_update(
            package, replace(OBSERVATION, firmware_partition_kib=capacity_kib)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"UpdaterFamilyID": 38},
        {"UpdaterFamilyID": "33"},
        {"FamilyID": True},
        {"FirmwareName": "other.bin"},
        {"BuildID": CLASSIC_33.visible_build_id},
        {"VisibleBuildID": CLASSIC_33.build_id},
    ],
)
def test_cross_checks_package_manifest(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    package, _ = fixture_package(monkeypatch, change_metadata=changes)
    with pytest.raises(ValueError, match="identity mismatch"):
        prepare_classic_update(package, OBSERVATION)


def test_refuses_unexpected_members(monkeypatch: pytest.MonkeyPatch) -> None:
    package, _ = fixture_package(monkeypatch, additional_member=True)
    with pytest.raises(ValueError, match="members"):
        prepare_classic_update(package, OBSERVATION)


def test_checks_complete_original_firmware_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _ = fixture_package(monkeypatch, bad_payload=True)
    with pytest.raises(ValueError, match="Firmware member"):
        prepare_classic_update(package, OBSERVATION)
