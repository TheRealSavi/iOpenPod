"""Typed Backup Snapshot contracts shared by the application and GUI."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from pathlib import Path

    from storage import DevicePath, FlushResult, HostPath


_ARCHIVE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_DOMAIN = "iopenpod.backup.device-identity.v1"
_LEGACY_IDENTITY_DOMAIN = "iopenpod.backup.original-device-identity.v1"


def sanitize_backup_device_id(device_id: str) -> str:
    """Match the Original iOpenPod archive-directory normalization."""

    safe = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in device_id
    )
    return safe or "unknown_device"


@dataclass(frozen=True, slots=True)
class LegacyIdentityClaim:
    """Non-reversible claim for an Original iOpenPod archive directory."""

    sha256: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("A legacy identity claim requires lowercase SHA-256")

    @classmethod
    def from_original_key(cls, value: str) -> Self:
        """Hash the archive-directory key Original iOpenPod derives from a value."""

        normalized = sanitize_backup_device_id(value)
        payload = f"{_LEGACY_IDENTITY_DOMAIN}\0{normalized}".encode(
            "utf-8", errors="surrogatepass"
        )
        return cls(hashlib.sha256(payload).hexdigest())

    def to_manifest(self) -> dict[str, str]:
        return {"algorithm": "sha256", "sha256": self.sha256}

    @classmethod
    def from_manifest(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("A legacy identity claim must be an object")
        fields = cast("dict[object, object]", value)
        if set(fields) != {"algorithm", "sha256"}:
            raise ValueError("A legacy identity claim has invalid fields")
        if fields.get("algorithm") != "sha256":
            raise ValueError("A legacy identity claim algorithm is unsupported")
        digest = fields.get("sha256")
        if not isinstance(digest, str):
            raise ValueError("A legacy identity claim digest is missing")
        return cls(digest)


@dataclass(frozen=True, slots=True)
class ArchiveKey:
    """Filesystem-safe native archive locator; never device authorization."""

    value: str

    def __post_init__(self) -> None:
        if _ARCHIVE_KEY.fullmatch(self.value) is None:
            raise ValueError(f"Invalid Backup Archive Key: {self.value!r}")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def for_identity(
        cls,
        identity: BackupDeviceIdentity,
        *,
        prefix: str = "ipod",
    ) -> Self:
        """Return a deterministic collision-resistant key for a Backup Identifier."""

        if not identity.is_stable:
            raise ValueError("An Archive Key requires a Backup Identifier")
        base = _native_archive_slug(prefix)
        return cls(f"{base[:136]}--{identity.digest[:16]}")

    @classmethod
    def for_legacy(cls, legacy_key: str) -> Self:
        """Return a deterministic namespace for one Original archive key."""

        if not legacy_key:
            raise ValueError("A legacy archive key must not be empty")
        claim = LegacyIdentityClaim.from_original_key(legacy_key)
        return cls(f"legacy--{claim.sha256[:32]}")

    @classmethod
    def for_unstable(cls, session_identity: str) -> Self:
        """Create a non-authoritative locator for one unstable connection context."""

        normalized = session_identity.strip()
        if not normalized:
            raise ValueError("An unstable Archive Key needs a session identity")
        digest = hashlib.sha256(
            ("iopenpod.backup.unstable-archive.v1\0" + normalized).encode(
                "utf-8", errors="surrogatepass"
            )
        ).hexdigest()
        return cls(f"unidentified--{digest[:32]}")


def _native_archive_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    safe = "".join(
        character if character.isascii() and character.isalnum() else "_"
        for character in normalized
    ).strip("_")
    return safe or "ipod"


class BackupIdentityClaimKind(StrEnum):
    PRODUCT_SERIAL = "product_serial"
    TRANSPORT_SERIAL = "transport_serial"
    VOLUME_ID = "volume_id"


@dataclass(frozen=True, slots=True)
class BackupIdentityClaim:
    """One non-reversible input to a version-1 Backup Identifier."""

    kind: BackupIdentityClaimKind
    sha256: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("A Backup Identifier claim requires lowercase SHA-256")

    @classmethod
    def from_hardware(
        cls,
        kind: BackupIdentityClaimKind,
        value: str,
    ) -> Self:
        canonical = unicodedata.normalize("NFC", value.strip()).casefold()
        if (
            kind is BackupIdentityClaimKind.TRANSPORT_SERIAL
            and canonical.startswith("0x")
            and canonical[2:]
            and all(character in "0123456789abcdef" for character in canonical[2:])
        ):
            canonical = canonical[2:]
        if not canonical:
            raise ValueError("A Backup Identifier value must not be empty")
        payload = "\0".join((_IDENTITY_DOMAIN, kind.value, canonical)).encode(
            "utf-8", errors="surrogatepass"
        )
        return cls(kind, hashlib.sha256(payload).hexdigest())

    def to_manifest(self) -> dict[str, str]:
        return {"kind": self.kind.value, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class BackupDeviceIdentity:
    """Serial-first Backup Identifier with a best-effort Volume fallback."""

    claims: tuple[BackupIdentityClaim, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError(f"Unsupported Backup Identifier version: {self.version}")
        claims = tuple(
            sorted(
                set(self.claims),
                key=lambda claim: (claim.kind.value, claim.sha256),
            )
        )
        object.__setattr__(self, "claims", claims)

    @property
    def is_stable(self) -> bool:
        """Return whether this identifier has any usable matching evidence."""

        return bool(self.claims)

    @property
    def uses_serial_number(self) -> bool:
        return any(
            claim.kind
            in {
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                BackupIdentityClaimKind.TRANSPORT_SERIAL,
            }
            for claim in self.claims
        )

    @property
    def digest(self) -> str:
        digest = hashlib.sha256()
        digest.update(f"{_IDENTITY_DOMAIN}.set\0".encode())
        claims = _preferred_claims(self.claims)
        for claim in claims:
            digest.update(claim.kind.value.encode())
            digest.update(b"\0")
            digest.update(claim.sha256.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def matches(self, other: BackupDeviceIdentity) -> bool:
        if not self.claims or not other.claims or self.version != other.version:
            return False
        mine = _claims_by_kind(self.claims)
        theirs = _claims_by_kind(other.claims)
        serial_kinds = {
            BackupIdentityClaimKind.PRODUCT_SERIAL,
            BackupIdentityClaimKind.TRANSPORT_SERIAL,
        }
        mine_has_serial = bool(mine.keys() & serial_kinds)
        theirs_has_serial = bool(theirs.keys() & serial_kinds)
        if mine_has_serial and theirs_has_serial:
            return any(
                mine.get(kind, set()) & theirs.get(kind, set()) for kind in serial_kinds
            )
        return bool(
            mine.get(BackupIdentityClaimKind.VOLUME_ID, set())
            & theirs.get(BackupIdentityClaimKind.VOLUME_ID, set())
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "claims": [claim.to_manifest() for claim in self.claims],
        }

    @classmethod
    def from_manifest(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("A Backup Identifier must be an object")
        fields = cast("dict[object, object]", value)
        if set(fields) != {"version", "claims"}:
            raise ValueError("The Backup Identifier has invalid fields")
        version = fields.get("version")
        raw_claims = fields.get("claims")
        if version != 1 or not isinstance(raw_claims, list):
            raise ValueError("The Backup Identifier version or claims are invalid")
        claims: list[BackupIdentityClaim] = []
        for raw_claim in cast("list[object]", raw_claims):
            if not isinstance(raw_claim, dict):
                raise ValueError("A Backup Identifier claim must be an object")
            claim = cast("dict[object, object]", raw_claim)
            if set(claim) != {"kind", "sha256"}:
                raise ValueError("A Backup Identifier claim has invalid fields")
            kind = claim.get("kind")
            digest = claim.get("sha256")
            if not isinstance(kind, str) or not isinstance(digest, str):
                raise ValueError("A Backup Identifier claim is incomplete")
            claims.append(BackupIdentityClaim(BackupIdentityClaimKind(kind), digest))
        return cls(tuple(claims), version=1)


def _claims_by_kind(
    claims: tuple[BackupIdentityClaim, ...],
) -> dict[BackupIdentityClaimKind, set[str]]:
    result: dict[BackupIdentityClaimKind, set[str]] = {}
    for claim in claims:
        result.setdefault(claim.kind, set()).add(claim.sha256)
    return result


def _preferred_claims(
    claims: tuple[BackupIdentityClaim, ...],
) -> tuple[BackupIdentityClaim, ...]:
    """Choose product serial, transport serial, then Volume fallback for keys."""

    for kind in (
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        BackupIdentityClaimKind.TRANSPORT_SERIAL,
        BackupIdentityClaimKind.VOLUME_ID,
    ):
        selected = tuple(claim for claim in claims if claim.kind is kind)
        if selected:
            return selected
    return ()


class SnapshotIdentityState(StrEnum):
    NATIVE = "native"
    LEGACY_ASSERTED = "legacy_asserted"
    LEGACY_UNKNOWN = "legacy_unknown"
    UNSTABLE = "unstable"


class BackupReason(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    PRE_SYNC = "pre-sync"
    PRE_RESTORE_SAFETY = "pre_restore_safety"


class BackupStage(StrEnum):
    SCANNING = "scanning"
    CAPTURING = "capturing"
    VERIFYING = "verifying"
    EXPORTING = "exporting"
    APPLYING = "applying"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True, slots=True)
class BackupProgress:
    stage: BackupStage
    current: int
    total: int
    message: str
    current_file: str = ""
    can_cancel: bool = True
    completed_bytes: int = 0
    total_bytes: int = 0


@dataclass(frozen=True, slots=True)
class BackupDeviceMetadata:
    family: str = ""
    generation: str = ""
    color: str = ""
    display_name: str = ""
    product_image: str = ""

    def to_manifest(self) -> dict[str, str]:
        return {
            "family": self.family,
            "generation": self.generation,
            "color": self.color,
            "display_name": self.display_name,
            "product_image": self.product_image,
        }

    @classmethod
    def from_manifest(cls, value: object) -> BackupDeviceMetadata:
        if not isinstance(value, dict):
            return cls()
        fields = cast("dict[object, object]", value)

        def text(key: str) -> str:
            candidate = fields.get(key, "")
            return candidate if isinstance(candidate, str) else ""

        return cls(
            family=text("family") or text("model_family"),
            generation=text("generation"),
            color=text("color"),
            display_name=text("display_name"),
            product_image=text("product_image"),
        )


@dataclass(frozen=True, slots=True)
class BackupDeviceContext:
    archive_key: ArchiveKey | None
    display_name: str
    identity: BackupDeviceIdentity
    filesystem_type: str
    metadata: BackupDeviceMetadata
    legacy_identity_claims: tuple[LegacyIdentityClaim, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "legacy_identity_claims",
            tuple(
                sorted(
                    set(self.legacy_identity_claims),
                    key=lambda claim: claim.sha256,
                )
            ),
        )

    @property
    def device_id(self) -> str:
        """Compatibility display value; never use this property as authority."""

        if self.archive_key is not None:
            return self.archive_key.value
        if self.identity.is_stable:
            return ArchiveKey.for_identity(self.identity).value
        return ""

    @property
    def has_backup_identifier(self) -> bool:
        return self.identity.is_stable


@dataclass(frozen=True, slots=True)
class LegacyImportIdentityAssignment:
    """A verified Original archive key's native Backup Identifier assignment."""

    legacy_identity_claim: LegacyIdentityClaim
    archive_key: ArchiveKey
    identity: BackupDeviceIdentity

    def __post_init__(self) -> None:
        if not self.identity.is_stable:
            raise ValueError(
                "A Legacy Backup Import assignment needs a Backup Identifier"
            )


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    id: str
    timestamp: str
    device_id: str
    device_name: str
    file_count: int = 0
    total_size: int = 0
    reason: BackupReason = BackupReason.MANUAL
    note: str = ""
    files_added: int = 0
    files_removed: int = 0
    files_changed: int = 0
    metadata: BackupDeviceMetadata = BackupDeviceMetadata()
    has_backup_identifier: bool = False
    is_valid: bool = True
    validation_error: str = ""
    identity_state: SnapshotIdentityState = SnapshotIdentityState.UNSTABLE
    legacy_identity_claim: LegacyIdentityClaim | None = None

    @property
    def display_date(self) -> str:
        try:
            value = datetime.fromisoformat(self.timestamp)
            if value.tzinfo is not None:
                value = value.astimezone()
            return value.strftime("%b %d, %Y · %I:%M %p")
        except ValueError:
            return self.timestamp

    @property
    def requires_restore_confirmation(self) -> bool:
        return self.identity_state in {
            SnapshotIdentityState.LEGACY_ASSERTED,
            SnapshotIdentityState.LEGACY_UNKNOWN,
        }


@dataclass(frozen=True, slots=True)
class BackupDeviceInfo:
    device_id: str
    device_name: str
    snapshot_count: int
    metadata: BackupDeviceMetadata = BackupDeviceMetadata()
    has_backup_identifier: bool = False
    connected: bool = False
    identity_state: SnapshotIdentityState = SnapshotIdentityState.UNSTABLE


@dataclass(frozen=True, slots=True)
class BackupInventory:
    devices: tuple[BackupDeviceInfo, ...]
    connected_device_id: str = ""
    pending_recoveries: tuple[RestoreRecoveryRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class BackupCatalog:
    device: BackupDeviceInfo
    snapshots: tuple[SnapshotInfo, ...]
    stored_size: int


@dataclass(frozen=True, slots=True)
class BackupRestoreResult:
    snapshot_id: str
    safety_snapshot_id: str
    flush: FlushResult


@dataclass(frozen=True, slots=True)
class BackupExportResult:
    destination: Path
    file_count: int
    total_size: int


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.sha256) is None or self.size < 0:
            raise ValueError(
                "Content Identity requires a SHA-256 and non-negative size"
            )


@dataclass(frozen=True, slots=True)
class VerifiedSnapshotFile:
    path_parts: tuple[str, ...]
    source: HostPath
    content: ContentIdentity
    modified_ns: int | None


@dataclass(frozen=True, slots=True)
class VerifiedSnapshot:
    archive_key: ArchiveKey
    snapshot_id: str
    identity_state: SnapshotIdentityState
    identity: BackupDeviceIdentity
    legacy_identity_claim: LegacyIdentityClaim | None
    files: tuple[VerifiedSnapshotFile, ...]
    recovery_material_identity: str


@dataclass(frozen=True, slots=True)
class LegacyImportFailure:
    legacy_device_id: str
    snapshot_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    imported: tuple[SnapshotInfo, ...]
    already_imported: tuple[SnapshotInfo, ...]
    failures: tuple[LegacyImportFailure, ...]


class RestoreRecoveryPhase(StrEnum):
    SAFETY_PINNED = "safety_pinned"
    DEVICE_TRANSACTION_PUBLISHED = "device_transaction_published"
    APPLYING = "applying"
    VERIFYING = "verifying"
    RECOVERY_REQUIRED = "recovery_required"


class RestoreRecoveryOutcome(StrEnum):
    UNRESOLVED = "unresolved"
    VERIFIED_COMPLETION = "verified_completion"
    VERIFIED_RECOVERY = "verified_recovery"


@dataclass(frozen=True, slots=True)
class RestoreRecoveryRecord:
    id: str
    target_archive_key: ArchiveKey
    safety_archive_key: ArchiveKey
    current_identity: BackupDeviceIdentity
    target_snapshot_id: str
    safety_snapshot_id: str
    operation_journal: DevicePath
    recovery_material_identity: str
    phase: RestoreRecoveryPhase
    outcome: RestoreRecoveryOutcome
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if len(self.id) != 32 or any(
            character not in "0123456789abcdef" for character in self.id
        ):
            raise ValueError("A Restore Recovery record requires a lowercase UUID")
        if not self.current_identity.is_stable:
            raise ValueError("Restore Recovery requires a Backup Identifier")
        journal = self.operation_journal.parts
        if (
            len(journal) != 3
            or journal[0] != ".iopenpod-recovery"
            or journal[2] != "transaction.json"
            or len(journal[1]) != 32
            or any(character not in "0123456789abcdef" for character in journal[1])
        ):
            raise ValueError("Restore Recovery requires an exact transaction journal")
        if _SHA256.fullmatch(self.recovery_material_identity) is None:
            raise ValueError("Restore Recovery requires a SHA-256 material identity")

    @property
    def archive_key(self) -> ArchiveKey:
        """Compatibility projection for the selected target archive."""

        return self.target_archive_key


__all__ = [
    "ArchiveKey",
    "BackupCatalog",
    "BackupDeviceContext",
    "BackupDeviceIdentity",
    "BackupDeviceInfo",
    "BackupDeviceMetadata",
    "BackupExportResult",
    "BackupIdentityClaim",
    "BackupIdentityClaimKind",
    "BackupInventory",
    "BackupProgress",
    "BackupReason",
    "BackupRestoreResult",
    "BackupStage",
    "ContentIdentity",
    "LegacyIdentityClaim",
    "LegacyImportFailure",
    "LegacyImportIdentityAssignment",
    "LegacyImportResult",
    "RestoreRecoveryOutcome",
    "RestoreRecoveryPhase",
    "RestoreRecoveryRecord",
    "SnapshotIdentityState",
    "SnapshotInfo",
    "VerifiedSnapshot",
    "VerifiedSnapshotFile",
    "sanitize_backup_device_id",
]
