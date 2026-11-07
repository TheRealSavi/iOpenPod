"""Validated resource paths and ArtworkDB filename resolution."""

from pathlib import PurePosixPath


def validated_path(value: str) -> str:
    value.encode("utf-8")
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("A resource requires a validated device-relative path.")
    parts = value.split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError(
            "A resource path cannot escape the device or contain empty components."
        )
    return value


def artwork_path(name: str) -> str:
    """Resolve a complete filename token without inferring it from a format ID.

    Leading-colon tokens are relative to the native Artwork base. Accepting a
    qualified iPod_Control/Artwork spelling, with or without its leading colon,
    is retained Host compatibility. The namespace and .ithmb suffix restriction
    are Host eligibility policy, not additional native filename validation.
    """
    value = name[1:] if name.startswith(":") else name
    value = value.replace(":", "/")
    if not value.startswith("iPod_Control/Artwork/") and (
        name.startswith(":") or "/" not in value
    ):
        value = "iPod_Control/Artwork/" + value
    path = validated_path(value)
    if not path.startswith("iPod_Control/Artwork/") or not path.casefold().endswith(
        ".ithmb"
    ):
        raise ValueError(
            "The retained artwork filename does not identify a supported iTHMB path."
        )
    return path
