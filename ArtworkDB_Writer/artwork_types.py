"""Typed internal artwork payload/ref models used by the ArtworkDB writer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IthmbLocation:
    """Filename and byte offset for one frame inside an ithmb file."""

    filename: str
    offset: int


@dataclass(frozen=True)
class ExistingFormatRef:
    """Location and visible geometry for one on-device ArtworkDB format ref."""

    path: str
    ithmb_offset: int
    size: int
    width: int
    height: int
    hpad: int = 0
    vpad: int = 0
    ithmb_filename: str = ""

    @property
    def stride_pixels(self) -> int:
        return max(1, self.width + self.hpad)

    @property
    def stored_height(self) -> int:
        return max(1, self.height + self.vpad)


@dataclass(frozen=True)
class EncodedFormatPayload:
    """Writable ithmb payload for a known format."""

    data: bytes
    width: int
    height: int
    size: int
    stride_pixels: int
    hpad: int = 0
    vpad: int = 0
    pixel_format: str | None = None

    @classmethod
    def from_existing_ref(cls, ref: ExistingFormatRef, data: bytes) -> EncodedFormatPayload:
        return cls(
            data=data,
            width=ref.width,
            height=ref.height,
            size=ref.size,
            stride_pixels=ref.stride_pixels,
            hpad=ref.hpad,
            vpad=ref.vpad,
        )


@dataclass(frozen=True)
class PassthroughFormatRef:
    """Existing format ref we can preserve in ArtworkDB without rewriting."""

    path: str
    ithmb_offset: int
    size: int
    width: int
    height: int
    hpad: int = 0
    vpad: int = 0
    ithmb_filename: str = ""

    @classmethod
    def from_existing_ref(cls, ref: ExistingFormatRef) -> PassthroughFormatRef:
        return cls(
            path=ref.path,
            ithmb_offset=ref.ithmb_offset,
            size=ref.size,
            width=ref.width,
            height=ref.height,
            hpad=ref.hpad,
            vpad=ref.vpad,
            ithmb_filename=ref.ithmb_filename,
        )

    @property
    def stride_pixels(self) -> int:
        return max(1, self.width + self.hpad)


ArtworkFormatPayload = EncodedFormatPayload | PassthroughFormatRef


@dataclass
class ArtworkPayload:
    """All format payloads for one unique artwork asset."""

    formats: dict[int, ArtworkFormatPayload] = field(default_factory=dict)
    src_img_size: int = 0


@dataclass
class ArtworkEntry:
    """Represents a unique album art image for the ArtworkDB."""

    img_id: int
    db_track_id: int
    art_hash: str | None
    src_img_size: int
    formats: dict[int, ArtworkFormatPayload] = field(default_factory=dict)
    db_track_ids: list[int] = field(default_factory=list)
