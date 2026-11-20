"""Exercise normal USB installation through real Storage ownership and journals."""

import json
import struct
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.boot_report_helpers import report_xml

from iOpenPod.app.firmware import shared_install, shared_records, shared_release
from iOpenPod.app.firmware.bootloader_install import UnlockIdentity
from iOpenPod.app.firmware.bootloader_targets import bootloader_target
from iOpenPod.app.firmware.shared_bootloader import BODY_SHA256, VERSION
from iOpenPod.app.firmware.shared_install import (
    InstallProgress,
    InstallStage,
    SharedFirmwareInstaller,
)
from iOpenPod.app.firmware.shared_records import InstallRecordState
from iOpenPod.app.firmware.shared_release import (
    SharedFirmwareRelease,
)
from storage import (
    AtomicHostFile,
    MountedVolume,
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    Storage,
    StorageError,
)
from storage.models import VolumeObservation
from storage.testing import VirtualStoragePlatform

PAYLOAD = bytes(range(256)) * 144


class Release(SharedFirmwareRelease):
    def prepare(self, cancel: Event, progress: Callable[[int | None], None]) -> bytes:
        return PAYLOAD


class Channel:
    def __init__(self, family: int, journal: Path) -> None:
        self.family = family
        self.version = bootloader_target(family).apple_version
        self.serial = "TEST12345678"
        self.journal = journal
        self.partition_kib = 196608
        self.forced = False
        self.block = 512 if family == 24 else 4096
        self.fail_at: int | None = None
        self.writes: list[ScsiCommand] = []
        self.closed = 0
        self.boot_report: bytes | None = None

    def payload(self) -> bytes:
        values = {
            "SerialNumber": self.serial,
            "FamilyID": 11,
            "UpdaterFamilyID": self.family,
            "VisibleBuildID": self.version,
            "UpdateMethod": 3,
            "FWPartSize": self.partition_kib,
            "MaxFWBlocks": 16,
            "ForcedDiskMode": self.forced,
            "CorruptDataPartition": False,
            "AutoRebootAfterFirmwareUpdate": True,
        }
        parts: list[str] = []
        for key, value in values.items():
            tag = "string" if isinstance(value, str) else "integer"
            text = (
                f"<{str(value).lower()}/>"
                if isinstance(value, bool)
                else f"<{tag}>{value}</{tag}>"
            )
            parts.append(f"<key>{key}</key>{text}")
        root = ET.fromstring("<plist><dict>" + "".join(parts) + "</dict></plist>")
        if self.boot_report is not None:
            root[0].extend(list(ET.fromstring(self.boot_report)[0]))
        return ET.tostring(root)

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        code = command.cdb[0]
        if code == 0x12:
            if not command.cdb[1]:
                data = b"\0" * 8 + b"Apple   " + b"iPod            " + b"2.0 "
            else:
                page = command.cdb[2]
                chunks = [
                    self.payload()[offset : offset + 240]
                    for offset in range(0, len(self.payload()), 240)
                ]
                content = (
                    self.serial.encode()
                    if page == 0x80
                    else bytes(range(0xC2, 0xC2 + len(chunks)))
                    if page == 0xC0
                    else chunks[page - 0xC2]
                )
                data = bytes((0, page)) + len(content).to_bytes(2, "big") + content
            return ScsiResponse(data, len(data))
        if code == 0x25:
            return ScsiResponse(struct.pack(">II", 100000, self.block), 8)
        if code == 0x28:
            sector = bytearray(self.block)
            if int.from_bytes(command.cdb[2:6], "big") == 0:
                sector[510:512] = b"\x55\xaa"
                sector[450] = 0x0C
                struct.pack_into("<II", sector, 454, 63, 99938)
            return ScsiResponse(bytes(sector), self.block)
        record = json.loads(self.journal.read_bytes())
        assert record["pending_command"] == command.cdb.hex()
        self.writes.append(command)
        if len(self.writes) - 1 == self.fail_at:
            return ScsiResponse(b"", command.transfer_length, status=2)
        return ScsiResponse(b"", command.transfer_length)

    def close(self) -> None:
        self.closed += 1


class Platform(VirtualStoragePlatform):
    def __init__(self, channel: Channel) -> None:
        super().__init__()
        self.channel = channel

    @property
    def name(self) -> str:
        return "windows"

    def open_scsi_channel(
        self, observation: VolumeObservation, expected_identity: ScsiIdentity
    ) -> Channel:
        if expected_identity.serial != self.channel.serial:
            raise ValueError("Wrong live serial")
        return self.channel


def fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int = 33
) -> tuple[SharedFirmwareInstaller, UnlockIdentity, MountedVolume, Platform]:
    root = tmp_path / "ipod"
    (root / "iPod_Control/iTunes").mkdir(parents=True)
    (root / "iPod_Control/iTunes/iTunesDB").write_bytes(b"unchanged library")
    directory = tmp_path / "host"
    identity = UnlockIdentity(
        "TEST12345678",
        bootloader_target(family).models[0],
        family,
        reported_family=family,
        reported_version=bootloader_target(family).apple_version,
    )
    channel = Channel(
        family, directory / "installations" / identity.serial / "operation.json"
    )
    platform = Platform(channel)
    platform.add_volume(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    installer = SharedFirmwareInstaller(storage, directory, release=Release(directory))
    (directory / "bootloader" / identity.serial).mkdir(parents=True)
    AtomicHostFile(
        directory / "bootloader" / identity.serial / "operation.json"
    ).create_bytes(
        json.dumps(
            {
                "state": "verified",
                "identifier": "iOpenPod-Bootloader-v1",
                "serial": identity.serial,
                "model": identity.model,
                "hardware_family": family,
                "version": VERSION,
                "body_sha256": BODY_SHA256,
            }
        ).encode()
    )
    monkeypatch.setitem(
        shared_release.RELEASE_BYTES, shared_release.MOD_VERSION, len(PAYLOAD)
    )

    def validate(data: bytes) -> None:
        assert data == PAYLOAD

    monkeypatch.setattr(shared_install, "validate_release", validate)
    return installer, identity, storage.inspect(root), platform


@pytest.mark.parametrize("family", (24, 33, 35, 38))
def test_current_report_allows_install_on_computer_without_dfu_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch, family)
    (installer.directory / "bootloader" / identity.serial / "operation.json").unlink()
    platform.channel.boot_report = report_xml(
        DeviceModel=identity.model, HardwareRevision=bootloader_target(family).hardware
    )
    installer.install(identity, mounted, Event(), lambda _: None)
    assert b"".join(command.data_out for command in platform.channel.writes) == PAYLOAD


@pytest.mark.parametrize(
    "fields",
    [
        {"Status": 1},
        {"Status": 2},
        {"Status": 3},
        {"Schema": 2},
        {"BodySHA256": "0" * 64},
        {"Marker": "00" * 64},
        {"DeviceSerial": "OTHER1234567"},
    ],
)
def test_fresh_negative_report_blocks_upload_despite_valid_saved_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fields: dict[str, str | int]
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    platform.channel.boot_report = report_xml(DeviceModel=identity.model, **fields)
    assert installer.require_bootloader(identity) == 33
    with pytest.raises(ValueError, match="current firmware report"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert platform.channel.writes == []
    assert installer.record(identity) is None


def test_absent_report_without_receipt_cannot_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    (installer.directory / "bootloader" / identity.serial / "operation.json").unlink()
    with pytest.raises(ValueError, match="Unlock or verify"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert platform.channel.writes == []


@pytest.mark.parametrize("family", (24, 33, 35, 38))
def test_install_completes_after_upload_for_all_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch, family)
    installer.install(identity, mounted, Event(), lambda _: None)
    assert b"".join(command.data_out for command in platform.channel.writes) == PAYLOAD
    assert [command.cdb[:2].hex() for command in platform.channel.writes] == [
        "c690",
        "c691",
        "c691",
        "c692",
        "1b00",
    ]
    record = installer.record(identity)
    assert record is not None and record.state is InstallRecordState.COMPLETE
    assert record.verified_library is None and record.reported_mod_version == ""
    assert installer.pending_identity() is None
    assert platform.channel.closed == 1
    assert platform.eject_count(mounted.mount_point.path) == 0
    # Reopening before the device returns needs only the completed Host record.
    platform.disconnect(mounted.mount_point.path)
    reopened = SharedFirmwareInstaller(installer.storage, installer.directory)
    assert reopened.pending_identity() is None
    assert reopened.record(identity) == record
    assert len(platform.channel.writes) == 5


@pytest.mark.parametrize(
    "state",
    [
        InstallRecordState.COMPLETE,
        InstallRecordState.AWAITING_BOOT,
        InstallRecordState.BOOT_VERIFIED,
        InstallRecordState.REBOOT_IN_FLIGHT,
    ],
)
@pytest.mark.parametrize("version", ("0.2.0-dev", "0.2.1-dev", "0.2.2-dev"))
def test_legacy_uploaded_receipt_finishes_offline_and_allows_next_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: InstallRecordState,
    version: str,
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    installer.install(identity, mounted, Event(), lambda _: None)
    record = installer.record(identity)
    assert record is not None
    previous = replace(
        record,
        state=state,
        mod_version=version,
        image_sha256=shared_release.RELEASE_HASHES[version],
        acknowledged_bytes=shared_release.RELEASE_BYTES[version],
        pending_command=shared_records.REBOOT_COMMAND_HEX
        if state is InstallRecordState.REBOOT_IN_FLIGHT
        else "",
    )
    journal = AtomicHostFile(platform.channel.journal)
    journal.replace_bytes(json.dumps(asdict(previous)).encode())
    platform.disconnect(mounted.mount_point.path)
    assert installer.pending_identity() is None
    assert installer.record(identity) == replace(
        previous, state=InstallRecordState.COMPLETE
    )
    assert len(platform.channel.writes) == 5
    # The install entry point also handles a legacy receipt without startup discovery.
    journal.replace_bytes(json.dumps(asdict(previous)).encode())
    platform.reconnect(mounted.mount_point.path)
    mounted = installer.storage.inspect(mounted.mount_point.path)
    installer.install(identity, mounted, Event(), lambda _: None)
    assert len(platform.channel.writes) == 10
    current = installer.record(identity)
    assert current is not None and current.state is InstallRecordState.COMPLETE
    assert current.mod_version == shared_release.MOD_VERSION


@pytest.mark.parametrize("failure", (0, 1, 2, 3, 4))
def test_failed_command_never_retries_finalizes_or_reboots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    platform.channel.fail_at = failure
    with pytest.raises(ScsiCommandError):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert len(platform.channel.writes) == failure + 1
    platform.reconnect(mounted.mount_point.path)
    mounted = installer.storage.inspect(mounted.mount_point.path)
    with pytest.raises(ValueError, match="cannot be replayed"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert len(platform.channel.writes) == failure + 1
    assert installer.pending_identity() == identity
    assert platform.eject_count(mounted.mount_point.path) == 0


def test_missing_restart_reply_completes_acknowledged_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    execute = Channel.execute

    def timeout_on_restart(self: Channel, command: ScsiCommand) -> ScsiResponse:
        response = execute(self, command)
        if command.cdb.hex() == shared_records.REBOOT_COMMAND_HEX:
            raise ScsiCommandError("DeviceIoControl 0x4d014 failed (Windows error 121)")
        return response

    monkeypatch.setattr(Channel, "execute", timeout_on_restart)
    installer.install(identity, mounted, Event(), lambda _: None)
    record = installer.record(identity)
    assert record is not None and record.state is InstallRecordState.COMPLETE
    assert record.pending_command == shared_records.REBOOT_COMMAND_HEX
    assert record.acknowledged_bytes == len(PAYLOAD)
    assert record.acknowledged_commands == record.command_count == 4
    assert record.verified_library is None and record.reported_mod_version == ""
    assert installer.pending_identity() is None
    assert platform.channel.closed == 1 and len(platform.channel.writes) == 5


@pytest.mark.parametrize("failure", (0, 1, 2, 3))
def test_upload_timeout_is_never_treated_as_an_uncertain_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    execute = Channel.execute

    def timeout(self: Channel, command: ScsiCommand) -> ScsiResponse:
        response = execute(self, command)
        if command.cdb[0] == 0xC6 and len(self.writes) == failure + 1:
            raise ScsiCommandError("DeviceIoControl 0x4d014 failed (Windows error 121)")
        return response

    monkeypatch.setattr(Channel, "execute", timeout)
    with pytest.raises(ScsiCommandError):
        installer.install(identity, mounted, Event(), lambda _: None)
    record = installer.record(identity)
    assert record is not None and record.state is InstallRecordState.INTERRUPTED
    assert record.pending_command != shared_records.REBOOT_COMMAND_HEX
    assert len(platform.channel.writes) == failure + 1
    assert installer.pending_identity() == identity
    assert len(platform.channel.writes) == failure + 1


@pytest.mark.parametrize(
    "problem",
    ("version", "space", "disk-mode", "bootloader", "serial", "changed-connection"),
)
def test_bad_preconditions_send_no_vendor_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    if problem == "version":
        platform.channel.version = "1.0.0"
    elif problem == "space":
        platform.channel.partition_kib = 1
    elif problem == "disk-mode":
        platform.channel.forced = True
    elif problem == "serial":
        platform.channel.serial = "ANOTHER12345"
    elif problem == "changed-connection":
        platform.reconnect(mounted.mount_point.path)
    else:
        (
            installer.directory / "bootloader" / identity.serial / "operation.json"
        ).unlink()
    with pytest.raises((ValueError, StorageError)):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert not platform.channel.writes


@pytest.mark.parametrize("stage", (InstallStage.CHECKING, InstallStage.INSTALLING))
def test_cancellation_only_before_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: InstallStage
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    cancel = Event()

    def progress(value: InstallProgress) -> None:
        if value.stage == stage:
            cancel.set()

    if stage == InstallStage.CHECKING:
        with pytest.raises(InterruptedError):
            installer.install(identity, mounted, cancel, progress)
        assert not platform.channel.writes
    else:
        installer.install(identity, mounted, cancel, progress)
        assert len(platform.channel.writes) == 5


def test_interrupted_record_keeps_pending_command_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    platform.channel.fail_at = 1
    with pytest.raises(ScsiCommandError):
        installer.install(identity, mounted, Event(), lambda _: None)
    record = installer.record(identity)
    assert record is not None and record.pending_command.startswith("c691")
    damaged = replace(record, acknowledged_commands=99999)
    with pytest.raises(ValueError):
        shared_records.decode_record(json.dumps(asdict(damaged)).encode())


def test_journal_failure_stops_before_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    original = AtomicHostFile.replace_bytes

    def fail(self: AtomicHostFile, data: bytes) -> None:
        value = json.loads(data)
        if value.get("state") == "command-in-flight" and value.get(
            "pending_command", ""
        ).startswith("c691"):
            raise OSError("Host disk full")
        original(self, data)

    monkeypatch.setattr(AtomicHostFile, "replace_bytes", fail)
    with pytest.raises(OSError, match="disk full"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert [command.cdb[:2] for command in platform.channel.writes] == [b"\xc6\x90"]


def test_followup_update_uses_normal_usb_with_saved_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    installer.install(identity, mounted, Event(), lambda _: None)
    platform.channel.family, platform.channel.version = 38, "2.0.5"
    platform.reconnect(mounted.mount_point.path)
    mounted = installer.storage.inspect(mounted.mount_point.path)
    installer.install(
        replace(identity, reported_family=38, reported_version="2.0.5"),
        mounted,
        Event(),
        lambda _: None,
    )
    assert len(platform.channel.writes) == 10


def test_custom_running_version_uses_observation_not_model_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    identity = replace(identity, reported_version="7.26.0-custom", reported_family=99)
    platform.channel.version = identity.reported_version
    platform.channel.family = 99
    installer.install(identity, mounted, Event(), lambda _: None)
    assert platform.channel.writes


@pytest.mark.parametrize("version,family", [("7.26.0-custom", 33), ("2.0.1", 38)])
def test_runtime_report_change_stops_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, family: int
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    platform.channel.version, platform.channel.family = version, family
    with pytest.raises(ValueError, match="does not match"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert not platform.channel.writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("identifier", "different-loader"),
        ("body_sha256", "00" * 32),
        ("version", "9.9.9"),
    ],
)
def test_marker_name_alone_or_wrong_build_never_authorizes_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    path = installer.directory / "bootloader" / identity.serial / "operation.json"
    record = json.loads(path.read_bytes())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Unlock or verify"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert not platform.channel.writes


def test_previous_shared_loader_requires_upgrade_before_expanded_firmware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, platform = fixture(tmp_path, monkeypatch)
    path = installer.directory / "bootloader" / identity.serial / "operation.json"
    record = json.loads(path.read_bytes())
    record.update(
        version="2.0.0",
        body_sha256="9cb983b4bc8b5707074cdc06ce4a3634a78694ddea3449adb7727c6c4449100c",
    )
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match=r"2\.1\.0.*larger OS limit"):
        installer.install(identity, mounted, Event(), lambda _: None)
    assert not platform.channel.writes
    assert json.loads(path.read_bytes()) == record


def test_previous_release_cannot_claim_new_image_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, identity, mounted, _ = fixture(tmp_path, monkeypatch)
    installer.install(identity, mounted, Event(), lambda _: None)
    current = installer.record(identity)
    assert current is not None
    old = replace(
        current,
        mod_version="0.2.2-dev",
        image_sha256=shared_release.RELEASE_HASHES["0.2.2-dev"],
        acknowledged_bytes=shared_release.RELEASE_BYTES["0.2.2-dev"] + 4096,
    )
    with pytest.raises(ValueError, match="damaged firmware installation record"):
        shared_records.decode_record(json.dumps(asdict(old)).encode())
