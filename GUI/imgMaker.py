import os
import threading
import numpy as np
from PIL import Image


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


def generate_image(ithmb_filename, image_info):
    """Generate image from the ithmb file based on image_info."""
    try:
        with open(ithmb_filename, "rb") as f:
            f.seek(image_info["ithmbOffset"])
            img_data = f.read(image_info["imgSize"])
    except Exception as e:
        print(f"Error reading {ithmb_filename}: {e}")
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
        return img_pil

    print(f"Unsupported image format: {fmt}")
    return None


def getDominantColor(image):
    """Extract a vibrant dominant color from an image.

    Uses adaptive palette extraction then boosts saturation and brightness
    to get a more visually appealing background color.
    """
    import colorsys

    # Resize to small size for faster processing
    small = image.copy()
    small.thumbnail((50, 50))

    # Extract multiple colors and find the most vibrant one
    small_rgb = small.convert("RGB")
    colors = small_rgb.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = colors.getpalette()[:24]  # 8 colors * 3 RGB values

    best_color = None
    best_score = -1

    for i in range(0, len(palette), 3):
        r, g, b = palette[i], palette[i + 1], palette[i + 2]

        # Convert to HSV to evaluate saturation and value
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

        # Score based on saturation and brightness (prefer vibrant colors)
        # Avoid very dark colors (v < 0.2) and very light/white colors (s < 0.1)
        score = s * 2 + v  # Weight saturation more heavily
        if v < 0.15:  # Too dark
            score *= 0.3
        if s < 0.1:  # Too desaturated (grays/whites)
            score *= 0.3

        if score > best_score:
            best_score = score
            best_color = (r, g, b)

    if best_color is None:
        # Fallback to simple dominant color
        simple = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=1)
        best_color = tuple(simple.getpalette()[:3])

    r, g, b = best_color

    # Boost saturation and brightness for a more vivid result
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    # Aggressively increase saturation
    s = min(1.0, s * 2.0 + 0.25)

    # Boost brightness significantly
    v = max(0.5, min(0.95, v * 1.6 + 0.15))

    # Convert back to RGB
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def find_image_by_imgId(artworkdb_data, ithmb_folder_path, imgId, imgid_index=None):
    """Find and return image for the given imgID.

    Args:
        artworkdb_data: Parsed ArtworkDB dict (from parse_artworkdb)
        ithmb_folder_path: Path to the Artwork folder containing .ithmb files
        imgId: The image ID to find
        imgid_index: Optional pre-built index for O(1) lookup

    Returns:
        Tuple of (PIL.Image, dominant_color) or None if not found
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
        try:
            thumb_result = entry["Thumbnail Image"]["Thumbnail Image"]["result"]
        except KeyError:
            continue

        file_info = thumb_result.get("3", {})
        ithmb_filename = file_info.get(
            "File Name", f"F{thumb_result.get('correlationID')}_1.ithmb")
        if ithmb_filename.startswith(":"):
            ithmb_filename = ithmb_filename[1:]
        ithmb_path = os.path.join(ithmb_folder_path, ithmb_filename)

        required_keys = ["ithmbOffset", "imgSize", "image_format"]
        if not all(key in thumb_result for key in required_keys):
            continue

        img = generate_image(ithmb_path, thumb_result)

        if img is not None:
            dcol = getDominantColor(img)
            return img, dcol
    return None
