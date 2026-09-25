"""Public interface for iOpenPod's Device Registry boundary."""

from device_registry.authority import (
    SYSINFO_AUTHORITY_FILENAME,
    DeviceMetadataPlan,
    authority_covers_metadata,
    reconcile_device_metadata,
)
from device_registry.data.catalog import DEFAULT_CATALOG
from device_registry.metadata import parse_sysinfo, parse_sysinfo_extended
from device_registry.models import (
    ArtworkCapabilities,
    ArtworkFormat,
    ArtworkPixelFormat,
    ArtworkUsage,
    AudioCapabilities,
    ConnectionMode,
    DatabaseCapabilities,
    DatabaseChecksum,
    DeviceCapabilities,
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    DisplayCapabilities,
    EvidenceAuthority,
    IdentificationIssue,
    IdentificationIssueCode,
    IdentificationResult,
    IdentificationStatus,
    StorageTechnology,
    UsbIdentifier,
    VideoCapabilities,
)
from device_registry.registry import DeviceRegistry

DEFAULT_DEVICE_REGISTRY = DeviceRegistry(DEFAULT_CATALOG)

__all__ = [
    "DEFAULT_DEVICE_REGISTRY",
    "SYSINFO_AUTHORITY_FILENAME",
    "ArtworkCapabilities",
    "ArtworkFormat",
    "ArtworkPixelFormat",
    "ArtworkUsage",
    "AudioCapabilities",
    "ConnectionMode",
    "DatabaseCapabilities",
    "DatabaseChecksum",
    "DeviceCapabilities",
    "DeviceEvidence",
    "DeviceIdentifier",
    "DeviceMetadataPlan",
    "DeviceProfile",
    "DeviceRegistry",
    "DisplayCapabilities",
    "EvidenceAuthority",
    "IdentificationIssue",
    "IdentificationIssueCode",
    "IdentificationResult",
    "IdentificationStatus",
    "StorageTechnology",
    "UsbIdentifier",
    "VideoCapabilities",
    "authority_covers_metadata",
    "parse_sysinfo",
    "parse_sysinfo_extended",
    "reconcile_device_metadata",
]
