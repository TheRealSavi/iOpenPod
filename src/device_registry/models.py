"""Immutable public data structures for iPod identification and capabilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum


class EvidenceAuthority(IntEnum):
    """Relative authority of evidence supplied to the Device Registry."""

    DERIVED = 10
    DEVICE_METADATA = 20
    CURRENT_HARDWARE = 30


@dataclass(frozen=True, slots=True)
class DeviceIdentifier[IdentifierValue]:
    """One typed identifier plus where and when it was observed."""

    value: IdentifierValue
    source: str
    authority: EvidenceAuthority

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("A Device Identifier source must not be empty")


@dataclass(frozen=True, slots=True)
class UsbIdentifier:
    """A paired USB vendor and product identifier."""

    vendor_id: int
    product_id: int

    def __post_init__(self) -> None:
        for name, value in (
            ("vendor_id", self.vendor_id),
            ("product_id", self.product_id),
        ):
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"{name} must be a 16-bit unsigned integer")


@dataclass(frozen=True, slots=True)
class DeviceEvidence:
    """Identity observations for one currently considered Physical Device."""

    model_numbers: tuple[DeviceIdentifier[str], ...] = ()
    product_serials: tuple[DeviceIdentifier[str], ...] = ()
    transport_serials: tuple[DeviceIdentifier[str], ...] = ()
    usb_identifiers: tuple[DeviceIdentifier[UsbIdentifier], ...] = ()
    board_hardware_names: tuple[DeviceIdentifier[str], ...] = ()
    firmware_versions: tuple[DeviceIdentifier[str], ...] = ()
    family_ids: tuple[DeviceIdentifier[int], ...] = ()
    updater_family_ids: tuple[DeviceIdentifier[int], ...] = ()

    def merged_with(self, other: DeviceEvidence) -> DeviceEvidence:
        """Combine observations without losing either source's provenance."""

        return DeviceEvidence(
            model_numbers=self.model_numbers + other.model_numbers,
            product_serials=self.product_serials + other.product_serials,
            transport_serials=self.transport_serials + other.transport_serials,
            usb_identifiers=self.usb_identifiers + other.usb_identifiers,
            board_hardware_names=(
                self.board_hardware_names + other.board_hardware_names
            ),
            firmware_versions=self.firmware_versions + other.firmware_versions,
            family_ids=self.family_ids + other.family_ids,
            updater_family_ids=(self.updater_family_ids + other.updater_family_ids),
        )


class StorageTechnology(StrEnum):
    HARD_DISK = "hard_disk"
    FLASH = "flash"


class DatabaseChecksum(StrEnum):
    NONE = "none"
    HASH58 = "hash58"
    HASH72 = "hash72"
    HASHAB = "hashab"


class ArtworkPixelFormat(StrEnum):
    """Pixel encoding and, when necessary, its iTHMB storage order."""

    RGB565_LE = "RGB565_LE"
    RGB565_BE = "RGB565_BE"
    RGB565_BE_90 = "RGB565_BE_90"
    RGB555_LE = "RGB555_LE"
    RGB555_BE = "RGB555_BE"
    REC_RGB555_LE = "REC_RGB555_LE"
    UYVY = "UYVY"
    UYVY_FIELDS = "UYVY_FIELDS"
    I420_LE = "I420_LE"
    JPEG = "JPEG"


class ArtworkUsage(StrEnum):
    """Broad purpose of an artwork format on an iPod."""

    COVER = "cover"
    PHOTO = "photo"
    TV_OUTPUT = "tv_output"


@dataclass(frozen=True, slots=True)
class ArtworkFormat:
    """One device-specific iTHMB format definition."""

    format_id: int
    width: int
    height: int
    row_bytes: int
    pixel_format: ArtworkPixelFormat
    usage: ArtworkUsage

    def __post_init__(self) -> None:
        if self.format_id <= 0:
            raise ValueError("Artwork format ID must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Artwork format dimensions must be positive")
        if self.row_bytes < 0:
            raise ValueError("Artwork row size must not be negative")


@dataclass(frozen=True, slots=True)
class DisplayCapabilities:
    width: int
    height: int
    color: bool

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Display dimensions must be positive")


@dataclass(frozen=True, slots=True)
class AudioCapabilities:
    supports_podcasts: bool
    supports_gapless_playback: bool
    supports_alac: bool
    max_sample_rate_hz: int = 48_000
    max_channels: int = 2
    max_lossless_bits: int = 16
    max_aac_bitrate_kbps: int = 320

    def __post_init__(self) -> None:
        if self.max_sample_rate_hz <= 0 or self.max_channels not in (1, 2):
            raise ValueError(
                "Audio capabilities require positive rate and mono/stereo output"
            )
        if self.max_lossless_bits != 16 or not 0 < self.max_aac_bitrate_kbps <= 320:
            raise ValueError("Unsupported native audio encoding limits")


@dataclass(frozen=True, slots=True)
class ArtworkCapabilities:
    supports_cover_art: bool
    supports_photos: bool
    supports_chapter_images: bool
    supports_sparse_artwork: bool
    cover_formats: tuple[ArtworkFormat, ...] = ()
    photo_formats: tuple[ArtworkFormat, ...] = ()
    # Creation policy only; a retained ArtworkDB keeps its own root field.
    artwork_root_value: int | None = None
    # Creation policy only; retained Photo Albums keep their own MHBA type.
    photo_album_creation_type: int | None = None
    photos_root_value: int | None = None

    def __post_init__(self) -> None:
        if self.photos_root_value is not None and (
            not self.supports_photos or not 0 <= self.photos_root_value <= 0xFFFFFFFF
        ):
            raise ValueError(
                "PhotosDB creation requires Photo support and a u32 root value"
            )
        if self.artwork_root_value is not None and (
            not self.supports_cover_art
            or not 0 <= self.artwork_root_value <= 0xFFFFFFFF
        ):
            raise ValueError(
                "ArtworkDB creation requires cover support and a u32 root value"
            )
        if self.photo_album_creation_type is not None and (
            not self.supports_photos
            or not 0 < self.photo_album_creation_type <= 0xFF
            or self.photo_album_creation_type == 1
        ):
            raise ValueError(
                "Photo Album creation requires Photo support and a non-master u8 type"
            )
        if bool(self.cover_formats) != self.supports_cover_art:
            raise ValueError(
                "Cover-art support and cover format definitions must agree"
            )
        if bool(self.photo_formats) != self.supports_photos:
            raise ValueError("Photo support and photo format definitions must agree")
        if self.supports_photos != (self.photo_album_creation_type is not None):
            raise ValueError("Photo support and Photo Album creation policy must agree")
        if any(
            artwork_format.usage is not ArtworkUsage.COVER
            for artwork_format in self.cover_formats
        ):
            raise ValueError("Cover formats must use the cover artwork role")
        if any(
            artwork_format.usage is ArtworkUsage.COVER
            for artwork_format in self.photo_formats
        ):
            raise ValueError("Photo formats cannot use the cover artwork role")

    def cover_format(self, format_id: int) -> ArtworkFormat | None:
        """Return this Device Profile's definition for one cover format ID."""

        return next(
            (
                artwork_format
                for artwork_format in self.cover_formats
                if artwork_format.format_id == format_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class VideoCapabilities:
    supported: bool
    max_width: int = 0
    max_height: int = 0
    max_bitrate_kbps: int = 0
    h264_level: str = ""
    supports_tx3g_subtitles: bool = False
    supports_cea608_captions: bool = False
    max_fps: int = 30
    h264_profiles: tuple[str, ...] = ("Baseline", "Constrained Baseline")
    max_audio_bitrate_kbps: int = 160

    def __post_init__(self) -> None:
        dimensions = (self.max_width, self.max_height)
        if any(value < 0 for value in dimensions):
            raise ValueError("Video dimensions must not be negative")
        if self.max_bitrate_kbps < 0:
            raise ValueError("Video bitrate must not be negative")
        if self.max_fps <= 0 or self.max_audio_bitrate_kbps <= 0:
            raise ValueError("Video frame rate and audio bitrate must be positive")
        if self.supported and 0 in dimensions:
            raise ValueError("A video-capable profile needs positive dimensions")
        if not self.supported and any((*dimensions, self.max_bitrate_kbps)):
            raise ValueError("A non-video profile cannot declare video limits")


@dataclass(frozen=True, slots=True)
class DatabaseCapabilities:
    checksum: DatabaseChecksum
    binary_version: int
    music_directory_count: int
    max_database_bytes: int
    supports_compressed_database: bool = False
    uses_sqlite_database: bool = False
    sqlite_checksum: DatabaseChecksum = DatabaseChecksum.NONE
    requires_sqlite_postprocessing: bool = False

    def __post_init__(self) -> None:
        if self.binary_version <= 0:
            raise ValueError("Database version must be positive")
        if self.music_directory_count <= 0:
            raise ValueError("Music directory count must be positive")
        if self.max_database_bytes <= 0:
            raise ValueError("Maximum database size must be positive")
        if (
            not self.uses_sqlite_database
            and self.sqlite_checksum is not DatabaseChecksum.NONE
        ):
            raise ValueError("A SQLite checksum requires SQLite database support")
        if self.requires_sqlite_postprocessing and not self.uses_sqlite_database:
            raise ValueError("SQLite postprocessing requires SQLite database support")


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    display: DisplayCapabilities
    audio: AudioCapabilities
    artwork: ArtworkCapabilities
    video: VideoCapabilities
    database: DatabaseCapabilities


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Catalog description of one marketed iPod variant."""

    model_number: str
    family: str
    generation: str
    advertised_capacity: str
    finish: str
    product_image: str
    storage_technology: StorageTechnology
    capabilities: DeviceCapabilities

    def __post_init__(self) -> None:
        if not self.product_image.endswith(".png"):
            raise ValueError("A Device Profile product image must be a PNG asset name")
        if "/" in self.product_image or "\\" in self.product_image:
            raise ValueError("A Device Profile product image must not contain a path")

    @property
    def display_name(self) -> str:
        return f"{self.family} {self.generation}"

    def with_capabilities(self, capabilities: DeviceCapabilities) -> DeviceProfile:
        """Return a refined profile without mutating the catalog baseline."""

        return replace(self, capabilities=capabilities)


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    family: str
    generation: str


class ConnectionMode(StrEnum):
    NORMAL = "normal"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SerialSuffixDefinition:
    suffix: str
    model_number: str


@dataclass(frozen=True, slots=True)
class UsbProductDefinition:
    identifier: UsbIdentifier
    mode: ConnectionMode
    candidate_identities: tuple[ModelIdentity, ...]


@dataclass(frozen=True, slots=True)
class RegistryCatalog:
    profiles: tuple[DeviceProfile, ...]
    serial_suffixes: tuple[SerialSuffixDefinition, ...]
    usb_products: tuple[UsbProductDefinition, ...]


class IdentifierKind(StrEnum):
    MODEL_NUMBER = "model_number"
    PRODUCT_SERIAL = "product_serial"
    TRANSPORT_SERIAL = "transport_serial"
    USB = "usb"


@dataclass(frozen=True, slots=True)
class IdentifierSummary:
    kind: IdentifierKind
    value: str
    source: str
    authority: EvidenceAuthority


class IdentificationIssueCode(StrEnum):
    EXACT_IDENTIFIERS_DISAGREE = "exact_identifiers_disagree"
    LOWER_AUTHORITY_IDENTIFIER_DISAGREES = "lower_authority_identifier_disagrees"
    USB_IDENTITY_DISAGREES = "usb_identity_disagrees"
    USB_IDENTIFIERS_DISAGREE = "usb_identifiers_disagree"


@dataclass(frozen=True, slots=True)
class IdentificationIssue:
    code: IdentificationIssueCode
    identifiers: tuple[IdentifierSummary, ...]


class IdentificationStatus(StrEnum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    RECOVERY_MODE = "recovery_mode"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IdentificationResult:
    """Complete, non-authorizing answer returned by Device Registry."""

    status: IdentificationStatus
    connection_mode: ConnectionMode
    profile: DeviceProfile | None = None
    candidates: tuple[DeviceProfile, ...] = ()
    issues: tuple[IdentificationIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.status is IdentificationStatus.EXACT and self.profile is None:
            raise ValueError("An exact result requires a Device Profile")
        if self.status is not IdentificationStatus.EXACT and self.profile is not None:
            raise ValueError("Only an exact result may expose a Device Profile")
