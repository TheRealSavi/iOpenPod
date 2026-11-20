"""One selected Classic's initial unlock, with no automatic persistent-write retry."""

from __future__ import annotations

import json
import re
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from threading import Event
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID, uuid4

from storage import (
    AtomicHostFile,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlSession,
)
from storage.host_files import lock_host_file

from .bootloader_bundle import (
    WriterPlan,
    sha,
)
from .bootloader_dfu import ClassicBootDfu
from .bootloader_targets import CLASSIC_BOOTLOADERS, bootloader_target
from .paths import firmware_directory
from .shared_bootloader import IDENTIFIER, VERSION, SharedBootloaderBundle

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from iOpenPod.app.models.device import ActiveIPod

INTERFACE = UUID("b8085869-feb9-404b-8cb1-1e5c14fa8c54")


def _valid_serial(value: object) -> bool:
    return (
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{8,20}", value) is not None
    )


def decode_bootloader_receipt(raw: bytes) -> dict[str, object]:
    """Read a saved JSON object; each caller validates its phase-specific fields."""
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid bootloader receipt")
    # JSON guarantees string keys, but field values still require validation.
    return cast("dict[str, object]", value)


def _receipt_text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Invalid bootloader receipt field: {key}")
    return value


class UnlockStage(StrEnum):
    READY = "ready"
    WAITING_DFU = "waiting_dfu"
    CHECKING = "checking"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    RESTART = "restart"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELED = "canceled"


@dataclass(frozen=True)
class UnlockProgress:
    stage: UnlockStage = UnlockStage.READY
    percent: int | None = None
    detail: str = ""
    already_unlocked: bool = False


@dataclass(frozen=True)
class UnlockIdentity:
    serial: str
    model: str
    # A hardware constraint, never the running OS's UpdaterFamilyID. Some model
    # numbers span revisions 35 and 38; only DFU SysCfg can distinguish them.
    family: int | None = 33
    shared_os: bool = False
    reported_family: int | None = None
    reported_version: str = ""

    def __post_init__(self) -> None:
        if (
            not _valid_serial(self.serial)
            or not any(self.model in target.models for target in CLASSIC_BOOTLOADERS)
            or (
                self.family is not None
                and self.model not in bootloader_target(self.family).models
            )
            or type(self.shared_os) is not bool
            or (
                self.reported_family is not None
                and (type(self.reported_family) is not int or self.reported_family < 0)
            )
            or type(self.reported_version) is not str
            or len(self.reported_version) > 128
        ):
            raise ValueError("Unsupported iPod identity")


def identity_from_record(record: Mapping[str, object]) -> UnlockIdentity:
    """Validate the selected identity persisted by either firmware workflow."""
    # Receipts from the original family-33-only installer omitted this field.
    family = record.get("family", 33)
    if family is not None and type(family) is not int:
        raise ValueError("Invalid bootloader receipt field: family")
    shared_os = record.get("shared_os", False)
    if type(shared_os) is not bool:
        raise ValueError("Invalid bootloader receipt field: shared_os")
    reported_family = record.get("reported_family")
    if reported_family is not None and type(reported_family) is not int:
        raise ValueError("Invalid bootloader receipt field: reported_family")
    reported_version = record.get("reported_version", "")
    if not isinstance(reported_version, str):
        raise ValueError("Invalid bootloader receipt field: reported_version")
    return UnlockIdentity(
        _receipt_text(record, "serial"),
        _receipt_text(record, "model"),
        family,
        shared_os,
        reported_family,
        reported_version,
    )


def supported_identity(
    active: ActiveIPod | None, platform: str
) -> UnlockIdentity | None:
    if active is None or platform != "windows":
        return None
    try:
        targets = [
            t for t in CLASSIC_BOOTLOADERS if active.profile.model_number in t.models
        ]
        if not targets:
            return None
        return UnlockIdentity(
            active.serial_number,
            active.profile.model_number,
            targets[0].family if len(targets) == 1 else None,
            reported_family=active.updater_family_id
            if active.updater_family_current
            else None,
            reported_version=active.firmware_version
            if active.firmware_version_current
            else "",
        )
    except ValueError:
        return None


def verify_syscfg(data: bytes, identity: UnlockIdentity) -> int:
    if len(data) < 24:
        raise ValueError("Missing iPod identity in boot flash")
    magic, size, capacity, version, reserved, count = struct.unpack_from("<6I", data)
    if (
        (magic, capacity, version, reserved) != (0x53436667, 0x2000, 0x10001, 0)
        or size != 24 + 20 * count
        or not 24 <= size <= min(len(data), 8192)
    ):
        raise ValueError("Unsupported SysCfg layout")
    entries: dict[str, bytes] = {}
    for offset in range(24, size, 20):
        key = data[offset : offset + 4][::-1].decode("ascii")
        if key in entries:
            raise ValueError("Duplicate SysCfg entry")
        entries[key] = data[offset + 4 : offset + 20]

    def value(key: str) -> str:
        raw = entries.get(key, b"")
        text, separator, padding = raw.partition(b"\0")
        if not separator or any(padding):
            raise ValueError("Invalid SysCfg text")
        return text.decode("ascii")

    hardware = struct.unpack_from("<I", entries.get("HwVr", bytes(16)), 4)[0]
    target = next((t for t in CLASSIC_BOOTLOADERS if t.hardware == hardware), None)
    if (
        value("SrNm") != identity.serial
        or value("Mod#") != identity.model
        or target is None
        or identity.model not in target.models
        or (
            identity.family is not None
            and not identity.shared_os
            and target.family != identity.family
        )
    ):
        raise ValueError("The DFU iPod does not match the selected Classic")
    return target.family


class UnlockStorage(Protocol):
    @property
    def platform_name(self) -> str: ...
    def discover_usb_control(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]: ...
    def open_usb_control_session(
        self, endpoint: UsbControlEndpoint
    ) -> UsbControlSession: ...


class BootloaderInstaller:
    def __init__(
        self,
        storage: UnlockStorage,
        directory: Path | None = None,
        *,
        dfu_factory: Callable[
            [UsbControlSession, Event], ClassicBootDfu
        ] = ClassicBootDfu,
        writer_wait: float = 90,
        detection_timeout: float = 180,
    ) -> None:
        self.storage = storage
        self.directory = (
            directory if directory is not None else firmware_directory() / "bootloader"
        )
        self._dfu = dfu_factory
        self._writer_wait = writer_wait
        self._detection_timeout = detection_timeout

    @property
    def platform(self) -> str:
        return self.storage.platform_name

    def pending_identity(self) -> UnlockIdentity | None:
        """Expose one unfinished handoff even if no filesystem can be mounted."""
        pending: list[UnlockIdentity] = []
        for path in self.directory.glob("*/operation.json"):
            raw = AtomicHostFile(path).read_bytes(max_bytes=16384)
            if raw is None:
                continue
            record = decode_bootloader_receipt(raw)
            if record.get("state") == "handoff":
                identity = identity_from_record(record)
                if path.parent.name != identity.serial:
                    raise ValueError("Bootloader receipt identity mismatch")
                pending.append(identity)
        return pending[0] if len(pending) == 1 else None

    def _endpoint(self) -> UsbControlEndpoint | None:
        endpoints = self.storage.discover_usb_control(INTERFACE, 0x05AC, 0x1223)
        if len(endpoints) > 1:
            raise ValueError("Connect only the selected iPod while unlocking")
        return endpoints[0] if endpoints else None

    def run(
        self,
        identity: UnlockIdentity,
        cancel: Event,
        publish: Callable[[UnlockProgress], None],
        *,
        verify_only: bool = False,
    ) -> bool:
        directory = self.directory / identity.serial
        directory.mkdir(parents=True, exist_ok=True)
        # Keep the application-level claim across USB handle closure and the
        # RAM writer's return, when Storage cannot retain the old connection.
        with lock_host_file(directory / "operation.json"):
            return self._run(identity, cancel, publish, verify_only=verify_only)

    def _run(
        self,
        identity: UnlockIdentity,
        cancel: Event,
        publish: Callable[[UnlockProgress], None],
        *,
        verify_only: bool,
    ) -> bool:
        if self.platform != "windows":
            raise ValueError("Bootloader installation currently requires Windows")
        bundle = SharedBootloaderBundle()  # Check assets before touching USB.
        directory = self.directory / identity.serial
        directory.mkdir(parents=True, exist_ok=True)
        journal = AtomicHostFile(directory / "operation.json")
        previous = journal.read_bytes(max_bytes=16384)
        pending: dict[str, object] = (
            decode_bootloader_receipt(previous) if previous is not None else {}
        )
        if previous is not None and pending.get("state") not in (
            "prepared",
            "handoff",
            "verified",
        ):
            raise ValueError(
                "Invalid bootloader installation receipt; no write was attempted"
            )
        if verify_only and pending.get("state") != "handoff":
            raise ValueError(
                "There is no pending installation to verify; no write was attempted"
            )
        if (
            pending.get("state") == "handoff"
            and identity_from_record(pending) != identity
        ):
            raise ValueError("Bootloader receipt identity mismatch")
        publish(UnlockProgress(UnlockStage.WAITING_DFU))
        deadline = time.monotonic() + self._detection_timeout
        endpoint = self._endpoint()
        while endpoint is None:
            if cancel.wait(0.5):
                raise InterruptedError("Unlock canceled before installation")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "No Classic found in DFU. Check the cable and Apple Mobile Device USB driver, then reopen the setup."
                )
            endpoint = self._endpoint()
        if cancel.is_set():
            raise InterruptedError("Unlock canceled before installation")
        if pending.get("state") == "handoff":
            # A previous process may have exited after launching the writer.
            # Only verify its nonce; never prepare a second installation.
            plan = WriterPlan(
                bytes.fromhex(_receipt_text(pending, "nonce")),
                _receipt_text(pending, "before_sha"),
                _receipt_text(pending, "target_sha"),
                _receipt_text(pending, "after_sha"),
                _receipt_text(pending, "outside_sha"),
                b"",
            )
            publish(UnlockProgress(UnlockStage.VERIFYING))
            handoff_time = pending.get("handoff_time", 0)
            if not isinstance(handoff_time, (int, float, str)):
                raise ValueError("Invalid bootloader receipt field: handoff_time")
            elapsed = max(0.0, time.time() - float(handoff_time))
            time.sleep(max(0, self._writer_wait - elapsed))
            self._verify(plan, journal, pending, publish)
            return False
        publish(UnlockProgress(UnlockStage.CHECKING))
        with self.storage.open_usb_control_session(endpoint) as session:
            dfu = self._dfu(session, cancel)
            dfu.qualify()

            def quiet(_done: int, _total: int) -> None:
                pass

            syscfg = dfu.nor(0, 8192, quiet)
            hardware_family = verify_syscfg(syscfg, identity)
            installed = dfu.nor(0x8000, 0x20000, quiet)
            body = dfu.plaintext(installed)
            if bundle.is_current(body):
                dfu.clean()
                journal.replace_bytes(
                    self._encode(
                        {
                            "state": "verified",
                            "identifier": IDENTIFIER,
                            "version": VERSION,
                            "serial": identity.serial,
                            "model": identity.model,
                            "family": identity.family,
                            "shared_os": identity.shared_os,
                            "reported_family": identity.reported_family,
                            "reported_version": identity.reported_version,
                            "hardware_family": hardware_family,
                            "body_sha256": sha(body),
                            "already_unlocked": True,
                        }
                    )
                )
                return True
            candidate = bundle.apply(body, hardware_family)
            nor = dfu.nor(
                0,
                0x100000,
                lambda done, total: publish(
                    UnlockProgress(UnlockStage.CHECKING, done * 100 // total)
                ),
            )
            if nor[:8192] != syscfg or nor[0x8000:0x28000] != installed:
                raise ValueError("Boot flash changed during preparation")
            original = AtomicHostFile(directory / "original.nor")
            original_hash = AtomicHostFile(directory / "original.sha256")
            if not original.exists():
                original.create_bytes(nor)  # One initial 1 MiB copy, reused thereafter.
                original_hash.replace_bytes(sha(nor).encode("ascii"))
            else:
                retained = original.read_bytes(max_bytes=0x100000)
                checksum = original_hash.read_bytes(max_bytes=64)
                if checksum is None and retained == nor:
                    # Recover a Host interruption between the two initial
                    # publications without acquiring another original copy.
                    checksum = sha(nor).encode("ascii")
                    original_hash.replace_bytes(checksum)
                if (
                    retained is None
                    or len(retained) != 0x100000
                    or checksum != sha(retained).encode("ascii")
                ):
                    raise ValueError(
                        "The retained original boot flash copy is incomplete or damaged"
                    )
            sealed = dfu.seal(candidate)
            plan = bundle.writer(nor, sealed, uuid4().bytes)
            pending = {
                "state": "prepared",
                "identifier": IDENTIFIER,
                "version": VERSION,
                "serial": identity.serial,
                "model": identity.model,
                "family": identity.family,
                "shared_os": identity.shared_os,
                "reported_family": identity.reported_family,
                "reported_version": identity.reported_version,
                "hardware_family": hardware_family,
                "body_sha256": sha(candidate),
                "nonce": plan.nonce.hex(),
                "before_sha": plan.before_sha,
                "target_sha": plan.target_sha,
                "after_sha": plan.after_sha,
                "outside_sha": plan.outside_sha,
                "writer_sha": sha(plan.image),
            }
            journal.replace_bytes(self._encode(pending))

            def handoff() -> None:
                if cancel.is_set():
                    raise InterruptedError("Unlock canceled before installation")
                pending["state"] = "handoff"
                pending["handoff_time"] = time.time()
                journal.replace_bytes(self._encode(pending))
                publish(UnlockProgress(UnlockStage.INSTALLING))

            dfu.download(plan.image, handoff)
        # Writer owns USB until it returns. Do not send probes while NOR is busy.
        time.sleep(self._writer_wait)
        self._verify(plan, journal, pending, publish)
        return False

    @staticmethod
    def _encode(value: Mapping[str, object]) -> bytes:
        return (json.dumps(value, indent=2) + "\n").encode()

    def _verify(
        self,
        plan: WriterPlan,
        journal: AtomicHostFile,
        pending: dict[str, object],
        publish: Callable[[UnlockProgress], None],
    ) -> None:
        publish(UnlockProgress(UnlockStage.VERIFYING))
        deadline = time.monotonic() + 60
        last_error = "No DFU interface returned"
        while time.monotonic() < deadline:
            try:
                endpoint = self._endpoint()
                if endpoint is not None:
                    with self.storage.open_usb_control_session(endpoint) as session:
                        dfu = self._dfu(session, Event())
                        dfu.fingerprint()
                        record = dfu.report(plan)
                        dfu.clean()
                    pending["state"] = "verified"
                    pending["report_hex"] = record.hex()
                    journal.replace_bytes(self._encode(pending))
                    return
            except (UsbControlError, OSError) as error:
                last_error = str(error)
            time.sleep(2)
        raise TimeoutError(
            f"Installation could not be verified. No write was retried. Keep this iPod connected and reopen setup to check the result. {last_error}"
        )
