"""Normalize decoded images to the application's RGB pixel representation."""

from PIL import Image


def rgb_image(image: Image.Image) -> Image.Image:
    """Return owned RGB pixels, expanding palette alpha before dropping it."""
    if image.mode == "P" and isinstance(image.info.get("transparency"), bytes):
        with image.convert("RGBA") as rgba:
            return rgba.convert("RGB")
    return image.convert("RGB")
