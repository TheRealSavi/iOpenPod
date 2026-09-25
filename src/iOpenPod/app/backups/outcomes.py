"""Typed terminal outcomes for Backup application workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from iOpenPod.app.backups.models import (
        BackupExportResult,
        BackupInventory,
        SnapshotInfo,
    )
    from storage import DevicePath, FlushResult


class FollowUpRequirement(StrEnum):
    """Whether an application adapter must perform a follow-up action."""

    NONE = "none"
    REQUIRED = "required"


class DeviceWritePolicy(StrEnum):
    """When another device mutation may begin after a terminal outcome."""

    ALLOWED = "allowed"
    BLOCKED_UNTIL_RELOAD = "blocked_until_reload"
    BLOCKED_UNTIL_DURABILITY_CONFIRMED = "blocked_until_durability_confirmed"
    BLOCKED_UNTIL_RECOVERY = "blocked_until_recovery"


class DisconnectGuidance(StrEnum):
    """Disconnect guidance attached to a completed operation."""

    STANDARD = "standard"
    SAFE_EJECT_REQUIRED = "safe_eject_required"


@dataclass(frozen=True, slots=True)
class BackupFollowUp:
    """Typed application actions derived from an outcome, not GUI prose."""

    archive_refresh: FollowUpRequirement = FollowUpRequirement.NONE
    device_reload: FollowUpRequirement = FollowUpRequirement.NONE
    device_writes: DeviceWritePolicy = DeviceWritePolicy.ALLOWED
    disconnect: DisconnectGuidance = DisconnectGuidance.STANDARD


class BackupFailureCode(StrEnum):
    """Stable categories suitable for controller policy and diagnostics."""

    ARCHIVE_BUSY = "archive.busy"
    ARCHIVE_INVALID = "archive.invalid"
    ARCHIVE_UNAVAILABLE = "archive.unavailable"
    DEVICE_CHANGED = "device.changed"
    DEVICE_IDENTITY_MISMATCH = "device.identity_mismatch"
    DEVICE_IDENTITY_UNSTABLE = "device.identity_unstable"
    DEVICE_UNAVAILABLE = "device.unavailable"
    INSUFFICIENT_SPACE = "storage.insufficient_space"
    SOURCE_CHANGED = "source.changed"
    UNSAFE_DESTINATION = "destination.unsafe"
    VERIFICATION_FAILED = "verification.failed"
    UNEXPECTED = "operation.unexpected"


@dataclass(frozen=True, slots=True)
class BackupFailure:
    """One expected failure with stable policy and human-readable guidance."""

    code: BackupFailureCode
    summary: str
    action: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class BrowseCompleted:
    """The current Backup Archive inventory was read successfully."""

    inventory: BackupInventory
    kind: Literal["browse.completed"] = field(
        default="browse.completed",
        init=False,
    )


@dataclass(frozen=True, slots=True)
class BrowseFailed:
    """The Backup Archive could not produce a trusted browse projection."""

    failure: BackupFailure
    kind: Literal["browse.failed"] = field(default="browse.failed", init=False)


@dataclass(frozen=True, slots=True)
class BrowseCancelled:
    """Browsing stopped at a cancellation checkpoint without changing an archive."""

    kind: Literal["browse.cancelled"] = field(
        default="browse.cancelled",
        init=False,
    )


type BrowseOutcome = BrowseCompleted | BrowseCancelled | BrowseFailed


@dataclass(frozen=True, slots=True)
class CaptureCreated:
    """A new, verified Backup Snapshot was published."""

    snapshot: SnapshotInfo
    kind: Literal["capture.created"] = field(default="capture.created", init=False)


@dataclass(frozen=True, slots=True)
class CaptureUnchanged:
    """The device catalog still matches an existing Backup Snapshot."""

    snapshot_id: str
    kind: Literal["capture.unchanged"] = field(
        default="capture.unchanged",
        init=False,
    )


@dataclass(frozen=True, slots=True)
class CaptureCancelled:
    """Capture stopped safely before publishing a new Backup Snapshot."""

    kind: Literal["capture.cancelled"] = field(
        default="capture.cancelled",
        init=False,
    )


@dataclass(frozen=True, slots=True)
class CaptureFailed:
    """Capture could not publish a trustworthy Backup Snapshot."""

    failure: BackupFailure
    kind: Literal["capture.failed"] = field(default="capture.failed", init=False)


type CaptureOutcome = (
    CaptureCreated | CaptureUnchanged | CaptureCancelled | CaptureFailed
)


@dataclass(frozen=True, slots=True)
class ExportCompleted:
    """A Backup Snapshot was materialized in a new Host directory."""

    result: BackupExportResult
    kind: Literal["export.completed"] = field(default="export.completed", init=False)


@dataclass(frozen=True, slots=True)
class ExportCancelled:
    """Export stopped safely and left no partial output visible."""

    kind: Literal["export.cancelled"] = field(
        default="export.cancelled",
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ExportFailed:
    """A Backup Snapshot could not be exported safely."""

    failure: BackupFailure
    kind: Literal["export.failed"] = field(default="export.failed", init=False)


type ExportOutcome = ExportCompleted | ExportCancelled | ExportFailed


@dataclass(frozen=True, slots=True)
class BackupDiagnostic:
    """One non-fatal, machine-addressable observation from an operation."""

    code: str
    summary: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class BackupImportCounts:
    """Legacy objects categorized by their native-archive publication result."""

    devices: int = 0
    snapshots: int = 0
    content_items: int = 0


@dataclass(frozen=True, slots=True)
class ImportCompleted:
    """A read-only Legacy Backup Import completed.

    The Original source repository is immutable input to every import operation;
    source preservation is an invariant rather than a reported runtime condition.
    """

    imported: BackupImportCounts
    already_present: BackupImportCounts
    diagnostics: tuple[BackupDiagnostic, ...] = ()
    kind: Literal["import.completed"] = field(default="import.completed", init=False)


@dataclass(frozen=True, slots=True)
class ImportCancelled:
    """Legacy import stopped before publishing any new v4 snapshots."""

    kind: Literal["import.cancelled"] = field(
        default="import.cancelled",
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ImportFailed:
    """Legacy input could not be converted into trusted v4 snapshots."""

    failure: BackupFailure
    kind: Literal["import.failed"] = field(default="import.failed", init=False)


type ImportOutcome = ImportCompleted | ImportCancelled | ImportFailed


@dataclass(frozen=True, slots=True)
class RestoreCompleted:
    """The selected snapshot is verified and durably published on the iPod."""

    snapshot_id: str
    safety_snapshot_id: str
    flush: FlushResult
    kind: Literal["restore.completed"] = field(default="restore.completed", init=False)
    follow_up: BackupFollowUp = field(
        default=BackupFollowUp(
            archive_refresh=FollowUpRequirement.REQUIRED,
            device_reload=FollowUpRequirement.REQUIRED,
            device_writes=DeviceWritePolicy.BLOCKED_UNTIL_RELOAD,
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.flush.complete:
            raise ValueError(
                "Restore completion requires a complete durability barrier"
            )


@dataclass(frozen=True, slots=True)
class RestoreUnchanged:
    """The iPod already matched the selected snapshot; no write was attempted."""

    snapshot_id: str
    safety_snapshot_id: str
    kind: Literal["restore.unchanged"] = field(
        default="restore.unchanged",
        init=False,
    )
    device_mutated: Literal[False] = field(default=False, init=False)
    content_verified: Literal[True] = field(default=True, init=False)
    follow_up: BackupFollowUp = field(
        default=BackupFollowUp(
            archive_refresh=FollowUpRequirement.REQUIRED,
        ),
        init=False,
    )


@dataclass(frozen=True, slots=True)
class RestoreRecovered:
    """An interrupted restore was rolled back to its verified safety snapshot."""

    snapshot_id: str
    safety_snapshot_id: str
    flush: FlushResult
    kind: Literal["restore.recovered"] = field(default="restore.recovered", init=False)
    follow_up: BackupFollowUp = field(
        default=BackupFollowUp(
            archive_refresh=FollowUpRequirement.REQUIRED,
            device_reload=FollowUpRequirement.REQUIRED,
            device_writes=DeviceWritePolicy.BLOCKED_UNTIL_RELOAD,
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.flush.complete:
            raise ValueError(
                "Restore recovery completion requires a complete durability barrier"
            )


@dataclass(frozen=True, slots=True)
class RestoreDurabilityPending:
    """Restored content verified, but the Volume durability barrier did not."""

    snapshot_id: str
    safety_snapshot_id: str
    flush: FlushResult
    kind: Literal["restore.durability_pending"] = field(
        default="restore.durability_pending",
        init=False,
    )
    content_verified: Literal[True] = field(default=True, init=False)
    follow_up: BackupFollowUp = field(
        default=BackupFollowUp(
            archive_refresh=FollowUpRequirement.REQUIRED,
            device_reload=FollowUpRequirement.REQUIRED,
            device_writes=DeviceWritePolicy.BLOCKED_UNTIL_DURABILITY_CONFIRMED,
            disconnect=DisconnectGuidance.SAFE_EJECT_REQUIRED,
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        if self.flush.complete:
            raise ValueError(
                "Pending restore durability requires an incomplete durability barrier"
            )


@dataclass(frozen=True, slots=True)
class RestoreCancelled:
    """Restore stopped at a checkpoint before device publication began."""

    snapshot_id: str
    safety_snapshot_id: str | None = None
    kind: Literal["restore.cancelled"] = field(
        default="restore.cancelled",
        init=False,
    )
    device_mutated: Literal[False] = field(default=False, init=False)

    @property
    def follow_up(self) -> BackupFollowUp:
        return BackupFollowUp(
            archive_refresh=(
                FollowUpRequirement.REQUIRED
                if self.safety_snapshot_id is not None
                else FollowUpRequirement.NONE
            )
        )


@dataclass(frozen=True, slots=True)
class RestorePreMutationFailure:
    """Restore failed after validation began but before device publication."""

    snapshot_id: str
    failure: BackupFailure
    safety_snapshot_id: str | None = None
    kind: Literal["restore.pre_mutation_failure"] = field(
        default="restore.pre_mutation_failure",
        init=False,
    )
    device_mutated: Literal[False] = field(default=False, init=False)

    @property
    def follow_up(self) -> BackupFollowUp:
        return BackupFollowUp(
            archive_refresh=(
                FollowUpRequirement.REQUIRED
                if self.safety_snapshot_id is not None
                else FollowUpRequirement.NONE
            )
        )


@dataclass(frozen=True, slots=True)
class RestoreIncomplete:
    """Restore publication began and requires explicit journal recovery."""

    snapshot_id: str
    safety_snapshot_id: str
    recovery_journal: DevicePath
    failure: BackupFailure
    kind: Literal["restore.incomplete"] = field(
        default="restore.incomplete",
        init=False,
    )
    device_mutated: Literal[True] = field(default=True, init=False)
    content_verified: Literal[False] = field(default=False, init=False)
    follow_up: BackupFollowUp = field(
        default=BackupFollowUp(
            archive_refresh=FollowUpRequirement.REQUIRED,
            device_reload=FollowUpRequirement.REQUIRED,
            device_writes=DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY,
            disconnect=DisconnectGuidance.SAFE_EJECT_REQUIRED,
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.safety_snapshot_id.strip():
            raise ValueError("An incomplete restore requires a safety snapshot")


type RestoreOutcome = (
    RestoreCompleted
    | RestoreUnchanged
    | RestoreRecovered
    | RestoreDurabilityPending
    | RestoreCancelled
    | RestorePreMutationFailure
    | RestoreIncomplete
)

type BackupTerminalOutcome = (
    BrowseOutcome | CaptureOutcome | ExportOutcome | ImportOutcome | RestoreOutcome
)
