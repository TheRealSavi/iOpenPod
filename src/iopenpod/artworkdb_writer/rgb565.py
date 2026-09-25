"""
RGB565 image conversion for iPod ithmb files.

Converts PIL/Pillow images to RGB565 little-endian pixel data,
the format used by iPod Classic/Nano album art.

RGB565 encoding: 5 bits red | 6 bits green | 5 bits blue (16 bits per pixel)
"""

import io

import numpy as np
from PIL import Image

from iopenpod.artworkdb_shared.mhlf import extract_format_ids
from iopenpod.device import (
    ITHMB_FORMAT_MAP,
    ArtworkFormat,
    ithmb_formats_for_device,
    resolve_cover_art_format_definitions_for_device,
)

# ── Artwork format tables ─────────────────────────────────────────────────
# All canonical format definitions now live in iopenpod.device.
#
# The dicts below are DERIVED from the canonical source so that existing
# callers (artwork_writer.py, __init__.py, etc.) still see the same
# ``{correlation_id: (width, height)}`` interface without changes.

# Combined lookup for ALL known format IDs (validation / preserved art)
ALL_KNOWN_FORMATS: dict[int, tuple[int, int]] = {
    fid: (af.width, af.height) for fid, af in ITHMB_FORMAT_MAP.items()
}

# Per-family convenience dicts — thin wrappers around ipod_device data.
# May be removed in a future cleanup once all callers migrate to
# ``ithmb_formats_for_device()`` or ``capabilities_for_family_gen()``.
IPOD_CLASSIC_FORMATS = ithmb_formats_for_device("iPod Classic", "6th Gen")
IPOD_NANO_1G2G_FORMATS = ithmb_formats_for_device("iPod Nano", "1st Gen")
IPOD_4G_PHOTO_FORMATS = ithmb_formats_for_device("iPod", "4th Gen (photo)")
IPOD_5G_FORMATS = ithmb_formats_for_device("iPod", "5th Gen")
IPOD_NANO_4G_FORMATS = ithmb_formats_for_device("iPod Nano", "4th Gen")
IPOD_NANO_5G_FORMATS = ithmb_formats_for_device("iPod Nano", "5th Gen")

# Stride override: format_id → stride in pixels (when stride != width)
IPOD_STRIDE_OVERRIDE: dict[int, int] = {}


def _format_decompression_bomb_message(source_path: str, exc: Exception) -> str:
    base = f"Artwork image exceeds Pillow safety limit: {exc}"
    if source_path:
        return f"{base} Offending image: {source_path}"
    return base


def get_artwork_format_definitions(ipod_path: str) -> dict[int, ArtworkFormat]:
    """Return device-specific artwork format objects for the connected iPod."""
    from iopenpod.device import get_current_device_for_path

    device = get_current_device_for_path(ipod_path)
    resolved = resolve_cover_art_format_definitions_for_device(device)
    if resolved:
        return resolved
    return {}


def get_artwork_formats(ipod_path: str) -> dict[int, tuple[int, int]]:
    """Return the correct format table for the connected iPod.

    Reads from the centralised DeviceInfo store (populated when the device
    was selected). Falls back to the model capabilities table. Only code paths
    without an identified device stop instead of guessing another model's
    binary artwork layout.
    """
    import logging
    _log = logging.getLogger(__name__)

    from iopenpod.device import get_current_device_for_path

    defs = get_artwork_format_definitions(ipod_path)
    if defs:
        _log.info("ART: using resolved format definitions: %s", list(defs.keys()))
        return {fid: (int(fmt.width), int(fmt.height)) for fid, fmt in defs.items()}

    device = get_current_device_for_path(ipod_path)
    _log.warning(
        "ART: no artwork definitions available for device %s %s at %s; "
        "refusing to guess an unrelated device format",
        getattr(device, "model_family", "") or "unknown",
        getattr(device, "generation", "") or "",
        ipod_path,
    )
    return {}


def _extract_format_ids(data: bytes) -> list[int]:
    """Extract correlation IDs from mhif entries in an ArtworkDB binary."""
    return extract_format_ids(data)


def image_from_bytes(art_bytes: bytes, *, source_path: str = "") -> Image.Image | None:
    """
    Load an image from raw bytes (JPEG/PNG/etc).

    Args:
        art_bytes: Raw image file bytes

    Returns:
        PIL Image in RGB mode, or None on failure
    """
    try:
        img = Image.open(io.BytesIO(art_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGBA').convert('RGB')
        return img
    except Image.DecompressionBombError as exc:
        raise ValueError(_format_decompression_bomb_message(source_path, exc)) from exc
    except Exception:
        return None


def resize_for_format(img: Image.Image, format_id: int) -> Image.Image:
    """
    Resize an image to the exact iPod format dimensions.

    Album art is square by convention.  We resize directly to the target
    format dimensions (e.g. 128×128, 320×320, 56×56) without preserving
    aspect ratio.  This matches iTunes behaviour and guarantees that
    imgSize / height / 2 == format_width (the stride the iPod firmware
    computes when decoding ithmb data).

    For the 99.9 % of album art that is already square, no distortion
    occurs.  For the rare non-square source, the stretch is invisible
    at thumbnail sizes.

    Args:
        img: Source PIL Image in RGB mode
        format_id: Correlation ID (1055, 1060, 1061)

    Returns:
        Resized PIL Image at exactly (format_w, format_h)
    """
    if format_id not in ALL_KNOWN_FORMATS:
        raise ValueError(f"Unknown format ID: {format_id}")

    target_w, target_h = ALL_KNOWN_FORMATS[format_id]
    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)


def rgb888_to_rgb565(img: Image.Image, format_width: int, format_height: int,
                     stride: int | None = None) -> bytes:
    """
    Convert an RGB888 image to RGB565 little-endian pixel data.

    The image MUST already be exactly format_width × format_height pixels
    (ensured by resize_for_format).  When stride > format_width, each
    row is padded with zero-pixels to reach stride pixels.

    Output size = stride * format_height * 2 bytes
    (stride defaults to format_width when not given).

    Args:
        img: PIL Image in RGB mode, exactly format_width × format_height
        format_width: Expected width (for validation)
        format_height: Expected height (for validation)
        stride: Row stride in pixels (>= format_width). If None, equals format_width.

    Returns:
        Raw RGB565_LE bytes
    """
    if stride is None:
        stride = format_width

    arr = np.array(img, dtype=np.uint32)
    actual_h, actual_w = arr.shape[:2]

    assert actual_w == format_width and actual_h == format_height, \
        f"Image {actual_w}×{actual_h} != expected {format_width}×{format_height}"

    # Convert RGB888 → RGB565
    r = (arr[:, :, 0] >> 3) & 0x1F   # 5 bits red
    g = (arr[:, :, 1] >> 2) & 0x3F   # 6 bits green
    b = (arr[:, :, 2] >> 3) & 0x1F   # 5 bits blue
    rgb565 = ((r << 11) | (g << 5) | b).astype(np.uint16)

    if stride > format_width:
        # Pad each row with zeros to reach stride pixels
        padded = np.zeros((format_height, stride), dtype=np.uint16)
        padded[:, :format_width] = rgb565
        rgb565 = padded

    # Convert to little-endian bytes
    return rgb565.astype('<u2').tobytes()


def convert_art_for_ipod(art_bytes: bytes, format_id: int) -> dict | None:
    """
    Convert album art to iPod RGB565 format for a specific size.

    Args:
        art_bytes: Raw image bytes (JPEG/PNG)
        format_id: iPod correlation ID (1055, 1060, 1061)

    Returns:
        Dict with keys: 'data' (bytes), 'width', 'height', 'size',
        'format_width', 'format_height', or None on failure
    """
    img = image_from_bytes(art_bytes)
    if img is None:
        return None

    format_w, format_h = ALL_KNOWN_FORMATS[format_id]
    stride = IPOD_STRIDE_OVERRIDE.get(format_id, format_w)
    resized = resize_for_format(img, format_id)

    # Convert to RGB565 — image is already exactly format_w × format_h
    # stride may be > format_w (e.g. 1061: 55px padded to 56)
    pixel_data = rgb888_to_rgb565(resized, format_w, format_h, stride)

    return {
        'data': pixel_data,
        'width': format_w,             # visible pixel width
        'height': format_h,            # visible pixel height
        'size': len(pixel_data),       # stride * height * 2
        'format_width': format_w,
        'format_height': format_h,
    }
