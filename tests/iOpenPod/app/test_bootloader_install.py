"""Exercise the application workflow with an isolated simulated iPod."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from tests.iOpenPod.app.test_bootloader import PLAN, report, syscfg

from iOpenPod.app.firmware import bootloader_install as install
from iOpenPod.app.firmware.bootloader_bundle import WriterPlan, sha
from iOpenPod.app.firmware.bootloader_dfu import ClassicBootDfu, verify_report
from iOpenPod.app.firmware.bootloader_install import (
    BootloaderInstaller,
    UnlockIdentity,
    UnlockProgress,
    UnlockStage,
)
from storage import StorageError, UsbControlEndpoint, UsbControlSession
from storage.host_files import lock_host_file

IDENTITY = UnlockIdentity("8K123ABC9ZS", "MB565")
ENDPOINT = UsbControlEndpoint(
    install.INTERFACE, "test-interface", "test-instance", 0x05AC, 0x1223
)


class FakeStorage:
    platform_name = "windows"

    def __init__(self) -> None:
        self.endpoints: tuple[UsbControlEndpoint, ...] = (ENDPOINT,)
        self.opens = 0

    def discover_usb_control(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        return self.endpoints

    def open_usb_control_session(
        self, endpoint: UsbControlEndpoint
    ) -> UsbControlSession:
        self.opens += 1
        session = MagicMock(spec=UsbControlSession)
        session.__enter__.return_value = session
        return session


class FakeDfu(ClassicBootDfu):
    def __init__(self, _session: object, cancel: Event) -> None:
        self.cancel = cancel
        self.identity = IDENTITY
        self.body = b"known-stock-body"
        self.downloads = 0
        self.reads: list[tuple[int, int]] = []
        self.bad_report = False

    def qualify(self) -> None:
        pass

    def fingerprint(self) -> None:
        pass

    def clean(self) -> None:
        pass

    def nor(
        self, offset: int, size: int, progress: Callable[[int, int], None]
    ) -> bytes:
        self.reads.append((offset, size))
        data = syscfg(self.identity).ljust(0x100000, b"\0")
        progress(size, size)
        return data[offset : offset + size]

    def plaintext(self, image: bytes) -> bytes:
        return self.body

    def seal(self, body: bytes) -> bytes:
        return b"device-sealed-target"

    def download(self, image: bytes, handoff: Callable[[], None]) -> None:
        handoff()
        self.downloads += 1

    def report(self, plan: WriterPlan) -> bytes:
        data = bytearray(report(plan))
        if self.bad_report:
            data[32] ^= 1
        verify_report(bytes(data), plan)
        return bytes(data)


class FakeBundle:
    @staticmethod
    def is_current(body: bytes) -> bool:
        return body == b"current-shared-body"

    def apply(self, body: bytes, hardware_family: int) -> bytes:
        assert hardware_family in (24, 33, 35, 38)
        if body not in (b"known-stock-body", b"previous-custom-loader"):
            raise ValueError("unknown bootloader")
        return b"patched-body"

    def writer(self, _before: bytes, _target: bytes, _nonce: bytes) -> WriterPlan:
        return PLAN


type Harness = tuple[BootloaderInstaller, FakeStorage, FakeDfu]


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    storage = FakeStorage()
    dfu = FakeDfu(None, Event())
    monkeypatch.setattr(install, "SharedBootloaderBundle", FakeBundle)
    installer = BootloaderInstaller(
        storage, tmp_path, dfu_factory=lambda _session, _cancel: dfu, writer_wait=0
    )
    return installer, storage, dfu


def test_install_once_verifies_and_reuses_initial_copy(
    harness: Harness, tmp_path: Path
) -> None:
    installer, storage, dfu = harness
    events: list[UnlockProgress] = []
    assert installer.run(IDENTITY, Event(), events.append) is False
    assert dfu.downloads == 1 and storage.opens == 2
    assert [event.stage for event in events][-2:] == [
        UnlockStage.INSTALLING,
        UnlockStage.VERIFYING,
    ]
    directory = tmp_path / IDENTITY.serial
    assert (directory / "original.nor").stat().st_size == 0x100000
    receipt = json.loads((directory / "operation.json").read_bytes())
    assert receipt["state"] == "verified"
    assert receipt["report_hex"] == report(PLAN).hex()


def test_previous_custom_loader_is_upgraded_instead_of_reported_current(
    harness: Harness, tmp_path: Path
) -> None:
    installer, _, dfu = harness
    dfu.body = b"previous-custom-loader"
    assert installer.run(IDENTITY, Event(), lambda _progress: None) is False
    assert dfu.downloads == 1
    receipt = json.loads((tmp_path / IDENTITY.serial / "operation.json").read_bytes())
    assert receipt["version"] == "2.1.0"
    assert receipt["hardware_family"] == 33


def test_already_unlocked_does_not_seal_backup_or_write(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, _, dfu = harness
    dfu.body = b"current-shared-body"
    assert installer.run(IDENTITY, Event(), lambda _progress: None) is True
    assert dfu.downloads == 0
    assert (0, 0x100000) not in dfu.reads
    assert not (tmp_path / IDENTITY.serial / "original.nor").exists()


@pytest.mark.parametrize(
    "fault", ["wrong-ipod", "unknown-loader", "multiple-devices", "cancel"]
)
def test_preparation_failures_never_mutate(harness: Harness, fault: str) -> None:
    installer, storage, dfu = harness
    cancel = Event()
    if fault == "wrong-ipod":
        dfu.identity = UnlockIdentity("OTHER123456", "MB565")
    elif fault == "unknown-loader":
        dfu.body = b"unqualified-loader"
    elif fault == "multiple-devices":
        storage.endpoints = (ENDPOINT, ENDPOINT)
    else:
        cancel.set()
    with pytest.raises((ValueError, InterruptedError)):
        installer.run(IDENTITY, cancel, lambda _progress: None)
    assert dfu.downloads == 0


def test_stale_report_leaves_pending_receipt_and_retry_only_reads(
    harness: Harness, tmp_path: Path
) -> None:
    installer, _, dfu = harness
    dfu.bad_report = True
    with pytest.raises(ValueError, match="unverified"):
        installer.run(IDENTITY, Event(), lambda _progress: None)
    receipt = tmp_path / IDENTITY.serial / "operation.json"
    assert json.loads(receipt.read_bytes())["state"] == "handoff"
    assert installer.pending_identity() == IDENTITY
    assert dfu.downloads == 1
    dfu.bad_report = False
    dfu.body = b"never inspect or rewrite this loader"
    assert (
        installer.run(IDENTITY, Event(), lambda _progress: None, verify_only=True)
        is False
    )
    assert dfu.downloads == 1
    assert json.loads(receipt.read_bytes())["state"] == "verified"
    assert installer.pending_identity() is None


@pytest.mark.parametrize(
    "family, model", [(24, "MB029"), (33, "MB565"), (35, "MC293"), (38, "MC293")]
)
def test_family_is_retained_through_install_and_result_only_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int, model: str
) -> None:
    identity = UnlockIdentity("8K123ABC9ZS", model, family)
    storage, dfu = FakeStorage(), FakeDfu(None, Event())
    dfu.identity = identity
    dfu.bad_report = True
    selected: list[bool] = []

    def bundle() -> FakeBundle:
        selected.append(True)
        return FakeBundle()

    monkeypatch.setattr(install, "SharedBootloaderBundle", bundle)
    installer = BootloaderInstaller(
        storage, tmp_path, dfu_factory=lambda _session, _cancel: dfu, writer_wait=0
    )
    with pytest.raises(ValueError, match="unverified"):
        installer.run(identity, Event(), lambda _progress: None)
    assert installer.pending_identity() == identity
    receipt = tmp_path / identity.serial / "operation.json"
    assert json.loads(receipt.read_bytes())["family"] == family
    if family in (35, 38):
        opens = storage.opens
        with pytest.raises(ValueError, match="identity mismatch"):
            installer.run(
                replace(identity, family=38 if family == 35 else 35),
                Event(),
                lambda _progress: None,
                verify_only=True,
            )
        assert storage.opens == opens and dfu.downloads == 1
    dfu.bad_report = False
    installer.run(identity, Event(), lambda _progress: None, verify_only=True)
    assert selected == [True, True] or selected == [True, True, True]
    assert dfu.downloads == 1
    assert installer.pending_identity() is None


def test_previous_family33_receipt_can_still_be_resumed(
    harness: Harness, tmp_path: Path
) -> None:
    installer, _, dfu = harness
    dfu.bad_report = True
    with pytest.raises(ValueError, match="unverified"):
        installer.run(IDENTITY, Event(), lambda _progress: None)
    receipt = tmp_path / IDENTITY.serial / "operation.json"
    record: dict[str, object] = json.loads(receipt.read_bytes())
    del record["family"]
    receipt.write_text(json.dumps(record))
    assert installer.pending_identity() == IDENTITY
    dfu.bad_report = False
    installer.run(IDENTITY, Event(), lambda _progress: None, verify_only=True)
    assert dfu.downloads == 1


def test_result_check_cannot_start_a_new_installation(harness: Harness) -> None:
    installer, storage, dfu = harness
    with pytest.raises(ValueError, match="no pending installation"):
        installer.run(IDENTITY, Event(), lambda _progress: None, verify_only=True)
    assert storage.opens == 0 and dfu.downloads == 0


@pytest.mark.parametrize("record", [None, [], "handoff"])
def test_invalid_receipt_shape_is_rejected_before_usb_access(
    harness: Harness, tmp_path: Path, record: object
) -> None:
    installer, storage, dfu = harness
    directory = tmp_path / IDENTITY.serial
    directory.mkdir()
    (directory / "operation.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Invalid bootloader receipt"):
        installer.pending_identity()
    with pytest.raises(ValueError, match="Invalid bootloader receipt"):
        installer.run(IDENTITY, Event(), lambda _progress: None, verify_only=True)
    assert storage.opens == 0 and dfu.downloads == 0


@pytest.mark.parametrize(
    "field",
    [
        "serial",
        "model",
        "nonce",
        "before_sha",
        "target_sha",
        "after_sha",
        "outside_sha",
        "handoff_time",
    ],
)
def test_invalid_pending_field_never_replays_installation(
    harness: Harness, tmp_path: Path, field: str
) -> None:
    installer, storage, dfu = harness
    dfu.bad_report = True
    with pytest.raises(ValueError, match="unverified"):
        installer.run(IDENTITY, Event(), lambda _progress: None)
    receipt = tmp_path / IDENTITY.serial / "operation.json"
    record: dict[str, object] = json.loads(receipt.read_bytes())
    record[field] = None
    receipt.write_text(json.dumps(record))
    opens = storage.opens
    with pytest.raises(ValueError, match=f"Invalid bootloader receipt field: {field}"):
        if field in ("serial", "model"):
            installer.pending_identity()
        else:
            installer.run(IDENTITY, Event(), lambda _progress: None, verify_only=True)
    assert storage.opens == opens and dfu.downloads == 1


def test_operation_claim_excludes_a_second_controller(
    harness: Harness, tmp_path: Path
) -> None:
    installer, storage, dfu = harness
    directory = tmp_path / IDENTITY.serial
    directory.mkdir()
    with lock_host_file(directory / "operation.json"), pytest.raises(StorageError):
        installer.run(IDENTITY, Event(), lambda _progress: None)
    assert storage.opens == 0 and dfu.downloads == 0


def test_original_copy_is_reused_after_interrupted_checksum_publication(
    harness: Harness, tmp_path: Path
) -> None:
    installer, _, dfu = harness
    directory = tmp_path / IDENTITY.serial
    directory.mkdir()
    original = directory / "original.nor"
    original.write_bytes(dfu.nor(0, 0x100000, lambda _done, _total: None))
    revision = original.stat().st_mtime_ns
    installer.run(IDENTITY, Event(), lambda _progress: None)
    assert original.stat().st_mtime_ns == revision
    assert (directory / "original.sha256").read_text() == sha(original.read_bytes())


def test_readback_failure_never_publishes_success(harness: Harness) -> None:
    installer, _, dfu = harness
    dfu.bad_report = True
    events: list[UnlockProgress] = []
    with pytest.raises(ValueError):
        installer.run(IDENTITY, Event(), events.append)
    assert all(
        event.stage not in (UnlockStage.COMPLETE, UnlockStage.RESTART)
        for event in events
    )
