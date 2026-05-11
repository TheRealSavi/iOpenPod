"""Artwork image loading and color extraction for iOpenPod.

This module provides a simple, unified API for loading and extracting metadata
from iPod album artwork. The public interface is minimal and focused:

    configure_artwork_api(artworkdb_path, artwork_folder)
        Warm the ArtworkDB context once at startup or device change.

    get_artwork(img_id, mode="with_colors")
        Load artwork by image ID. Modes:
        - "image_only": Returns PIL.Image (for lists/thumbnails)
        - "with_colors": Returns (image, dominant_color, album_colors) (for UI backgrounds)
        - "cache_only": Returns cached result or None (UI-thread peek, no decode)

    get_artwork_colors(image)
        Extract dominant and album colors from an image.

    clear_artwork_api()
        Clear all caches (call on device disconnect).

Internal subsystems:
- Shared LRU image cache (thread-safe, 500 max)
- ArtworkDB parsing and indexing
- RGB565 image decoding with geometry heuristics
- Color extraction using iTunes 11 algorithms

All low-level functions (_*) are internal. Legacy API functions are deprecated.
"""

import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Literal, overload

import numpy as np
from PIL import Image

from ArtworkDB_Writer.ithmb_codecs import decode_pixels_for_format

logger = logging.getLogger(__name__)


# ============================================================================
# SHARED CACHE (INTERNAL)
# ============================================================================

# Cache for parsed ArtworkDB and index
_artworkdb_cache = None
_artworkdb_path_cache = None
_img_id_index = None
_artwork_folder_cache = None
_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Shared decoded-image cache (LRU, keyed by artwork_id / img_id)
# ---------------------------------------------------------------------------
_IMAGE_CACHE_MAX = 500
ArtworkColors = dict[str, tuple[int, int, int]]
ArtworkResult = tuple[Image.Image, tuple[int, int, int], ArtworkColors]
ArtworkMode = Literal["image_only", "with_colors", "cache_only"]

_image_cache: OrderedDict[int, ArtworkResult] = OrderedDict()
_image_cache_lock = threading.Lock()


def _image_cache_get(img_id: int):
    """Return cached (pil_image, dcol, album_colors) or None. Thread-safe."""
    with _image_cache_lock:
        val = _image_cache.get(img_id)
        if val is not None:
            _image_cache.move_to_end(img_id)
        return val


def _image_cache_put(img_id: int, value):
    """Store (pil_image, dcol, album_colors) in the LRU cache. Thread-safe."""
    with _image_cache_lock:
        _image_cache[img_id] = value
        _image_cache.move_to_end(img_id)
        while len(_image_cache) > _IMAGE_CACHE_MAX:
            _image_cache.popitem(last=False)


def clear_image_cache():
    """Clear the decoded image cache (call on device change)."""
    with _image_cache_lock:
        _image_cache.clear()


# ============================================================================
# PUBLIC API — SIMPLE ARTWORK INTERFACE
# ============================================================================

def configure_artwork_api(artworkdb_path: str, artwork_folder_path: str | None = None):
    """Configure and warm the shared ArtworkDB context.

    Simple API entrypoint for callers that want one-time setup and then
    repeated `get_artwork` calls.
    """
    global _artworkdb_cache, _artworkdb_path_cache, _img_id_index, _artwork_folder_cache

    with _cache_lock:
        if _artworkdb_cache is None or _artworkdb_path_cache != artworkdb_path:
            from ArtworkDB_Parser.parser import parse_artworkdb
            _artworkdb_cache = parse_artworkdb(artworkdb_path)
            _artworkdb_path_cache = artworkdb_path
            _img_id_index = _build_img_id_index(_artworkdb_cache)

    if artwork_folder_path is not None:
        _artwork_folder_cache = artwork_folder_path

    return _artworkdb_cache, _img_id_index


@overload
def get_artwork(
    img_id: int,
    *,
    mode: Literal["image_only"],
    artworkdb_data: dict[str, Any] | None = None,
    artwork_folder_path: str | None = None,
    img_id_index: dict[int, dict[str, Any]] | None = None,
) -> Image.Image | None: ...


@overload
def get_artwork(
    img_id: int,
    *,
    mode: Literal["with_colors"],
    artworkdb_data: dict[str, Any] | None = None,
    artwork_folder_path: str | None = None,
    img_id_index: dict[int, dict[str, Any]] | None = None,
) -> ArtworkResult | None: ...


@overload
def get_artwork(
    img_id: int,
    *,
    mode: Literal["cache_only"],
    artworkdb_data: dict[str, Any] | None = None,
    artwork_folder_path: str | None = None,
    img_id_index: dict[int, dict[str, Any]] | None = None,
) -> ArtworkResult | None: ...


def get_artwork(
    img_id: int,
    *,
    mode: ArtworkMode = "with_colors",
    artworkdb_data: dict[str, Any] | None = None,
    artwork_folder_path: str | None = None,
    img_id_index: dict[int, dict[str, Any]] | None = None,
) -> Image.Image | ArtworkResult | None:
    """Get artwork by image id through a single concrete API.

    Modes:
      - "image_only": returns PIL.Image | None
      - "with_colors": returns (PIL.Image, dominant_color, album_colors) | None
      - "cache_only": returns cached tuple or None, without decoding
    """
    if mode == "cache_only":
        return _image_cache_get(int(img_id))

    if artworkdb_data is None:
        artworkdb_data = _artworkdb_cache

    if img_id_index is None:
        img_id_index = _img_id_index

    if artwork_folder_path is None:
        artwork_folder_path = _artwork_folder_cache

    if artworkdb_data is None or not artwork_folder_path:
        return None

    if mode == "image_only":
        return _decode_image_from_db(artworkdb_data, artwork_folder_path, int(img_id), img_id_index)

    return _find_artwork_result(artworkdb_data, artwork_folder_path, int(img_id), img_id_index)


def get_artwork_colors(image: Image.Image):
    """Return (dominant_color, album_colors) for an image."""
    dcol = getDominantColor(image)
    return dcol, getAlbumColors(image, bg=dcol)


def clear_artwork_api():
    """Clear configured artwork context and all shared artwork caches."""
    global _artworkdb_cache, _artworkdb_path_cache, _img_id_index, _artwork_folder_cache
    with _cache_lock:
        _artworkdb_cache = None
        _artworkdb_path_cache = None
        _img_id_index = None
        _artwork_folder_cache = None
    clear_image_cache()


# ============================================================================
# INTERNAL IMPLEMENTATIONS
# ============================================================================

def _build_img_id_index(artworkdb_data):
    """Build a dictionary index mapping img_id to entry for O(1) lookups."""
    index = {}
    for entry in artworkdb_data.get("mhli", []):
        img_id = entry.get("img_id")
        if img_id is not None:
            index[img_id] = entry
    return index


def get_artworkdb_cached(artworkdb_path):
    """REMOVED: Use configure_artwork_api() instead."""
    raise NotImplementedError(
        "get_artworkdb_cached() has been removed. Use configure_artwork_api() instead."
    )


def clear_artworkdb_cache():
    """REMOVED: Use clear_artwork_api() instead."""
    raise NotImplementedError(
        "clear_artworkdb_cache() has been removed. Use clear_artwork_api() instead."
    )


# ============================================================================
# IMAGE FORMAT & GENERATION (INTERNAL HELPERS)
# ============================================================================

def rgb565_to_rgb888_vectorized(pixels):
    """Convert RGB565 to RGB888 format using vectorized NumPy operations."""
    pixels = pixels.astype(np.uint32)
    r = ((pixels >> 11) & 0x1F) * 255 // 31
    g = ((pixels >> 5) & 0x3F) * 255 // 63
    b = (pixels & 0x1F) * 255 // 31
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def read_rgb565_pixels(img_data, fmt):
    """Read RGB565 pixels with correct byte order based on format."""
    if fmt in ("RGB565_BE", "RGB565_BE_90"):
        # Big-endian: use dtype with explicit byte order
        pixels = np.frombuffer(img_data, dtype='>u2')
    else:
        # Little-endian (default for most album art)
        pixels = np.frombuffer(img_data, dtype='<u2')
    return pixels


def generate_image(ithmb_filename, image_info):
    """Generate image from the ithmb file based on image_info."""
    try:
        with open(ithmb_filename, "rb") as f:
            f.seek(image_info["ithmbOffset"])
            img_data = f.read(image_info["imgSize"])
    except Exception as e:
        logger.warning("Error reading %s: %s", ithmb_filename, e)
        return None

    fmt_info = image_info.get("image_format") or {}
    fmt = fmt_info.get("format")
    if not fmt:
        logger.warning("generate_image: missing image_format for %s", ithmb_filename)
        return None

    format_id = image_info.get("correlationID")
    target_height = image_info["image_format"]["height"]
    target_width = image_info["image_format"]["width"]
    hpad = max(0, int(image_info.get("horizontalPadding") or 0))
    vpad = max(0, int(image_info.get("verticalPadding") or 0))

    if fmt.startswith("RGB565"):
        num_pixels = image_info["imgSize"] // 2

        # The mhni chunk records the actual stored pixmap layout:
        #   estimatedPixmapWidth  = row stride in pixels  (imageWidth  + horizontalPadding)
        #   estimatedPixmapHeight = total rows            (imageHeight + verticalPadding)
        # When both multiply to exactly num_pixels they are unambiguous — use
        # them directly.  When only the width is available (height missing or
        # inconsistent) fall back to width-only division.  Finally fall back to
        # the format-table width.  This handles Nano 7G entries whose
        # correlationID maps to a 140×140 format table entry but the .ithmb
        # file contains a much smaller pixmap (e.g. 58×57 = 3306 pixels).
        mhni_w = image_info.get("estimatedPixmapWidth") or 0
        mhni_h = image_info.get("estimatedPixmapHeight") or 0
        image_w = image_info.get("imageWidth") or 0
        image_h = image_info.get("imageHeight") or 0

        # Prefer exact geometries that consume the payload exactly.
        # Avoid forcing format-table width (e.g. 140) when payload math disagrees.
        pref_w = mhni_w or image_w or target_width
        pref_h = mhni_h or image_h or target_height

        pair_candidates = []
        for w, h in (
            (mhni_w, mhni_h),
            (image_w, image_h),
            (target_width, target_height),
        ):
            if w > 0 and h > 0 and w * h == num_pixels:
                pair_candidates.append((w, h))

        width_candidates = set()
        for base in (mhni_w, image_w, target_width):
            if base and base > 0:
                width_candidates.add(base)
                if base > 1:
                    width_candidates.add(base - 1)
                width_candidates.add(base + 1)

        div_candidates = []
        for w in sorted(width_candidates):
            if w > 0 and num_pixels % w == 0:
                h = num_pixels // w
                score = abs(w - pref_w) + abs(h - pref_h)
                # Ambiguous stride cases (e.g. 57x58 vs 58x57) often shear when
                # width is chosen too small. Prefer larger width on score ties.
                target_bias = abs(w - target_width) + abs(h - target_height)
                div_candidates.append((score, target_bias, -w, w, h))

        if pair_candidates:
            current_width, current_height = min(
                pair_candidates,
                key=lambda wh: abs(wh[0] - pref_w) + abs(wh[1] - pref_h),
            )
        elif div_candidates:
            _score, _bias, _neg_w, current_width, current_height = min(div_candidates)
        else:
            logger.warning(
                "generate_image: no valid geometry for %s imgSize=%d (%d px) "
                "mhni w=%d h=%d imageWidth=%s imageHeight=%s fmt=%dx%d",
                ithmb_filename,
                image_info["imgSize"],
                num_pixels,
                mhni_w,
                mhni_h,
                image_info.get("imageWidth"),
                image_info.get("imageHeight"),
                target_width,
                target_height,
            )
            return None

        if current_width != target_width or current_height * current_width != num_pixels:
            logger.info(
                "generate_image: imgSize=%d (%d px) mhni w=%d h=%d → "
                "decode %dx%d (fmt %dx%d); imageWidth=%s imageHeight=%s "
                "hPad=%s vPad=%s",
                image_info["imgSize"], num_pixels, mhni_w, mhni_h,
                current_width, current_height, target_width, target_height,
                image_info.get("imageWidth"), image_info.get("imageHeight"),
                image_info.get("horizontalPadding"),
                image_info.get("verticalPadding"),
            )

        expected_pixels = current_height * current_width

        # Use byte-order-aware pixel reader
        pixels = read_rgb565_pixels(img_data, fmt)

        # Guard against empty/truncated ithmb data
        if len(pixels) == 0 or len(pixels) < expected_pixels:
            return None

        # Trim any partial-row trailing padding before conversion
        if len(pixels) > expected_pixels:
            pixels = pixels[:expected_pixels]

        rgb_array = rgb565_to_rgb888_vectorized(pixels)

        # Reshape image
        rgb_array = rgb_array.reshape((current_height, current_width, 3))
        img_pil = Image.fromarray(rgb_array)

        # Handle 90-degree rotation for _90 formats (PhotoPod full screen)
        if fmt.endswith("_90"):
            img_pil = img_pil.rotate(-90, expand=True)

        # Resize to target dimensions if needed
        if img_pil.size != (target_width, target_height):
            img_pil = img_pil.resize(
                (target_width, target_height), Image.Resampling.LANCZOS)
        return img_pil

    # Non-RGB565 formats (UYVY, I420, RGB555 variants, JPEG) go through
    # the shared format-aware decoder.
    if format_id is not None:
        decoded = decode_pixels_for_format(
            int(format_id),
            img_data,
            int(image_info.get("imageWidth") or target_width),
            int(image_info.get("imageHeight") or target_height),
            hpad,
            vpad,
        )
        if decoded is None:
            logger.warning("Unsupported/failed decode for format %s (id=%s)", fmt, format_id)
            return None
        if decoded.size != (target_width, target_height):
            decoded = decoded.resize((target_width, target_height), Image.Resampling.LANCZOS)
        return decoded

    logger.warning("Unsupported image format: %s", fmt)
    return None


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _yiq_brightness(r: int, g: int, b: int) -> float:
    """YIQ perceived brightness (0-255). Higher = lighter."""
    return (r * 299 + g * 587 + b * 114) / 1000


def _yiq_contrast(c1: tuple, c2: tuple) -> float:
    """Contrast ratio between two (r, g, b) colors using YIQ brightness."""
    return abs(_yiq_brightness(*c1) - _yiq_brightness(*c2))


def _detect_border(image_rgb, threshold: int = 8):
    """Detect and crop a solid-color border/frame around artwork.

    Returns the cropped image (or the original if no border detected).
    iTunes 11 skipped solid-color frames before sampling.
    """
    w, h = image_rgb.size
    if w < 6 or h < 6:
        return image_rgb

    pixels = image_rgb.load()
    corner_color = pixels[0, 0]

    # Check whether the left edge is all roughly the same color
    same_count = 0
    for y in range(0, h, max(1, h // 10)):
        pr, pg, pb = pixels[0, y]
        cr, cg, cb = corner_color
        if abs(pr - cr) < threshold and abs(pg - cg) < threshold and abs(pb - cb) < threshold:
            same_count += 1

    if same_count < (h // max(1, h // 10)) * 0.8:
        return image_rgb  # Left edge isn't uniform -- no border

    # Find border width (how many pixels deep the border goes)
    border = 0
    for x in range(min(w // 4, 20)):
        pr, pg, pb = pixels[x, h // 2]
        cr, cg, cb = corner_color
        if abs(pr - cr) < threshold and abs(pg - cg) < threshold and abs(pb - cb) < threshold:
            border = x + 1
        else:
            break

    if border > 1:
        return image_rgb.crop((border, border, w - border, h - border))
    return image_rgb


# ============================================================================
# PUBLIC UTILITIES — COLOR EXTRACTION
# ============================================================================

def getDominantColor(image):
    """Extract a dominant background color from album artwork (iTunes 11 style).

    Samples primarily from the left edge of the artwork (like iTunes 11),
    detects and skips solid-color borders/frames, and prefers saturated
    colors over black/white.

    Returns (r, g, b) tuple.
    """
    import colorsys

    # Resize for performance
    small = image.copy()
    small.thumbnail((80, 80))
    small_rgb = small.convert("RGB")

    # Detect and crop border frames
    small_rgb = _detect_border(small_rgb)

    w, h = small_rgb.size

    # Sample the left ~20% of the image (iTunes 11 approach)
    left_strip_w = max(2, w // 5)
    left_strip = small_rgb.crop((0, 0, left_strip_w, h))

    # Extract palette from left strip
    quantized = left_strip.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette_data = quantized.getpalette()[:24]

    best_color = None
    best_score = -1

    for i in range(0, len(palette_data), 3):
        r, g, b = palette_data[i], palette_data[i + 1], palette_data[i + 2]
        h_val, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

        # Score: prefer saturated, reasonably bright colors
        score = s * 2.5 + v
        if v < 0.15:
            score *= 0.2  # Too dark
        if s < 0.08:
            score *= 0.2  # Too desaturated (grays/whites/blacks)

        if score > best_score:
            best_score = score
            best_color = (r, g, b)

    if best_color is None:
        simple = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=1)
        best_color = tuple(simple.getpalette()[:3])

    r, g, b = best_color

    # If the best color is too neutral, fall back to sampling the whole image
    h_val, s_val, v_val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if s_val < 0.12 and best_score < 0.8:
        quantized_full = small_rgb.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette_full = quantized_full.getpalette()[:24]
        for i in range(0, len(palette_full), 3):
            fr, fg, fb = palette_full[i], palette_full[i + 1], palette_full[i + 2]
            fh, fs, fv = colorsys.rgb_to_hsv(fr / 255, fg / 255, fb / 255)
            fscore = fs * 2.5 + fv
            if fv < 0.15:
                fscore *= 0.2
            if fs < 0.08:
                fscore *= 0.2
            if fscore > best_score:
                best_score = fscore
                best_color = (fr, fg, fb)
                r, g, b = fr, fg, fb

    # Moderate boost to saturation and brightness for visual appeal
    h_val, s_val, v_val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s_val = min(1.0, s_val * 1.4 + 0.1)
    v_val = max(0.35, min(0.85, v_val * 1.2 + 0.05))
    r, g, b = colorsys.hsv_to_rgb(h_val, s_val, v_val)
    return (int(r * 255), int(g * 255), int(b * 255))


def getAlbumColors(image, bg=None):
    """Extract background + text colors from album artwork (iTunes 11 style).

    Args:
        image: PIL Image
        bg: Optional pre-computed dominant color (r, g, b). If None,
            getDominantColor(image) is called.

    Returns a dict with:
        bg:             (r, g, b) - dominant background color
        text:           (r, g, b) - primary text color (high contrast with bg)
        text_secondary: (r, g, b) - secondary text color (lower contrast)
    """
    import colorsys

    if bg is None:
        bg = getDominantColor(image)

    # Get palette from the full image for text color candidates
    small = image.copy()
    small.thumbnail((80, 80))
    small_rgb = small.convert("RGB")

    quantized = small_rgb.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    palette_data = quantized.getpalette()[:36]

    candidates = []
    for i in range(0, len(palette_data), 3):
        r, g, b = palette_data[i], palette_data[i + 1], palette_data[i + 2]
        contrast = _yiq_contrast((r, g, b), bg)
        candidates.append(((r, g, b), contrast))

    # Sort by contrast against background (highest first)
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Pick primary text: highest contrast, with minimum threshold
    text = (255, 255, 255) if _yiq_brightness(*bg) < 128 else (0, 0, 0)
    for color, contrast in candidates:
        if contrast >= 100:
            # Ensure it's distinct enough from bg
            h1, s1, _ = colorsys.rgb_to_hsv(*[c / 255 for c in color])
            h2, s2, _ = colorsys.rgb_to_hsv(*[c / 255 for c in bg])
            # Skip colors too similar in hue to the background
            hue_diff = min(abs(h1 - h2), 1 - abs(h1 - h2))
            if hue_diff > 0.05 or s1 < 0.15:
                text = color
                break

    # Pick secondary text: good contrast but distinct from primary
    text_secondary = tuple(max(0, min(255, c + (40 if _yiq_brightness(*bg) < 128 else -40))) for c in text)
    for color, contrast in candidates:
        if contrast >= 60 and _yiq_contrast(color, text) >= 30:
            text_secondary = color
            break

    return {"bg": bg, "text": text, "text_secondary": text_secondary}


def _iter_entry_image_candidates(entry):
    """Yield parsed MHNI results for all usable image containers on an entry."""
    for container_name in ("Full Res Image", "Thumbnail Image", "UNK MHOD 6"):
        container = entry.get(container_name)
        if not isinstance(container, dict):
            continue

        child = container.get(container_name)
        if not isinstance(child, dict):
            continue

        result = child.get("result")
        if not isinstance(result, dict):
            continue

        required_keys = ("ithmbOffset", "imgSize", "image_format")
        if not all(key in result for key in required_keys):
            continue

        image_format = result.get("image_format") or {}
        width = image_format.get("width") or result.get("imageWidth") or 0
        height = image_format.get("height") or result.get("imageHeight") or 0
        area = int(width) * int(height)

        yield area, result


def _decode_image_from_db(artworkdb_data, ithmb_folder_path, img_id, img_id_index=None):
    """Decode the PIL image for img_id without color extraction.

    Returns PIL.Image or None.
    """
    if artworkdb_data is None:
        return None

    if img_id_index is not None:
        entry = img_id_index.get(img_id)
        if entry is None:
            return None
        entries = [entry]
    else:
        entries = [e for e in artworkdb_data.get("mhli", []) if e.get("img_id") == img_id]

    for entry in entries:
        candidates = sorted(
            _iter_entry_image_candidates(entry),
            key=lambda item: item[0],
            reverse=True,
        )
        if not candidates:
            continue

        for _area, image_result in candidates:
            file_info = image_result.get("3", {})
            ithmb_filename = file_info.get(
                "File Name", f"F{image_result.get('correlationID')}_1.ithmb")
            if ithmb_filename.startswith(":"):
                ithmb_filename = ithmb_filename[1:]
            ithmb_path = os.path.join(ithmb_folder_path, ithmb_filename)

            img = generate_image(ithmb_path, image_result)
            if img is not None:
                return img

    return None


def decode_image_by_img_id(artworkdb_data, ithmb_folder_path, img_id, img_id_index=None):
    """REMOVED: Use get_artwork(img_id, mode="image_only") instead."""
    raise NotImplementedError(
        "decode_image_by_img_id() has been removed. "
        "Use get_artwork(img_id, mode='image_only') instead."
    )


def _find_artwork_result(artworkdb_data, ithmb_folder_path, img_id, img_id_index=None):
    """Internal implementation for full artwork lookup with color extraction."""
    # Check shared cache first
    cached = _image_cache_get(img_id)
    if cached is not None:
        return cached

    img = _decode_image_from_db(artworkdb_data, ithmb_folder_path, img_id, img_id_index)
    if img is None:
        return None

    dcol = getDominantColor(img)
    album_colors = getAlbumColors(img, bg=dcol)

    result = (img, dcol, album_colors)
    _image_cache_put(img_id, result)
    return result


def find_image_by_img_id(artworkdb_data, ithmb_folder_path, img_id, img_id_index=None):
    """REMOVED: Use get_artwork(img_id, mode="with_colors") instead."""
    raise NotImplementedError(
        "find_image_by_img_id() has been removed. "
        "Use get_artwork(img_id, mode='with_colors') instead."
    )
