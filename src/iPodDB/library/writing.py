"""Immutable inputs and results for pure, source-bound Library preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iPodDB.library.artwork import ArtworkPixels, CoverFormat
    from iPodDB.library.models import LibrarySnapshot
    from iPodDB.library.photos import Photo, PhotoThumbnailFormat
    from iPodDB.library.signing import Hash72Material
    from iPodDB.library.sqlite import SQLiteDatabaseSet


class IssueSeverity(StrEnum):
    INFO = "info"
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class WriteIssue:
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR
    phase: str = "validation"
    subject: str = "library"
    record_id: int | None = None
    field: str = ""
    detail: str = ""
    chunk_path: tuple[int, ...] = ()
    offset: int | None = None
    artifact: str = ""


class WriteChecksum(StrEnum):
    NONE = "none"
    HASH58 = "hash58"
    HASH72 = "hash72"
    HASHAB = "hashab"


class WritePhase(StrEnum):
    """Pure preparation checkpoints. Entry does not imply successful completion."""

    VALIDATION = "validation"
    RESOURCES = "resources"
    RECONCILIATION = "reconciliation"
    ARTWORK = "artwork"
    SERIALIZATION = "serialization"
    SIGNING = "signing"
    VERIFICATION = "verification"


@dataclass(frozen=True, slots=True)
class WriteTarget:
    """Capabilities for these artifacts; supplied by the application, never inferred."""

    checksum: WriteChecksum = WriteChecksum.NONE
    firewire_guid: bytes = b""
    max_database_bytes: int = 256 * 1024 * 1024
    compressed_database: bool = False
    sqlite_database: bool = False
    sqlite_checksum: WriteChecksum = WriteChecksum.NONE
    hash72_material: Hash72Material | None = None
    sqlite_postprocess_commands: tuple[str, ...] = ()
    cover_formats: tuple[CoverFormat, ...] = ()
    max_artwork_file_bytes: int = 256 * 1024 * 1024
    # The meaning of this root field is not established across all models.
    # The application supplies the identified Device Profile's creation policy.
    # Retained ArtworkDB root values are never replaced with this seed.
    artwork_root_value: int | None = None
    artwork_checksum: WriteChecksum = WriteChecksum.NONE
    supports_sparse_artwork: bool = True
    photo_formats: tuple[PhotoThumbnailFormat, ...] = ()
    photos_root_value: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryDraft:
    """Complete desired state; omitted source records require explicit deletion intent."""

    source_revision: str
    snapshot: LibrarySnapshot
    delete_omissions: bool = field(default=False, kw_only=True)
    # Existing Track identities whose file content is explicitly being replaced,
    # even if every projected value is unchanged. Resources alone are not intent.
    replace_media: tuple[int, ...] = field(default=(), kw_only=True)
    replace_photos: tuple[int, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class LibraryChange:
    subject: str
    record_id: int | None
    action: str
    name: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteEffect:
    """A generated consequence, tied to requested changes by their plan indexes."""

    code: str
    subject: str
    record_id: int | None
    reason: str
    causes: tuple[int, ...]
    fields: tuple[str, ...] = ()
    dataset: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryResolution:
    """Observable resolved intent, never a second editable submission format.

    Native allocation and resource-dependent values are described by effects;
    their exact output identities and bytes arrive in the Prepared Library.
    """

    snapshot: LibrarySnapshot
    generated_changes: tuple[LibraryChange, ...]
    effects: tuple[WriteEffect, ...]
    preservation: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FileDependency:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceFile:
    dependency: FileDependency
    data: bytes


class MediaContent(StrEnum):
    """Caller-observed content, independent of a Track's Library classification."""

    AUDIO = "audio"
    VIDEO = "video"
    AUDIO_VIDEO = "audio_video"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class PreparedMedia:
    """Validated media facts from a caller-owned import/inspection workflow.

    The desired Track supplies semantic duration, size, bitrate, sample rate and
    gapless facts. This record supplies native codec facts and a captured file
    identity; neither implies that a file has been copied to the iPod.
    When PreparedLyrics is also supplied, its final file size supersedes the
    draft's pre-tagging size and both resources identify the same final bytes.
    Content describes the timed streams (excluding embedded cover images), or a
    document. The default retains the existing audio-input contract.
    """

    track_id: int
    file: FileDependency
    filetype: int
    mp3_flag: int
    audio_format_flag: int
    mpeg_audio_type: int
    gapless_audio_payload_size: int
    content: MediaContent = field(default=MediaContent.AUDIO, kw_only=True)


@dataclass(frozen=True, slots=True)
class ArtworkAsset:
    artwork_id: int
    pixels: ArtworkPixels


@dataclass(frozen=True, slots=True)
class PreparedPhoto:
    """A complete Photo and verified, freshly named original/thumbnail bytes."""

    photo: Photo
    files: tuple[SourceFile, ...]


@dataclass(frozen=True, slots=True)
class PreparedLyrics:
    """Caller-verified embedded lyrics and the resulting media file identity.

    Tagging changes the file size, but retains the encoded media and codec facts.
    The application owns reading, transforming, verifying and publishing the file.
    """

    track_id: int
    lyrics: str
    file: FileDependency


@dataclass(frozen=True, slots=True)
class WriteResources:
    media: tuple[PreparedMedia, ...] = ()
    artwork: tuple[ArtworkAsset, ...] = ()
    files: tuple[SourceFile, ...] = ()
    file_inventory: tuple[FileDependency, ...] | None = None
    # False means no unhandled positional sidecars remain: the caller captured
    # their absence or bound their preservation/remapping to the same transaction.
    # None means the caller has not checked.
    pending_playback_sidecars: bool | None = None
    lyrics: tuple[PreparedLyrics, ...] = field(default=(), kw_only=True)
    photos: tuple[PreparedPhoto, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class LibraryWritePlan:
    draft: LibraryDraft
    target: WriteTarget
    changes: tuple[LibraryChange, ...]
    issues: tuple[WriteIssue, ...]
    required_media: tuple[int, ...] = ()
    required_artwork: tuple[int, ...] = ()
    requires_artwork_inventory: bool = False
    requires_sidecar_inventory: bool = False
    resolution: LibraryResolution | None = field(default=None, kw_only=True)
    required_lyrics: tuple[int, ...] = field(default=(), kw_only=True)
    required_photos: tuple[int, ...] = field(default=(), kw_only=True)

    @property
    def blocked(self) -> bool:
        return any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def changes_photos(self) -> bool:
        return any(
            change.subject in {"photo", "photo_album", "photos"}
            for change in self.changes
        )

    @property
    def changes_itunes(self) -> bool:
        return any(
            change.subject not in {"photo", "photo_album", "photos"}
            for change in self.changes
        )


@dataclass(frozen=True, slots=True)
class PreparedFile:
    relative_path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class RetainedArtworkFile:
    """Retained source ranges, including photos. A filename is binary metadata,
    not authorization to access a host path; the application validates it first.
    """

    file_name: str
    ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class IdentityMapping:
    subject: str
    draft_id: int
    output_id: int
    # Older iPods require one image record per Track even for shared pixels.
    track_id: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedLibrary:
    itunes: bytes
    artwork: bytes | None
    artwork_files: tuple[PreparedFile, ...]
    retained_files: tuple[FileDependency, ...]
    snapshot: LibrarySnapshot
    identities: tuple[IdentityMapping, ...]
    source_revision: str
    retained_artwork: tuple[RetainedArtworkFile, ...] = ()
    photos: bytes | None = field(default=None, kw_only=True)
    sqlite: SQLiteDatabaseSet | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class WriteMeasurement:
    """Elapsed worker time between stage entries, including a terminal stage.

    A duration records work performed, not successful completion of that stage.
    """

    phase: WritePhase
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class LibraryWriteResult:
    issues: tuple[WriteIssue, ...]
    prepared: PreparedLibrary | None = None
    measurements: tuple[WriteMeasurement, ...] = field(
        default=(), kw_only=True, compare=False
    )
