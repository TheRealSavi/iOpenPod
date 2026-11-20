"""Exercise the upload workflow through real Storage session/journal semantics."""

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from iOpenPod.app.firmware import classic_upload
from iOpenPod.app.firmware.classic_update import CLASSIC_33, ClassicUpdatePlan
from iOpenPod.app.firmware.classic_upload import (
    ClassicRecovery,
    VerifiedFirmwareRange,
    upload_classic_stock,
)
from storage import (
    AtomicHostFile,
    MountedVolume,
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    Storage,
)
from storage.models import VolumeObservation
from storage.testing import VirtualStoragePlatform


class _Channel:
    def __init__(self, journal: AtomicHostFile) -> None:
        self.journal = journal
        self.vendor_commands: list[bytes] = []
        self.payloads: list[bytes] = []
        self.fail_at: int | None = None
        self.short_at: int | None = None
        self.capacity_last_lba = 100000
        self.closed = 0

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        if command.cdb[0] == 0x25:
            return ScsiResponse(struct.pack(">II", self.capacity_last_lba, 4096), 8)
        if command.cdb[0] == 0x28:
            lba = int.from_bytes(command.cdb[2:6], "big")
            return ScsiResponse((b"m" if lba == 0 else b"b") * 4096, 4096)
        assert command.cdb[:2] in (b"\xc6\x90", b"\xc6\x91", b"\xc6\x92")
        journal = json.loads(self.journal.read_bytes() or b"null")
        assert journal["state"] == "command-in-flight"
        assert journal["pending_command"]["cdb"] == command.cdb.hex()
        index = len(self.vendor_commands)
        self.vendor_commands.append(command.cdb)
        self.payloads.append(command.data_out)
        if index == self.fail_at:
            return ScsiResponse(
                b"", command.transfer_length, status=2, sense=b"\x70\0\x03"
            )
        if index == self.short_at:
            return ScsiResponse(b"", command.transfer_length - 1)
        return ScsiResponse(b"", command.transfer_length)

    def close(self) -> None:
        self.closed += 1


class _Platform(VirtualStoragePlatform):
    def __init__(self, channel: _Channel) -> None:
        super().__init__()
        self.channel = channel
        self.opens = 0

    def open_scsi_channel(
        self, observation: VolumeObservation, expected_identity: ScsiIdentity
    ) -> _Channel:
        assert expected_identity == ScsiIdentity("Apple", "iPod", "fixture-serial")
        self.opens += 1
        return self.channel


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    Storage,
    MountedVolume,
    ClassicUpdatePlan,
    ClassicRecovery,
    AtomicHostFile,
    _Platform,
    _Channel,
]:
    root = tmp_path / "volume"
    root.mkdir()
    host = tmp_path / "host"
    host.mkdir()
    journal = AtomicHostFile(host / "upload.json")
    channel = _Channel(journal)
    platform = _Platform(channel)
    platform.add_volume(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    mounted = storage.inspect(root)
    payload = bytes(range(256)) * 96
    release = replace(
        CLASSIC_33,
        payload_bytes=len(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(classic_upload, "CLASSIC_33", release)
    plan = ClassicUpdatePlan(release, payload, 49152 * 4096, 8192)
    raw_mbr = bytearray(4096)
    raw_mbr[510:512] = b"\x55\xaa"
    raw_mbr[466] = 0x3F
    struct.pack_into("<II", raw_mbr, 470, 63, 49152)
    recovery = ClassicRecovery(
        "fixture-serial",
        payload,
        (VerifiedFirmwareRange(0, len(payload), hashlib.sha256(payload).hexdigest()),),
        bytes(1024**2),
        bytes(raw_mbr),
        b"m" * 4096,
        b"b" * 4096,
        100000,
    )
    return storage, mounted, plan, recovery, journal, platform, channel


def test_success_records_acknowledgement_but_never_claims_verified_or_ejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, mounted, plan, recovery, journal, platform, channel = _fixture(
        tmp_path, monkeypatch
    )
    receipt = upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert receipt.state == "awaiting-independent-verification"
    assert receipt.acknowledged_bytes == len(plan.payload)
    assert receipt.acknowledged_commands == 5
    assert b"".join(channel.payloads) == plan.payload
    assert channel.vendor_commands == [item.cdb for item in plan.transfers()]
    assert channel.closed == 1
    saved = json.loads(journal.read_bytes() or b"null")
    assert saved["state"] == receipt.state and saved["pending_command"] is None
    with pytest.raises(ValueError, match="replayed"):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert platform.opens == 1


@pytest.mark.parametrize("failure_index", [0, 2, 4])
def test_failed_start_chunk_or_end_stops_without_retry_or_finalizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_index: int
) -> None:
    storage, mounted, plan, recovery, journal, _, channel = _fixture(
        tmp_path, monkeypatch
    )
    channel.fail_at = failure_index
    with pytest.raises(ScsiCommandError):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert len(channel.vendor_commands) == failure_index + 1
    assert channel.closed == 1
    saved = json.loads(journal.read_bytes() or b"null")
    assert saved["state"] == "interrupted-do-not-retry-or-eject"
    assert saved["acknowledged_commands"] == failure_index
    assert saved["pending_command"]["index"] == failure_index


def test_short_write_is_uncertain_and_stops_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, mounted, plan, recovery, journal, _, channel = _fixture(
        tmp_path, monkeypatch
    )
    channel.short_at = 1
    with pytest.raises(ScsiCommandError):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert len(channel.vendor_commands) == 2
    saved = json.loads(journal.read_bytes() or b"null")
    assert saved["acknowledged_bytes"] == 0 and saved["pending_command"]["index"] == 1


@pytest.mark.parametrize("failure_state", ["command-in-flight", "command-acknowledged"])
def test_journal_failure_prevents_further_device_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_state: str
) -> None:
    storage, mounted, plan, recovery, journal, _, channel = _fixture(
        tmp_path, monkeypatch
    )
    original = AtomicHostFile.replace_bytes

    def fail_write(self: AtomicHostFile, data: bytes) -> None:
        if json.loads(data)["state"] == failure_state:
            raise OSError("Host disk cannot persist the journal")
        original(self, data)

    monkeypatch.setattr(AtomicHostFile, "replace_bytes", fail_write)
    with pytest.raises(OSError):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert len(channel.vendor_commands) == int(failure_state == "command-acknowledged")
    assert channel.closed == 1


@pytest.mark.parametrize("kind", ["gap", "digest", "incomplete", "nor", "partition"])
def test_incomplete_or_changed_recovery_material_blocks_native_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    storage, mounted, plan, recovery, journal, platform, channel = _fixture(
        tmp_path, monkeypatch
    )
    if kind == "gap":
        recovery = replace(recovery, ranges=(replace(recovery.ranges[0], offset=1),))
    elif kind == "digest":
        recovery = replace(recovery, preimage=b"x" * len(recovery.preimage))
    elif kind == "incomplete":
        recovery = replace(recovery, ranges=())
    elif kind == "nor":
        recovery = replace(recovery, nor=b"")
    else:
        recovery = replace(recovery, raw_mbr=bytes(4096))
    with pytest.raises(ValueError):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert platform.opens == 0 and not channel.vendor_commands and not journal.exists()


def test_live_layout_change_blocks_start_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, mounted, plan, recovery, journal, _, channel = _fixture(
        tmp_path, monkeypatch
    )
    channel.capacity_last_lba += 1
    with pytest.raises(ValueError, match="capacity"):
        upload_classic_stock(storage, mounted, plan, recovery, journal)
    assert not channel.vendor_commands and not journal.exists() and channel.closed == 1
