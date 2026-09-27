"""Immutable plans and observations for recoverable filesystem transactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from storage.errors import RecoverableWriteError

if TYPE_CHECKING:
    from storage.models import FileFingerprint, FlushResult
    from storage.paths import DevicePath, HostPath


@dataclass(frozen=True, slots=True)
class FileContent:
    """Expected bytes, independent of filesystem identity or connection."""

    size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            self.size < 0
            or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError(
                "File content requires a nonnegative size and lowercase SHA-256"
            )

    @classmethod
    def from_fingerprint(cls, fingerprint: FileFingerprint) -> FileContent:
        return cls(fingerprint.size, fingerprint.sha256)


@dataclass(frozen=True, slots=True)
class FilePrecondition:
    path: DevicePath
    fingerprint: FileFingerprint | None = None


@dataclass(frozen=True, slots=True)
class TransactionWrite:
    path: DevicePath
    source: bytes | HostPath
    content: FileContent
    expected: FileFingerprint | None = None
    modified_ns: int | None = None

    def __post_init__(self) -> None:
        if self.modified_ns is not None and not 0 <= self.modified_ns < 1 << 63:
            raise ValueError("A transaction modification time is out of range")


@dataclass(frozen=True, slots=True)
class TransactionRemoval:
    path: DevicePath
    expected: FileFingerprint


@dataclass(frozen=True, slots=True)
class TransactionRecoveryFile:
    """Verified Host material for restoring one prior device file."""

    path: DevicePath
    source: HostPath
    content: FileContent
    modified_ns: int | None = None

    def __post_init__(self) -> None:
        if self.modified_ns is not None and not 0 <= self.modified_ns < 1 << 63:
            raise ValueError("A recovery modification time is out of range")


@dataclass(frozen=True, slots=True)
class TransactionRecoveryMaterial:
    """Opaque identity and Host files backing bounded transaction recovery."""

    identity: str
    files: tuple[TransactionRecoveryFile, ...]

    def __post_init__(self) -> None:
        if not self.identity.strip() or len(self.identity.encode("utf-8")) > 1024:
            raise ValueError("Transaction recovery material needs a bounded identity")


@dataclass(frozen=True, slots=True)
class StorageTransaction:
    """Writes publish in order; removals follow verification of all writes."""

    writes: tuple[TransactionWrite, ...]
    removals: tuple[TransactionRemoval, ...] = ()
    dependencies: tuple[FilePrecondition, ...] = ()
    reserve_bytes: int = 0
    recovery_material: TransactionRecoveryMaterial | None = None
    journal_identity: str | None = None

    def __post_init__(self) -> None:
        identity = self.journal_identity
        if identity is not None and (
            len(identity) != 32
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError(
                "A transaction journal identity must be 32 lowercase hexadecimal characters"
            )


class TransactionState(StrEnum):
    STAGING = "staging"
    PREPARED = "prepared"
    PUBLISHING = "publishing"
    COMMITTED = "committed"
    RESTORING = "restoring"
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class TransactionJournalStatus:
    """Recorded completion and identity correlation, never mutation authority."""

    state: TransactionState
    identity_matches: bool


@dataclass(frozen=True, slots=True)
class TransactionFailureFacts:
    journal_path: DevicePath
    state: TransactionState
    publication_started: bool
    content_verified: bool
    recovery_material_identity: str = ""

    @property
    def device_changed(self) -> bool:
        return self.publication_started


class TransactionPreparedError(RecoverableWriteError):
    """A durable transaction journal exists, but publication did not begin."""

    def __init__(self, message: str, facts: TransactionFailureFacts) -> None:
        super().__init__(message, str(facts.journal_path), False)
        self.facts = facts


class TransactionInterruptedError(RecoverableWriteError):
    """A transaction stopped after publication may have changed the Volume."""

    def __init__(self, message: str, facts: TransactionFailureFacts) -> None:
        super().__init__(message, str(facts.journal_path), facts.publication_started)
        self.facts = facts


class TransactionDurabilityPendingError(TransactionInterruptedError):
    """All resulting files verified, but the Volume barrier did not complete."""


@dataclass(frozen=True, slots=True)
class TransactionValidation:
    required_bytes: int


@dataclass(frozen=True, slots=True)
class TransactionProgress:
    state: TransactionState
    completed: int
    total: int
    path: DevicePath | None = None


class TransactionActivityPhase(StrEnum):
    VERIFYING_STAGED = "verifying_staged"
    VERIFYING_WRITES = "verifying_writes"
    VERIFYING_RECOVERY = "verifying_recovery"
    CHECKING_DEPENDENCIES = "checking_dependencies"
    INSPECTING = "inspecting"
    RECHECKING = "rechecking"
    FLUSHING = "flushing"


@dataclass(frozen=True, slots=True)
class TransactionActivity:
    """Read/flush progress, separate from durable journal state transitions."""

    phase: TransactionActivityPhase
    completed: int = 0
    total: int | None = None
    path: DevicePath | None = None


@dataclass(frozen=True, slots=True)
class TransactionRecovery:
    """Read-only observation; restoration rechecks its journal and every file."""

    journal_path: DevicePath
    journal_fingerprint: FileFingerprint
    state: TransactionState
    files: tuple[FilePrecondition, ...]
    recovery_material_identity: str = ""
    recovery_material_paths: tuple[DevicePath, ...] = ()


@dataclass(frozen=True, slots=True)
class TransactionResult:
    recovery: TransactionRecovery
    flush: FlushResult
