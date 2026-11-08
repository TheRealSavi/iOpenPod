"""Public interface for iOpenPod's Device Registry boundary."""

from device_registry.authority import (
    SYSINFO_AUTHORITY_FILENAME,
    SYSINFO_AUTHORITY_VERSION,
    DeviceMetadataPlan,
    authority_covers_metadata,
    reconcile_device_metadata,
)
from device_registry.data.catalog import DEFAULT_CATALOG
from device_registry.extras import resolve_extras_support
from device_registry.firmware import resolve_firmware_target, strongest_values
from device_registry.identifiers import normalize_product_serial
from device_registry.metadata import parse_sysinfo, parse_sysinfo_extended
from device_registry.models import (
    AlarmFormat,
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
    ExtrasCapabilities,
    ExtrasSupport,
    FeatureSupport,
    FirmwareTarget,
    GeniusCapabilities,
    IdentificationIssue,
    IdentificationIssueCode,
    IdentificationResult,
    IdentificationStatus,
    PreferencesSupport,
    StorageTechnology,
    UsbIdentifier,
    VideoCapabilities,
)
from device_registry.preferences import resolve_preferences_support
from device_registry.registry import DeviceRegistry

DEFAULT_DEVICE_REGISTRY = DeviceRegistry(DEFAULT_CATALOG)

__all__ = [
    "DEFAULT_DEVICE_REGISTRY",
    "SYSINFO_AUTHORITY_FILENAME",
    "SYSINFO_AUTHORITY_VERSION",
    "AlarmFormat",
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
    "ExtrasCapabilities",
    "ExtrasSupport",
    "FeatureSupport",
    "FirmwareTarget",
    "GeniusCapabilities",
    "IdentificationIssue",
    "IdentificationIssueCode",
    "IdentificationResult",
    "IdentificationStatus",
    "PreferencesSupport",
    "StorageTechnology",
    "UsbIdentifier",
    "VideoCapabilities",
    "authority_covers_metadata",
    "normalize_product_serial",
    "parse_sysinfo",
    "parse_sysinfo_extended",
    "reconcile_device_metadata",
    "resolve_extras_support",
    "resolve_firmware_target",
    "resolve_preferences_support",
    "strongest_values",
]
