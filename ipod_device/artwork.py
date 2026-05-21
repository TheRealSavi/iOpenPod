"""Artwork lookups backed by the canonical format registry."""

from .artwork_presets import (
    ARTWORK_FORMATS_BY_ID,
    ArtworkFormat,
)
from .capabilities import capabilities_for_family_gen, cover_art_formats_for_family_gen

ITHMB_FORMAT_MAP = ARTWORK_FORMATS_BY_ID
"""Primary global lookup of ithmb correlation ID -> ``ArtworkFormat``.

Most artwork IDs are globally meaningful. Device-aware code can layer a small
override set on top of this table for the few known conflicts, such as Nano
7G's reinterpretation of ``1013``/``1015``/``1016``.
"""

ITHMB_SIZE_MAP: dict[int, ArtworkFormat] = {}
"""Fallback lookup: byte size -> ``ArtworkFormat``."""
for _af in ITHMB_FORMAT_MAP.values():
    _byte_size = _af.row_bytes * _af.height
    if _byte_size > 0 and _byte_size not in ITHMB_SIZE_MAP:
        ITHMB_SIZE_MAP[_byte_size] = _af


def ithmb_formats_for_device(
    family: str,
    generation: str,
    *,
    capacity: str | None = None,
    model_number: str | None = None,
) -> dict[int, tuple[int, int]]:
    """Return ``{correlation_id: (width, height)}`` for a device's cover art."""
    definitions = cover_art_format_definitions_for_device(
        family,
        generation,
        capacity=capacity,
        model_number=model_number,
    )
    return {fid: (af.width, af.height) for fid, af in definitions.items()}


def _format_dict(formats: tuple[ArtworkFormat, ...]) -> dict[int, ArtworkFormat]:
    return {af.format_id: af for af in formats}


def cover_art_format_definitions_for_device(
    family: str,
    generation: str,
    *,
    capacity: str | None = None,
    model_number: str | None = None,
) -> dict[int, ArtworkFormat]:
    """Return the device's required cover-art definitions.

    The normal case is the global registry. Devices with known conflicting IDs
    expose a small explicit override set through their capability profile.
    """

    caps = capabilities_for_family_gen(
        family,
        generation or "",
        capacity=capacity,
        model_number=model_number,
    )
    if caps is None:
        return _format_dict(
            cover_art_formats_for_family_gen(
                family,
                generation,
                capacity=capacity,
                model_number=model_number,
            )
        )
    if not caps.supports_artwork:
        return {}
    return _format_dict(caps.cover_art_formats)


def _resolve_observed_format(
    format_id: int,
    width: int,
    height: int,
    preferred_defs: dict[int, ArtworkFormat],
) -> ArtworkFormat:
    """Resolve an observed ``id -> dimensions`` using overrides first, then global defaults.

    If neither source matches the observed dimensions, fall back to a generic
    RGB565 cover-art definition for that observed shape.
    """
    for candidate in (
        preferred_defs.get(format_id),
        ARTWORK_FORMATS_BY_ID.get(format_id),
    ):
        if candidate is None:
            continue
        if int(candidate.width) == int(width) and int(candidate.height) == int(height):
            return candidate

    return ArtworkFormat(
        int(format_id),
        int(width),
        int(height),
        int(width) * 2,
        "RGB565_LE",
        "cover",
        f"Device artwork format {format_id}",
    )


def resolve_cover_art_format_definitions(
    family: str = "",
    generation: str = "",
    *,
    capacity: str | None = None,
    model_number: str | None = None,
    observed_formats: dict[int, tuple[int, int]] | None = None,
) -> dict[int, ArtworkFormat]:
    """Resolve the authoritative cover-art definitions for a device.

    ``observed_formats`` usually comes from SysInfoExtended or an existing
    ArtworkDB. When present, its ID list is authoritative, but each entry still
    resolves through device overrides first and the global registry second. Only
    unmatched dimensions fall back to a generic inferred definition.
    """
    preferred_defs = cover_art_format_definitions_for_device(
        family,
        generation,
        capacity=capacity,
        model_number=model_number,
    )

    if observed_formats:
        resolved: dict[int, ArtworkFormat] = {}
        for fid, dims in observed_formats.items():
            width, height = dims
            resolved[int(fid)] = _resolve_observed_format(
                int(fid),
                int(width),
                int(height),
                preferred_defs,
            )
        return resolved

    return preferred_defs


def resolve_cover_art_format_definitions_for_device(device) -> dict[int, ArtworkFormat]:
    """Resolve cover-art definitions from a ``DeviceInfo``-like object."""
    if device is None:
        return {}

    return resolve_cover_art_format_definitions(
        getattr(device, "model_family", "") or "",
        getattr(device, "generation", "") or "",
        capacity=getattr(device, "capacity", ""),
        model_number=getattr(device, "model_number", ""),
        observed_formats=getattr(device, "artwork_formats", None) or None,
    )


def photo_formats_for_device(
    family: str,
    generation: str,
    *,
    capacity: str | None = None,
    model_number: str | None = None,
) -> dict[int, ArtworkFormat]:
    """Return device-specific photo ithmb formats.

    This is separate from cover-art formats because iPods keep slide-show/photo
    caches in the ``Photos`` hierarchy rather than ``ArtworkDB``. The per-device
    formats are sourced from ``DeviceCapabilities.photo_formats``.
    """

    caps = capabilities_for_family_gen(
        family,
        generation or "",
        capacity=capacity,
        model_number=model_number,
    )
    formats = caps.photo_formats if caps is not None else ()
    if not formats:
        return {}
    return {af.format_id: af for af in formats}
