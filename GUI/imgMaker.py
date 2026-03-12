import logging
import os
import threading
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)


# Cache for parsed ArtworkDB and index
_artworkdb_cache = None
_artworkdb_path_cache = None
_imgid_index = None
_cache_lock = threading.Lock()


def _build_imgid_index(artworkdb_data):
    """Build a dictionary index mapping imgId to entry for O(1) lookups."""
    index = {}
    for entry in artworkdb_data.get("mhli", []):
        imgId = entry.get("imgId")
        if imgId is not None:
            index[imgId] = entry
    return index


def get_artworkdb_cached(artworkdb_path):
    """Get cached artworkdb data, parsing only if needed. Thread-safe."""
    global _artworkdb_cache, _artworkdb_path_cache, _imgid_index

    with _cache_lock:
        if _artworkdb_cache is not None and _artworkdb_path_cache == artworkdb_path:
            return _artworkdb_cache, _imgid_index

        from ArtworkDB_Parser.parser import parse_artworkdb
        _artworkdb_cache = parse_artworkdb(artworkdb_path)
        _artworkdb_path_cache = artworkdb_path
        _imgid_index = _build_imgid_index(_artworkdb_cache)
        return _artworkdb_cache, _imgid_index


def clear_artworkdb_cache():
    """Clear the cache when device changes."""
    global _artworkdb_cache, _artworkdb_path_cache, _imgid_index
    with _cache_lock:
        _artworkdb_cache = None
        _artworkdb_path_cache = None
        _imgid_index = None


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


def _enhance_decoded_artwork(img_pil):
    """Apply mild post-processing to small decoded ithmb artwork."""
    width, height = img_pil.size
    min_dim = min(width, height)

    if min_dim <= 0:
        return img_pil

    sharpen_percent = 105
    contrast_factor = 1.03
    color_factor = 1.02

    if min_dim <= 80:
        sharpen_percent = 120
        contrast_factor = 1.05
        color_factor = 1.03
    elif min_dim <= 140:
        sharpen_percent = 112
        contrast_factor = 1.04
        color_factor = 1.025

    enhanced = img_pil.filter(
        ImageFilter.UnsharpMask(radius=0.8, percent=sharpen_percent, threshold=3)
    )
    enhanced = ImageEnhance.Contrast(enhanced).enhance(contrast_factor)
    enhanced = ImageEnhance.Color(enhanced).enhance(color_factor)
    return enhanced


def generate_image(ithmb_filename, image_info):
    """Generate image from the ithmb file based on image_info."""
    try:
        with open(ithmb_filename, "rb") as f:
            f.seek(image_info["ithmbOffset"])
            img_data = f.read(image_info["imgSize"])
    except Exception as e:
        logger.warning("Error reading %s: %s", ithmb_filename, e)
        return None

    fmt = image_info["image_format"]["format"]
    target_height = image_info["image_format"]["height"]
    target_width = image_info["image_format"]["width"]

    if fmt.startswith("RGB565"):
        num_pixels = image_info["imgSize"] // 2
        current_height = num_pixels // target_width
        current_width = target_width

        # Use byte-order-aware pixel reader
        pixels = read_rgb565_pixels(img_data, fmt)
        rgb_array = rgb565_to_rgb888_vectorized(pixels)

        # Guard against empty/truncated ithmb data
        expected_size = current_height * current_width * 3
        if rgb_array.size == 0 or rgb_array.size < expected_size:
            return None

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
        return _enhance_decoded_artwork(img_pil)

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


def getAlbumColors(image):
    """Extract background + text colors from album artwork (iTunes 11 style).

    Returns a dict with:
        bg:             (r, g, b) - dominant background color
        text:           (r, g, b) - primary text color (high contrast with bg)
        text_secondary: (r, g, b) - secondary text color (lower contrast)
    """
    import colorsys

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


def find_image_by_imgId(artworkdb_data, ithmb_folder_path, imgId, imgid_index=None):
    """Find and return image for the given imgID.

    Args:
        artworkdb_data: Parsed ArtworkDB dict (from parse_artworkdb)
        ithmb_folder_path: Path to the Artwork folder containing .ithmb files
        imgId: The image ID to find
        imgid_index: Optional pre-built index for O(1) lookup

    Returns:
        Tuple of (PIL.Image, dominant_color, album_colors) or None if not found
    """
    if artworkdb_data is None:
        return None

    # Use index for O(1) lookup if available
    if imgid_index is not None:
        entry = imgid_index.get(imgId)
        if entry is None:
            return None
        entries = [entry]
    else:
        # Fallback to linear search if no index provided
        entries = [e for e in artworkdb_data.get("mhli", []) if e.get("imgId") == imgId]

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
            if img is None:
                continue

            dcol = getDominantColor(img)
            album_colors = getAlbumColors(img)
            return img, dcol, album_colors
