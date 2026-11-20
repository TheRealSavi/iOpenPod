"""Immutable inputs and outputs for Firmware Mod composition."""

import hashlib
import re
from dataclasses import dataclass


def validate_id(value: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", value) or len(value) > 96:
        raise ValueError("Invalid Firmware Mod or target identifier")


def validate_text(value: str, *, maximum: int = 160) -> None:
    if (
        not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Invalid firmware metadata text")


def validate_digest(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256 fingerprint")


@dataclass(frozen=True, slots=True)
class AppleFirmware:
    """One exact image/container; a release number alone never identifies it."""

    target_id: str
    version: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        validate_id(self.target_id)
        validate_text(self.version, maximum=32)
        validate_digest(self.sha256)
        if not 0 < self.size_bytes <= 128 * 1024 * 1024:
            raise ValueError("Invalid Apple Firmware size")


@dataclass(frozen=True, slots=True)
class FirmwarePatch:
    """A fixed-size replacement checked against the pristine Apple image."""

    offset: int
    expected: bytes
    replacement: bytes

    def __post_init__(self) -> None:
        if (
            self.offset < 0
            or not self.expected
            or len(self.expected) != len(self.replacement)
        ):
            raise ValueError(
                "A Firmware Patch requires an offset and equal nonempty sizes"
            )


@dataclass(frozen=True, slots=True)
class FirmwareMod:
    """A pinned mod release and its composition requirements.

    None means no qualified recipe is available. An empty recipe is a valid
    metadata-only mod. Hook claims are exclusive; shared hooks must belong to
    a common dependency rather than relying on overwrite order.
    """

    id: str
    version: str
    name: str
    description: str
    targets: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ()
    patches: tuple[FirmwarePatch, ...] | None = None

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_text(self.version, maximum=32)
        validate_text(self.name)
        validate_text(self.description, maximum=512)
        for values in (self.targets, self.dependencies, self.conflicts, self.hooks):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate Firmware Mod metadata entries")
            for value in values:
                validate_id(value)
        if self.id in self.dependencies or self.id in self.conflicts:
            raise ValueError("A Firmware Mod cannot depend on or conflict with itself")


@dataclass(frozen=True, slots=True)
class FirmwareBuildPlan:
    apple: AppleFirmware
    platform_version: str
    requested: tuple[str, ...]
    mods: tuple[FirmwareMod, ...]
    build_id: str

    @property
    def missing_recipes(self) -> tuple[str, ...]:
        return tuple(mod.id for mod in self.mods if mod.patches is None)


@dataclass(frozen=True, slots=True)
class FirmwareBuild:
    """Composed image bytes and matching registry, not an installation receipt.

    Boot packaging, native registry-menu integration, device personalization and
    hardware validation must be supplied by a target's complete build adapter.
    """

    plan: FirmwareBuildPlan
    image: bytes
    registry: bytes

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image).hexdigest()
