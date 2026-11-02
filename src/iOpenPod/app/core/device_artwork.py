"""Resolve packaged device artwork consistently for GUI and Volume icons."""

from pathlib import Path

_IMAGE_DIRECTORY = Path(__file__).parents[2] / "assets" / "ipod_images"
_FALLBACK_IMAGE = "iPodGeneric.png"


def device_artwork_path(image_name: str, *, itunes_107: bool = False) -> Path:
    """Prefer the selected style, then the standard model, then generic artwork."""
    candidate = Path(image_name)
    if (
        candidate.name != image_name
        or candidate.suffix.casefold() != ".png"
        or "\\" in image_name
        or "\x00" in image_name
    ):
        image_name = _FALLBACK_IMAGE
    directories = (
        (_IMAGE_DIRECTORY / "107", _IMAGE_DIRECTORY)
        if itunes_107
        else (_IMAGE_DIRECTORY,)
    )
    for name in (image_name, _FALLBACK_IMAGE):
        for directory in directories:
            path = directory / name
            if path.is_file():
                return path
    return _IMAGE_DIRECTORY / _FALLBACK_IMAGE
