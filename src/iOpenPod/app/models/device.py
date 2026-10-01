"""Path-free Application Layer state for device discovery and selection."""

from dataclasses import dataclass
from enum import StrEnum

from device_registry import DeviceProfile, IdentificationStatus
from iOpenPod.app.models.ipod_preferences import IPodPreferenceSection
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint


@dataclass(frozen=True, slots=True)
class DeviceCandidateId:
    """Opaque identity for one currently mounted candidate connection."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("A Device Candidate ID must not be empty")


class DeviceReadiness(StrEnum):
    """Why a discovered candidate can or cannot become the Active iPod."""

    READY = "ready"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    RECOVERY_MODE = "recovery_mode"
    DATABASE_MISSING = "database_missing"
    DATABASE_UNSUPPORTED = "database_unsupported"
    INSPECTION_FAILED = "inspection_failed"
    SYNC_RECOVERY_REQUIRED = "sync_recovery_required"


class DeviceCandidateIssueCode(StrEnum):
    """Stable issue vocabulary suitable for GUI translation and tests."""

    TIMEZONE_UNCERTAIN = "timezone_uncertain"
    METADATA_UNREADABLE = "metadata_unreadable"
    METADATA_RECONCILIATION_SKIPPED = "metadata_reconciliation_skipped"
    METADATA_RECONCILIATION_FAILED = "metadata_reconciliation_failed"
    HARDWARE_PROBE_SETUP_REQUIRED = "hardware_probe_setup_required"
    HARDWARE_PROBE_FAILED = "hardware_probe_failed"
    DATABASE_EMPTY = "database_empty"
    DATABASE_FALLBACK = "database_fallback"
    ARTWORK_DATABASE_UNREADABLE = "artwork_database_unreadable"
    PHOTOS_DATABASE_UNREADABLE = "photos_database_unreadable"
    PLAYBACK_SIDECAR_FLUSH_PENDING = "playback_sidecar_flush_pending"
    VOLUME_PRESENTATION_INCOMPLETE = "volume_presentation_incomplete"
    TRANSACTION_CLEANUP_PENDING = "transaction_cleanup_pending"
    TRANSACTION_CLEANUP_FLUSH_PENDING = "transaction_cleanup_flush_pending"
    INSPECTION_FAILED = "inspection_failed"


@dataclass(frozen=True, slots=True)
class DeviceCandidateIssue:
    code: DeviceCandidateIssueCode
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DeviceCandidate:
    """One discovered Volume translated into path-free application state."""

    id: DeviceCandidateId
    display_name: str
    host_description: str
    bus: str
    identification_status: IdentificationStatus
    readiness: DeviceReadiness
    profile: DeviceProfile | None
    total_bytes: int
    available_bytes: int
    issues: tuple[DeviceCandidateIssue, ...] = ()

    @property
    def selectable(self) -> bool:
        return self.readiness in (
            DeviceReadiness.READY,
            DeviceReadiness.SYNC_RECOVERY_REQUIRED,
        )

    @property
    def profile_name(self) -> str:
        return self.profile.display_name if self.profile is not None else ""

    @property
    def model_number(self) -> str:
        return self.profile.model_number if self.profile is not None else ""

    @property
    def used_bytes(self) -> int:
        return max(0, self.total_bytes - self.available_bytes)


@dataclass(frozen=True, slots=True)
class DeviceDiscoveryIssue:
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class DeviceDiscovery:
    """Complete replacement snapshot for the Device Picker."""

    candidates: tuple[DeviceCandidate, ...]
    issues: tuple[DeviceDiscoveryIssue, ...] = ()
    active_candidate_id: DeviceCandidateId | None = None

    def candidate(self, candidate_id: DeviceCandidateId) -> DeviceCandidate | None:
        return next(
            (
                candidate
                for candidate in self.candidates
                if candidate.id == candidate_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class ActiveIPod:
    """The one selected iPod and its parsed, read-only Library snapshot."""

    candidate: DeviceCandidate
    profile: DeviceProfile
    library: LibrarySnapshot
    database_name: str
    database_fingerprint: FileFingerprint
    artwork_database_fingerprint: FileFingerprint | None = None
    photos_database_fingerprint: FileFingerprint | None = None
    preferences: tuple[IPodPreferenceSection, ...] = ()

    @property
    def display_name(self) -> str:
        return self.library.device_name.strip() or self.candidate.display_name
