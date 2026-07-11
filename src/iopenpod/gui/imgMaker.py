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
from dataclasses import dataclass
from typing import Any, Literal, cast, overload

from PIL import Image

from iopenpod.artworkdb_shared.constants import IMAGE_CONTAINER_NAMES
from iopenpod.artworkdb_shared.ithmb_paths import normalize_ithmb_filename
from iopenpod.artworkdb_writer.ithmb_codecs import decode_pixels_for_format
from iopenpod.device.artwork_presets import ArtworkFormat

logger = logging.getLogger(__name__)


# ============================================================================
# SHARED CACHE (INTERNAL)
# ============================================================================

# Cache for parsed ArtworkDB and index
_artworkdb_cache = None
_artworkdb_path_cache = None
_artworkdb_signature_cache = None
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
ArtworkMetadataRows = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArtworkFormatPreview:
    format_id: int
    label: str
    description: str
    width: int
    height: int
    pixel_format: str
    size: int
    filename: str
    offset: int
    image: Image.Image
    metadata: ArtworkMetadataRows = ()


@dataclass(frozen=True)
class TrackArtworkPreview:
    img_id: int
    song_id: int
    variants: tuple[ArtworkFormatPreview, ...]
    metadata: ArtworkMetadataRows = ()

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

def _artworkdb_signature(artworkdb_path: str):
    normalized_path = os.path.normcase(os.path.abspath(os.fspath(artworkdb_path)))
    try:
        stat = os.stat(normalized_path)
    except OSError:
        return (normalized_path, None, None)
    return (normalized_path, stat.st_mtime_ns, stat.st_size)


def configure_artwork_api(artworkdb_path: str, artwork_folder_path: str | None = None):
    """Configure and warm the shared ArtworkDB context.

    Simple API entrypoint for callers that want one-time setup and then
    repeated `get_artwork` calls.
    """
    global _artworkdb_cache, _artworkdb_path_cache, _artworkdb_signature_cache, _img_id_index, _artwork_folder_cache

    signature = _artworkdb_signature(artworkdb_path)
    with _cache_lock:
        if _artworkdb_cache is None or _artworkdb_signature_cache != signature:
            from iopenpod.artworkdb_parser.parser import parse_artworkdb
            _artworkdb_cache = parse_artworkdb(artworkdb_path)
            _artworkdb_path_cache = artworkdb_path
            _artworkdb_signature_cache = signature
            _img_id_index = _build_img_id_index(_artworkdb_cache)
            clear_image_cache()

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

    if mode == "image_only":
        cached = _image_cache_get(int(img_id))
        if cached is not None:
            return cached[0].copy()

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


def get_track_artwork_previews(
    tracks: dict[str, Any] | list[dict[str, Any]],
    *,
    artworkdb_data: dict[str, Any] | None = None,
    artwork_folder_path: str | None = None,
    img_id_index: dict[int, dict[str, Any]] | None = None,
) -> list[TrackArtworkPreview]:
    """Decode every assigned artwork entry and every available format variant."""
    if isinstance(tracks, dict):
        track_list = [tracks]
    else:
        track_list = tracks

    if artworkdb_data is None:
        artworkdb_data = _artworkdb_cache
    if artwork_folder_path is None:
        artwork_folder_path = _artwork_folder_cache
    if artworkdb_data is None or not artwork_folder_path:
        return []
    if img_id_index is None:
        img_id_index = _img_id_index or _build_img_id_index(artworkdb_data)

    entries: list[dict[str, Any]] = []
    seen_img_ids: set[int] = set()
    for track in track_list:
        for entry in _entries_for_track_artwork(track, artworkdb_data, img_id_index):
            img_id = entry.get("img_id")
            if img_id is None:
                continue
            try:
                img_id_int = int(img_id)
            except (TypeError, ValueError):
                continue
            if img_id_int in seen_img_ids:
                continue
            seen_img_ids.add(img_id_int)
            entries.append(entry)

    previews: list[TrackArtworkPreview] = []
    for entry in entries:
        variants = _decode_entry_format_previews(entry, artwork_folder_path)
        if variants:
            previews.append(
                TrackArtworkPreview(
                    img_id=int(entry.get("img_id") or 0),
                    song_id=int(entry.get("songId") or entry.get("song_id") or 0),
                    variants=tuple(variants),
                    metadata=_artwork_entry_metadata(entry),
                )
            )
    return previews


def get_artwork_colors(image: Image.Image):
    """Return (dominant_color, album_colors) for an image."""
    dcol = getDominantColor(image)
    return dcol, getAlbumColors(image, bg=dcol)


def clear_artwork_api():
    """Clear configured artwork context and all shared artwork caches."""
    global _artworkdb_cache, _artworkdb_path_cache, _artworkdb_signature_cache, _img_id_index, _artwork_folder_cache
    with _cache_lock:
        _artworkdb_cache = None
        _artworkdb_path_cache = None
        _artworkdb_signature_cache = None
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


def _track_artwork_refs(track: dict[str, Any]) -> list[int]:
    refs: list[int] = []
    for key in ("artwork_id_ref", "mhii_link", "mhiiLink"):
        value = track.get(key)
        if value in (None, "", 0):
            continue
        try:
            refs.append(int(value))
        except (TypeError, ValueError):
            continue
    return refs


def _entries_for_track_artwork(
    track: dict[str, Any],
    artworkdb_data: dict[str, Any],
    img_id_index: dict[int, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_img_ids: set[int] = set()

    def add_entry(entry: dict[str, Any] | None) -> None:
        if not isinstance(entry, dict):
            return
        raw_img_id = entry.get("img_id")
        if raw_img_id is None:
            return
        try:
            img_id = int(raw_img_id)
        except (TypeError, ValueError):
            return
        if img_id in seen_img_ids:
            return
        seen_img_ids.add(img_id)
        entries.append(entry)

    if img_id_index is not None:
        for ref in _track_artwork_refs(track):
            add_entry(img_id_index.get(ref))
    else:
        refs = set(_track_artwork_refs(track))
        for entry in artworkdb_data.get("mhli", []):
            raw_img_id = entry.get("img_id")
            if raw_img_id is None:
                continue
            try:
                if int(raw_img_id) in refs:
                    add_entry(entry)
            except (TypeError, ValueError):
                continue

    track_ids: set[int] = set()
    for key in ("db_track_id", "track_id"):
        value = track.get(key)
        if value in (None, "", 0):
            continue
        try:
            track_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    if track_ids:
        for entry in artworkdb_data.get("mhli", []):
            try:
                song_id = int(entry.get("songId") or entry.get("song_id") or 0)
            except (TypeError, ValueError):
                continue
            if song_id in track_ids:
                add_entry(entry)

    return entries


def _metadata_value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return repr(value)


def _flatten_metadata(value: Any, prefix: str = "") -> ArtworkMetadataRows:
    rows: list[tuple[str, str]] = []

    def visit(current: Any, path: str) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path)
            return
        if isinstance(current, (list, tuple)):
            if not current:
                rows.append((path, "[]"))
                return
            for index, child in enumerate(current):
                visit(child, f"{path}[{index}]")
            return
        rows.append((path, _metadata_value_text(current)))

    visit(value, prefix)
    return tuple((key, val) for key, val in rows if key)


def _artwork_entry_metadata(entry: dict[str, Any]) -> ArtworkMetadataRows:
    container_keys = {"_image_containers", *IMAGE_CONTAINER_NAMES}
    entry_fields = {
        key: value
        for key, value in entry.items()
        if key not in container_keys
    }
    return _flatten_metadata(entry_fields)


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

def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_two_byte_packed_format(pixel_format: str) -> bool:
    return (
        pixel_format.startswith("RGB565")
        or pixel_format.startswith("RGB555")
        or pixel_format.startswith("REC_RGB555")
        or pixel_format == "UYVY"
    )


def _artwork_format_override_from_image_info(
    format_id: int,
    image_info: dict[str, Any],
    image_format: dict[str, Any],
) -> ArtworkFormat | None:
    pixel_format = str(image_format.get("format") or "")
    if not pixel_format:
        return None

    width = _int_or_zero(image_format.get("width") or image_info.get("imageWidth"))
    height = _int_or_zero(image_format.get("height") or image_info.get("imageHeight"))
    if format_id <= 0 or width <= 0 or height <= 0:
        return None

    row_bytes = _int_or_zero(
        image_format.get("row_bytes")
        or image_format.get("rowBytes")
        or image_format.get("rowBytesHint")
    )
    if row_bytes <= 0 and _is_two_byte_packed_format(pixel_format):
        stored_width = _int_or_zero(image_info.get("estimatedPixmapWidth"))
        row_bytes = max(width, stored_width) * 2

    return ArtworkFormat(
        format_id=int(format_id),
        width=width,
        height=height,
        row_bytes=max(0, row_bytes),
        pixel_format=pixel_format,
        role=str(image_format.get("role") or "cover"),
        description=str(image_format.get("description") or ""),
    )


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

    if format_id is not None:
        format_id_int = int(format_id)
        fmt_override = _artwork_format_override_from_image_info(
            format_id_int,
            image_info,
            fmt_info,
        )
        decoded = decode_pixels_for_format(
            format_id_int,
            img_data,
            int(image_info.get("imageWidth") or target_width),
            int(image_info.get("imageHeight") or target_height),
            hpad,
            vpad,
            fmt_override=fmt_override,
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


def _image_result_from_container(container: dict[str, Any]) -> dict[str, Any] | None:
    container_name = None
    for name in IMAGE_CONTAINER_NAMES:
        if name in container:
            container_name = name
            break
    if container_name is None:
        return None

    child = container.get(container_name)
    if not isinstance(child, dict):
        return None

    result = child.get("result")
    return result if isinstance(result, dict) else None


def _image_result_file_info(image_result: dict[Any, Any]) -> dict[str, Any]:
    """Return MHOD type-3 file metadata from parser or fixture-shaped results."""
    for key in (3, "3"):
        value = image_result.get(key)
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    return {}


def _iter_entry_image_candidates(entry):
    """Yield parsed MHNI results for all usable image containers on an entry."""
    containers = entry.get("_image_containers")
    if isinstance(containers, list):
        for container in containers:
            if not isinstance(container, dict):
                continue
            result = _image_result_from_container(container)
            if result is None:
                continue
            yield from _iter_image_result_candidate(result, container)
        return

    for container_name in IMAGE_CONTAINER_NAMES:
        container = entry.get(container_name)
        if not isinstance(container, dict):
            continue
        result = _image_result_from_container(container)
        if result is None:
            continue
        yield from _iter_image_result_candidate(result, container)


def _iter_image_result_candidate(result: dict[str, Any], container: dict[str, Any]):
    required_keys = ("ithmbOffset", "imgSize", "image_format")
    if not all(key in result for key in required_keys):
        return

    image_format = result.get("image_format") or {}
    width = image_format.get("width") or result.get("imageWidth") or 0
    height = image_format.get("height") or result.get("imageHeight") or 0
    area = int(width) * int(height)

    yield area, result, container


def _format_preview_label(format_id: int, width: int, height: int) -> str:
    if width and height:
        return f"{format_id} {width}x{height}"
    return str(format_id)


def _decode_entry_format_previews(entry: dict[str, Any], ithmb_folder_path: str) -> list[ArtworkFormatPreview]:
    variants: list[ArtworkFormatPreview] = []
    seen_locations: set[tuple[int, str, int]] = set()
    candidates = sorted(
        _iter_entry_image_candidates(entry),
        key=lambda item: (item[0], int(item[1].get("correlationID") or 0)),
        reverse=True,
    )

    for _area, image_result, container in candidates:
        image_format = image_result.get("image_format") or {}
        try:
            format_id = int(image_result.get("correlationID") or image_format.get("format_id") or 0)
            offset = int(image_result.get("ithmbOffset") or 0)
        except (TypeError, ValueError):
            continue
        if format_id <= 0:
            continue

        file_info = _image_result_file_info(image_result)
        ithmb_filename = normalize_ithmb_filename(format_id, file_info.get("File Name"))

        location_key = (format_id, ithmb_filename, offset)
        if location_key in seen_locations:
            continue
        seen_locations.add(location_key)

        ithmb_path = os.path.join(ithmb_folder_path, ithmb_filename)
        img = generate_image(ithmb_path, image_result)
        if img is None:
            continue

        width = int(image_format.get("width") or image_result.get("imageWidth") or img.width or 0)
        height = int(image_format.get("height") or image_result.get("imageHeight") or img.height or 0)
        variants.append(
            ArtworkFormatPreview(
                format_id=format_id,
                label=_format_preview_label(format_id, width, height),
                description=str(image_format.get("description") or ""),
                width=width,
                height=height,
                pixel_format=str(image_format.get("format") or ""),
                size=int(image_result.get("imgSize") or 0),
                filename=ithmb_filename,
                offset=offset,
                image=img,
                metadata=_flatten_metadata(container),
            )
        )

    return variants


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
        for _area, image_result, _container in candidates:
            file_info = _image_result_file_info(image_result)
            ithmb_filename = normalize_ithmb_filename(
                int(image_result.get("correlationID") or 0),
                file_info.get("File Name"),
            )
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
