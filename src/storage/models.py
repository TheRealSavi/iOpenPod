"""Immutable data structures crossing the Storage interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from storage.paths import DevicePath


@dataclass(frozen=True, slots=True)
class PhysicalDeviceId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("A Physical Device ID must not be empty")


@dataclass(frozen=True, slots=True)
class VolumeId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("A Volume ID must not be empty")


@dataclass(frozen=True, slots=True)
class ConnectionGeneration:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("A Connection Generation must not be empty")


class DeviceBus(StrEnum):
    USB = "usb"
    FIREWIRE = "firewire"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HardwareIdentifiers:
    """Generic Host-observed identifiers suitable for Application translation."""

    usb_vendor_id: int | None = None
    usb_product_id: int | None = None
    product_serial: str = ""
    transport_serial: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("usb_vendor_id", self.usb_vendor_id),
            ("usb_product_id", self.usb_product_id),
        ):
            if value is not None and not 0 <= value <= 0xFFFF:
                raise ValueError(f"{name} must be a 16-bit unsigned integer")


class HardwareProbeIssueCode(StrEnum):
    """Stable, device-agnostic reasons a Host hardware probe was incomplete."""

    SETUP_REQUIRED = "setup_required"
    ACCESS_DENIED = "access_denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HardwareProperty:
    """One opaque property reported by a Host device manager."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A Hardware Property name must not be empty")


@dataclass(frozen=True, slots=True)
class ScsiVpdPagePlan:
    """Generic instructions for following one vendor VPD page index."""

    index_page: int
    first_data_page: int
    last_data_page: int
    scan_range_when_index_empty: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("index_page", self.index_page),
            ("first_data_page", self.first_data_page),
            ("last_data_page", self.last_data_page),
        ):
            if not 0 <= value <= 0xFF:
                raise ValueError(f"{name} must be an 8-bit VPD page code")
        if self.first_data_page > self.last_data_page:
            raise ValueError("The first VPD data page must not exceed the last")


@dataclass(frozen=True, slots=True)
class HardwareProbeObservation:
    """Generic SCSI or Host observation for Application-layer translation."""

    source: str
    vendor: str = ""
    product: str = ""
    firmware_revision: str = ""
    unit_serial: str = ""
    transport_serial: str = ""
    vendor_payload: bytes = b""
    host_properties: tuple[HardwareProperty, ...] = ()

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("A Hardware Probe source must not be empty")


@dataclass(frozen=True, slots=True)
class HardwareProbeIssue:
    code: HardwareProbeIssueCode
    detail: str
    setup_asset: str = ""

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("A Hardware Probe issue needs an explanation")


@dataclass(frozen=True, slots=True)
class HardwareProbeResult:
    observations: tuple[HardwareProbeObservation, ...] = ()
    issues: tuple[HardwareProbeIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class PhysicalDevice:
    id: PhysicalDeviceId
    display_name: str
    bus: DeviceBus
    removable: bool
    identifiers: HardwareIdentifiers = HardwareIdentifiers()


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    readable: bool
    writable: bool
    case_sensitive: bool | None
    max_file_size_bytes: int | None
    max_component_length: int | None
    allocation_unit_size: int | None
    unsafe_write_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("max_file_size_bytes", self.max_file_size_bytes),
            ("max_component_length", self.max_component_length),
            ("allocation_unit_size", self.allocation_unit_size),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when known")

    @property
    def safe_for_writes(self) -> bool:
        return self.readable and self.writable and not self.unsafe_write_reasons


@dataclass(frozen=True, slots=True)
class Volume:
    id: VolumeId
    physical_device_id: PhysicalDeviceId
    label: str
    filesystem_type: str
    total_bytes: int
    available_bytes: int
    capabilities: StorageCapabilities

    def __post_init__(self) -> None:
        if self.total_bytes < 0 or self.available_bytes < 0:
            raise ValueError("Volume byte counts must be non-negative")
        if self.available_bytes > self.total_bytes:
            raise ValueError("Available Volume bytes cannot exceed total bytes")


@dataclass(frozen=True, slots=True)
class MountPoint:
    path: Path

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ValueError("A Mount Point must be an absolute Host path")


@dataclass(frozen=True, slots=True)
class VolumeObservation:
    physical_device: PhysicalDevice
    volume: Volume
    mount_point: MountPoint
    mount_instance: str

    def __post_init__(self) -> None:
        if self.volume.physical_device_id != self.physical_device.id:
            raise ValueError("A Volume must belong to its observed Physical Device")
        if not self.mount_instance.strip():
            raise ValueError("A mount instance must not be empty")

    @property
    def connection_key(self) -> str:
        return "|".join(
            (
                self.physical_device.id.value,
                self.volume.id.value,
                self.mount_instance,
            )
        )


@dataclass(frozen=True, slots=True)
class MountedVolume:
    observation: VolumeObservation
    connection_generation: ConnectionGeneration

    @property
    def physical_device(self) -> PhysicalDevice:
        return self.observation.physical_device

    @property
    def volume(self) -> Volume:
        return self.observation.volume

    @property
    def mount_point(self) -> MountPoint:
        return self.observation.mount_point

    @property
    def mount_instance(self) -> str:
        return self.observation.mount_instance


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    volumes: tuple[MountedVolume, ...]
    issues: tuple[DiscoveryIssue, ...] = ()


class AccessMode(StrEnum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class DeviceEntryKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    LINK_OR_REPARSE_POINT = "link_or_reparse_point"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DeviceEntry:
    path: DevicePath
    kind: DeviceEntryKind
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    size: int
    modified_ns: int
    device: int
    inode: int
    sha256: str

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("A file fingerprint cannot contain a negative size")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("A file fingerprint requires a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Lightweight identity used to validate a cached read-only file range."""

    size: int
    modified_ns: int
    device: int
    inode: int

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("A file identity cannot contain a negative size")


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    data: bytes
    fingerprint: FileFingerprint


@dataclass(frozen=True, slots=True)
class FileRangeSnapshot:
    data: bytes
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class WriteResult:
    path: DevicePath
    fingerprint: FileFingerprint
    replaced_existing: bool


@dataclass(frozen=True, slots=True)
class RecoveryWriteResult:
    write: WriteResult
    recovery_path: DevicePath
    flush: FlushResult


@dataclass(frozen=True, slots=True)
class CopyResult:
    bytes_copied: int
    sha256: str
    source_fingerprint: FileFingerprint


@dataclass(frozen=True, slots=True)
class TrashEntry:
    original_path: DevicePath
    trash_path: DevicePath
    fingerprint: FileFingerprint


@dataclass(frozen=True, slots=True)
class FlushResult:
    complete: bool
    detail: str


@dataclass(frozen=True, slots=True)
class EjectResult:
    """Successful native safe-removal confirmation for one Physical Device."""

    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("An Eject Result needs an explanation")
