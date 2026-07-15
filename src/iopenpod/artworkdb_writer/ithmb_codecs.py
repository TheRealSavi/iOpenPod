"""Format-aware ithmb encode/decode helpers.

This module maps Apple correlation IDs to pixel codecs so callers can encode
and decode artwork without assuming every format is RGB565 little-endian.

Most IDs resolve through the global artwork registry. Known device-specific
conflicts are supplied by callers through ``fmt_override``. The format-specific
branches below are codec details; they should not be read as evidence that the
overall artwork ID model is device-specific or unreliable.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image

from iopenpod.artworkdb_shared.mhni import (
    default_stride_pixels_for_format,
)
from iopenpod.artworkdb_shared.mhni import (
    expected_size_bytes as shared_expected_size_bytes,
)
from iopenpod.device import ITHMB_FORMAT_MAP

from .artwork_types import EncodedFormatPayload

logger = logging.getLogger(__name__)


def _fmt(format_id: int, fmt_override=None):
    return fmt_override if fmt_override is not None else ITHMB_FORMAT_MAP.get(format_id)


def _rgb_image_from_array(rgb: np.ndarray) -> Image.Image:
    """Build an RGB Pillow image without Pillow's deprecated explicit mode arg."""
    return Image.fromarray(np.asarray(rgb, dtype=np.uint8))


def _encoded_payload(
    raw: bytes,
    width: int,
    height: int,
    stride_pixels: int,
    pixel_format: str,
) -> EncodedFormatPayload:
    return EncodedFormatPayload(
        data=raw,
        width=width,
        height=height,
        size=len(raw),
        stride_pixels=stride_pixels,
        pixel_format=pixel_format,
    )


def format_pixel_format(format_id: int, fmt_override=None) -> str:
    fmt = _fmt(format_id, fmt_override)
    return (fmt.pixel_format if fmt is not None else "UNKNOWN")


def format_dimensions(format_id: int, fallback_w: int, fallback_h: int, fmt_override=None) -> tuple[int, int]:
    fmt = _fmt(format_id, fmt_override)
    if fmt is None:
        return fallback_w, fallback_h
    return int(fmt.width), int(fmt.height)


def default_stride_pixels(format_id: int, width: int, fmt_override=None) -> int:
    fmt = _fmt(format_id, fmt_override)
    return default_stride_pixels_for_format(fmt, width)


def expected_size_bytes(
    format_id: int,
    width: int,
    height: int,
    stride_pixels: int | None = None,
    fmt_override=None,
) -> int:
    return shared_expected_size_bytes(
        format_id,
        width,
        height,
        stride_pixels=stride_pixels,
        fmt_override=fmt_override,
    )


def _rgb565_array_from_image(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"), dtype=np.uint32)
    r = (arr[:, :, 0] >> 3) & 0x1F
    g = (arr[:, :, 1] >> 2) & 0x3F
    b = (arr[:, :, 2] >> 3) & 0x1F
    return ((r << 11) | (g << 5) | b).astype(np.uint16)


def _rgb565_to_rgb(arr16: np.ndarray) -> np.ndarray:
    r = ((arr16 >> 11) & 0x1F).astype(np.uint8)
    g = ((arr16 >> 5) & 0x3F).astype(np.uint8)
    b = (arr16 & 0x1F).astype(np.uint8)
    return np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)), axis=2)


def _rgb555_array_from_image(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"), dtype=np.uint32)
    r = (arr[:, :, 0] >> 3) & 0x1F
    g = (arr[:, :, 1] >> 3) & 0x1F
    b = (arr[:, :, 2] >> 3) & 0x1F
    return ((r << 10) | (g << 5) | b).astype(np.uint16)


def _rgb555_to_rgb(arr16: np.ndarray) -> np.ndarray:
    r = ((arr16 >> 10) & 0x1F).astype(np.uint8)
    g = ((arr16 >> 5) & 0x1F).astype(np.uint8)
    b = (arr16 & 0x1F).astype(np.uint8)
    return np.stack(((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)), axis=2)


def _pad_packed_rows(arr16: np.ndarray, stride_pixels: int) -> np.ndarray:
    """Pad packed 16-bit rows to the on-disk stride, if needed."""
    stride = max(1, int(stride_pixels))
    height, width = arr16.shape[:2]
    if stride <= width:
        return arr16

    padded = np.zeros((height, stride), dtype=arr16.dtype)
    padded[:, :width] = arr16
    return padded


def _resolve_packed_geometry(
    pixel_bytes: bytes,
    width: int,
    height: int,
    hpad: int,
    vpad: int,
    format_id: int | None = None,
    fmt_override=None,
    *,
    require_even_width: bool = False,
) -> tuple[int, int]:
    """Infer packed raster geometry from visible size + MHNI padding.

    MHNI stores visible image dimensions and separate right/bottom padding.
    The payload size usually corresponds to (width + hpad) x (height + vpad).
    """
    px_count = len(pixel_bytes) // 2
    if px_count <= 0:
        return 0, 0

    vis_w = max(1, int(width))
    vis_h = max(1, int(height))
    pad_w = max(0, int(hpad))
    pad_h = max(0, int(vpad))

    candidates: list[tuple[int, int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(sw: int, sh: int, priority: int) -> None:
        sw = int(sw)
        sh = int(sh)
        if sw <= 0 or sh <= 0:
            return
        if require_even_width and (sw % 2) != 0:
            return
        if sw * sh != px_count:
            return
        key = (sw, sh)
        if key in seen:
            return
        seen.add(key)

        # Prefer candidates that contain the visible area and whose
        # overhang matches the MHNI hpad/vpad hints.
        overflow = max(0, vis_w - sw) + max(0, vis_h - sh)
        pad_delta = abs((sw - vis_w) - pad_w) + abs((sh - vis_h) - pad_h)
        candidates.append((priority, overflow, pad_delta, sw, sh))

    def add_neighborhood(base_w: int, base_h: int, priority: int) -> None:
        for dw in (-2, -1, 0, 1, 2):
            for dh in (-2, -1, 0, 1, 2):
                add(base_w + dw, base_h + dh, priority + abs(dw) + abs(dh))

    add(vis_w + pad_w, vis_h + pad_h, 0)
    add(vis_w, vis_h, 1)
    add_neighborhood(vis_w + pad_w, vis_h + pad_h, 2)
    add_neighborhood(vis_w, vis_h, 4)

    padded_h = vis_h + pad_h
    if padded_h > 0 and (px_count % padded_h) == 0:
        add(px_count // padded_h, padded_h, 2)

    if vis_h > 0 and (px_count % vis_h) == 0:
        add(px_count // vis_h, vis_h, 3)

    padded_w = vis_w + pad_w
    if padded_w > 0 and (px_count % padded_w) == 0:
        add(padded_w, px_count // padded_w, 4)

    if vis_w > 0 and (px_count % vis_w) == 0:
        add(vis_w, px_count // vis_w, 5)

    fmt = _fmt(int(format_id), fmt_override=fmt_override) if format_id is not None else None
    if fmt is not None:
        fmt_w = max(1, int(fmt.width))
        fmt_h = max(1, int(fmt.height))
        stride = max(1, int(fmt.row_bytes // 2) if int(fmt.row_bytes) > 0 else fmt_w)

        add(stride, fmt_h, 6)
        add(fmt_w, fmt_h, 6)

        if px_count % stride == 0:
            add(stride, px_count // stride, 7)
        if px_count % fmt_w == 0:
            add(fmt_w, px_count // fmt_w, 8)
        if px_count % fmt_h == 0:
            add(px_count // fmt_h, fmt_h, 9)

        # Generate additional candidates from row-byte alignment.
        # Work backwards from visible dimensions + alignment padding to find
        # candidates that match the actual payload byte count.
        # This handles cases where imagery is stored with row stride padding
        # for device-specific alignment requirements.
        #
        # Common alignment boundaries: 2, 4, 8, 16 pixels per row.
        # For each alignment, try the resulting (aligned_width, visible_height)
        # as a candidate if the byte math checks out.
        #
        # Use priority 1 to beat divisibility-based candidates (priority 3+).
        # This ensures alignment-based geometry takes precedence when available.
        for alignment in (2, 4, 8, 16):
            # Calculate what width would result from aligning vis_w to this boundary
            aligned_w = ((vis_w + alignment - 1) // alignment) * alignment

            # For RGB565/555 (2 bytes/pixel) and RGB888/UYVY (4 bytes/pixel),
            # check if this geometry produces the right byte count.
            for bpp in (2, 4):
                candidate_bytes = aligned_w * vis_h * bpp
                if candidate_bytes == len(pixel_bytes):
                    # This alignment produces exactly the payload size!
                    add(aligned_w, vis_h, 1)

                # Also try with format height in case visible height differs
                candidate_bytes_fmt_h = aligned_w * fmt_h * bpp
                if candidate_bytes_fmt_h == len(pixel_bytes):
                    add(aligned_w, fmt_h, 1)

    if not candidates:
        # Fallback: If no candidates found with exact payload size, try trimming
        # trailing bytes in small increments to find alignment padding.
        # This handles device alignment padding that's beyond the actual image data.
        # Only try trimming if payload is close to expected (within 256 bytes);
        # otherwise we risk accepting truly insufficient data.
        if fmt is not None and fmt.row_bytes > 0:
            expected_bytes = int(fmt.row_bytes) * max(1, int(fmt.height))
            # Only trim if payload is slightly larger than expected (not smaller)
            if len(pixel_bytes) > expected_bytes and (len(pixel_bytes) - expected_bytes) <= 256:
                # Try exact expected size
                trim_result = _resolve_packed_geometry(
                    pixel_bytes[:expected_bytes],
                    width,
                    height,
                    hpad,
                    vpad,
                    format_id=None,  # Don't recurse into format check
                    fmt_override=None,
                    require_even_width=require_even_width,
                )
                if trim_result != (0, 0):
                    return trim_result
        return 0, 0

    _priority, _overflow, _pad_delta, stored_w, stored_h = min(candidates)
    return stored_w, stored_h


def _line_discontinuity_ratio(rgb: np.ndarray) -> float:
    if rgb.shape[0] < 3:
        return 1.0
    arr = rgb.astype(np.int16, copy=False)
    adjacent = np.abs(np.diff(arr, axis=0))
    avg_adj = float(np.mean(adjacent))
    if avg_adj <= 0.0:
        return 1.0
    seam = rgb.shape[0] // 2
    seam_jump = float(np.mean(np.abs(arr[seam - 1] - arr[seam])))
    return seam_jump / avg_adj


def _detail_score(rgb: np.ndarray) -> float:
    arr = rgb.astype(np.int16, copy=False)
    if arr.shape[0] < 2 or arr.shape[1] < 2:
        return 0.0
    dx = np.diff(arr, axis=1)
    dy = np.diff(arr, axis=0)
    return float(np.var(dx) + np.var(dy))


def _weave_fields(top: np.ndarray, bottom: np.ndarray, *, swap: bool = False) -> np.ndarray:
    h2, w, _ = top.shape
    out = np.empty((h2 * 2, w, 3), dtype=np.uint8)
    if swap:
        out[0::2] = bottom
        out[1::2] = top
    else:
        out[0::2] = top
        out[1::2] = bottom
    return out


def _half_similarity(rgb: np.ndarray) -> tuple[float, float]:
    h = rgb.shape[0]
    if h < 4 or (h % 2) != 0:
        return 999.0, 999.0
    top = rgb[: h // 2].astype(np.int16, copy=False)
    bottom = rgb[h // 2:].astype(np.int16, copy=False)
    diff = np.abs(top - bottom)
    return float(np.mean(diff)), float(np.percentile(diff, 95))


def _fix_1019_layout(rgb: np.ndarray, format_id: int) -> np.ndarray:
    """Resolve known 1019 UYVY layout artifacts deterministically.

    This is a localized codec repair for one odd format. Candidate layouts are
    scored by seam continuity first, then detail level.
    """
    if int(format_id) != 1019:
        return rgb

    h, w = rgb.shape[:2]
    if h < 120 or (h % 2) != 0:
        return rgb

    half = h // 2
    top = rgb[:half]
    bottom = rgb[half:]

    # Fast path: obvious stacked duplicate.
    mad, p95 = _half_similarity(rgb)
    if mad < 8.0 and p95 < 30.0:
        chosen = top if _detail_score(top) >= _detail_score(bottom) else bottom
        restored = _rgb_image_from_array(chosen).resize((w, h), Image.Resampling.BILINEAR)
        return np.array(restored, dtype=np.uint8)

    top_scaled = np.array(
        _rgb_image_from_array(top).resize((w, h), Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )
    bottom_scaled = np.array(
        _rgb_image_from_array(bottom).resize((w, h), Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )
    candidates = [
        rgb,
        _weave_fields(top, bottom, swap=False),
        _weave_fields(top, bottom, swap=True),
        top_scaled,
        bottom_scaled,
    ]

    def score(img: np.ndarray) -> tuple[float, float, float]:
        m, p = _half_similarity(img)
        stacked_penalty = 1.0 if (m < 8.0 and p < 30.0) else 0.0
        return (stacked_penalty, _line_discontinuity_ratio(img), -_detail_score(img))

    return min(candidates, key=score)


def _crop_visible_region(
    rgb: np.ndarray,
    width: int,
    height: int,
    hpad: int,
    vpad: int,
    format_id: int,
    fmt_override=None,
) -> np.ndarray:
    """Crop decoded pixels to the intended visible image rectangle.

    Most formats use top-left anchored crops (width x height). A small number
    of photo-oriented formats appear to store centered pad margins, so that
    quirk stays localized here in the decoder instead of shaping writer policy.
    """
    stored_h, stored_w = rgb.shape[:2]
    visible_w = max(1, min(stored_w, int(width)))
    visible_h = max(1, min(stored_h, int(height)))
    crop_x = 0
    crop_y = 0

    fmt = _fmt(int(format_id), fmt_override=fmt_override)
    role = (fmt.role if fmt is not None else "")
    if (hpad > 0 or vpad > 0) and role.startswith("photo"):
        # Empirical iPod photo DB behavior (e.g. 1007/1015/1024/1093):
        # stored ~= (width + hpad, height + vpad), with pad on both sides.
        match_w = abs(stored_w - (int(width) + int(hpad))) <= 2
        match_h = abs(stored_h - (int(height) + int(vpad))) <= 2
        if match_w or match_h:
            crop_x = min(max(0, int(hpad)), max(0, stored_w - 1))
            crop_y = min(max(0, int(vpad)), max(0, stored_h - 1))
            padded_w = int(width) - int(hpad)
            padded_h = int(height) - int(vpad)
            if padded_w > 0:
                visible_w = min(stored_w - crop_x, padded_w)
            else:
                visible_w = min(stored_w - crop_x, visible_w)
            if padded_h > 0:
                visible_h = min(stored_h - crop_y, padded_h)
            else:
                visible_h = min(stored_h - crop_y, visible_h)

    end_x = max(crop_x + 1, crop_x + visible_w)
    end_y = max(crop_y + 1, crop_y + visible_h)
    return rgb[crop_y:end_y, crop_x:end_x, :]


def encode_image_for_format(
    source_img: Image.Image,
    format_id: int,
    target_width: int | None = None,
    target_height: int | None = None,
    fmt_override=None,
) -> EncodedFormatPayload:
    pf = format_pixel_format(format_id, fmt_override=fmt_override)
    w, h = format_dimensions(
        format_id,
        int(target_width or source_img.width),
        int(target_height or source_img.height),
        fmt_override=fmt_override,
    )
    stride = default_stride_pixels(format_id, w, fmt_override=fmt_override)

    base = source_img.convert("RGB").resize((w, h), Image.Resampling.LANCZOS)

    if pf == "RGB565_BE_90":
        rotated = base.transpose(Image.Transpose.ROTATE_270)
        arr16 = _rgb565_array_from_image(rotated)
        arr16 = _pad_packed_rows(arr16, stride)
        raw = arr16.astype(">u2").tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "RGB565_BE":
        arr16 = _rgb565_array_from_image(base)
        arr16 = _pad_packed_rows(arr16, stride)
        raw = arr16.astype(">u2").tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "RGB555_BE":
        arr16 = _rgb555_array_from_image(base)
        arr16 = _pad_packed_rows(arr16, stride)
        raw = arr16.astype(">u2").tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf in ("RGB555_LE", "REC_RGB555_LE"):
        arr16 = _rgb555_array_from_image(base)
        arr16 = _pad_packed_rows(arr16, stride)
        raw = arr16.astype("<u2").tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "JPEG":
        out = io.BytesIO()
        # Use fixed quality to keep writes deterministic enough for debugging.
        base.save(out, format="JPEG", quality=92, optimize=False)
        raw = out.getvalue()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "UYVY":
        if w % 2 != 0:
            w -= 1
            base = base.resize((w, h), Image.Resampling.LANCZOS)

        arr = np.array(base, dtype=np.float32)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        y = np.clip(0.257 * r + 0.504 * g + 0.098 * b + 16, 0, 255).astype(np.uint8)
        u = np.clip(-0.148 * r - 0.291 * g + 0.439 * b + 128, 0, 255)
        v = np.clip(0.439 * r - 0.368 * g - 0.071 * b + 128, 0, 255)
        u2 = ((u[:, 0::2] + u[:, 1::2]) * 0.5).astype(np.uint8)
        v2 = ((v[:, 0::2] + v[:, 1::2]) * 0.5).astype(np.uint8)
        packed = np.empty((h, w * 2), dtype=np.uint8)
        packed[:, 0::4] = u2
        packed[:, 1::4] = y[:, 0::2]
        packed[:, 2::4] = v2
        packed[:, 3::4] = y[:, 1::2]
        raw = packed.tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "I420_LE":
        w_even = w & ~1
        h_even = h & ~1
        if w_even != w or h_even != h:
            w, h = w_even, h_even
            base = base.resize((w, h), Image.Resampling.LANCZOS)

        arr = np.array(base, dtype=np.float32)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        y = np.clip(0.257 * r + 0.504 * g + 0.098 * b + 16, 0, 255).astype(np.uint8)
        u = np.clip(-0.148 * r - 0.291 * g + 0.439 * b + 128, 0, 255)
        v = np.clip(0.439 * r - 0.368 * g - 0.071 * b + 128, 0, 255)
        u420 = ((u[0::2, 0::2] + u[0::2, 1::2] + u[1::2, 0::2] + u[1::2, 1::2]) * 0.25).astype(np.uint8)
        v420 = ((v[0::2, 0::2] + v[0::2, 1::2] + v[1::2, 0::2] + v[1::2, 1::2]) * 0.25).astype(np.uint8)
        raw = y.tobytes() + u420.tobytes() + v420.tobytes()
        return _encoded_payload(raw, w, h, stride, pf)

    if pf == "UNKNOWN":
        raise ValueError(f"Unsupported unknown pixel format for format_id={format_id}")

    # Default and common path: RGB565 little-endian.
    arr16 = _rgb565_array_from_image(base)
    arr16 = _pad_packed_rows(arr16, stride)
    raw = arr16.astype("<u2").tobytes()
    return _encoded_payload(raw, w, h, stride, "RGB565_LE")


def decode_pixels_for_format(
    format_id: int,
    pixel_bytes: bytes,
    width: int,
    height: int,
    hpad: int = 0,
    vpad: int = 0,
    fmt_override=None,
) -> Image.Image | None:
    pf = format_pixel_format(format_id, fmt_override=fmt_override)
    width = max(1, int(width))
    height = max(1, int(height))
    hpad = max(0, int(hpad))
    vpad = max(0, int(vpad))

    if pf in ("RGB565_LE", "RGB565_BE", "RGB565_BE_90"):
        stored_w, stored_h = _resolve_packed_geometry(
            pixel_bytes,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
        )
        if stored_w <= 0 or stored_h <= 0:
            return None

        dtype = "<u2" if pf == "RGB565_LE" else ">u2"
        needed = stored_w * stored_h * 2
        if len(pixel_bytes) < needed:
            return None

        # Allow trailing padding bytes (device alignment may add extra bytes)
        if len(pixel_bytes) > needed:
            excess = len(pixel_bytes) - needed
            if excess > needed * 0.1:  # Warn if >10% excess
                logger.warning(
                    f"RGB565 {stored_w}x{stored_h}: payload has {excess} extra bytes "
                    f"({excess / needed * 100:.1f}% padding), truncating"
                )

        arr = np.frombuffer(pixel_bytes[:needed], dtype=dtype)
        if arr.size != stored_w * stored_h:
            return None
        arr = arr.reshape((stored_h, stored_w))

        rgb = _rgb565_to_rgb(arr)
        if pf == "RGB565_BE_90":
            rgb = np.rot90(rgb, k=1)

        rgb = _crop_visible_region(
            rgb,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
        )
        return _rgb_image_from_array(rgb)

    if pf in ("RGB555_LE", "RGB555_BE", "REC_RGB555_LE"):
        stored_w, stored_h = _resolve_packed_geometry(
            pixel_bytes,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
        )
        if stored_w <= 0 or stored_h <= 0:
            return None

        dtype = "<u2" if pf != "RGB555_BE" else ">u2"
        needed = stored_w * stored_h * 2
        if len(pixel_bytes) < needed:
            return None

        # Allow trailing padding bytes (device alignment may add extra bytes)
        if len(pixel_bytes) > needed:
            excess = len(pixel_bytes) - needed
            if excess > needed * 0.1:  # Warn if >10% excess
                logger.warning(
                    f"RGB555 {stored_w}x{stored_h}: payload has {excess} extra bytes "
                    f"({excess / needed * 100:.1f}% padding), truncating"
                )

        arr = np.frombuffer(pixel_bytes[:needed], dtype=dtype)
        if arr.size != stored_w * stored_h:
            return None
        arr = arr.reshape((stored_h, stored_w))

        rgb = _rgb555_to_rgb(arr)
        rgb = _crop_visible_region(
            rgb,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
        )
        return _rgb_image_from_array(rgb)

    if pf == "UYVY":
        stored_w, stored_h = _resolve_packed_geometry(
            pixel_bytes,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
            require_even_width=True,
        )
        if stored_w <= 0 or stored_h <= 0:
            return None
        needed = stored_w * stored_h * 2
        if len(pixel_bytes) < needed:
            return None

        # Allow trailing padding bytes (device alignment may add extra bytes)
        if len(pixel_bytes) > needed:
            excess = len(pixel_bytes) - needed
            if excess > needed * 0.1:  # Warn if >10% excess
                logger.warning(
                    f"UYVY {stored_w}x{stored_h}: payload has {excess} extra bytes "
                    f"({excess / needed * 100:.1f}% padding), truncating"
                )

        p = np.frombuffer(pixel_bytes[:needed], dtype=np.uint8).reshape((stored_h, stored_w * 2))
        u = p[:, 0::4].astype(np.float32)
        y0 = p[:, 1::4].astype(np.float32)
        v = p[:, 2::4].astype(np.float32)
        y1 = p[:, 3::4].astype(np.float32)

        y = np.empty((stored_h, stored_w), dtype=np.float32)
        y[:, 0::2] = y0
        y[:, 1::2] = y1
        uu = np.repeat(u, 2, axis=1)
        vv = np.repeat(v, 2, axis=1)

        c = y - 16.0
        d = uu - 128.0
        e = vv - 128.0
        r = np.clip((298.082 * c + 408.583 * e) / 256.0, 0, 255).astype(np.uint8)
        g = np.clip((298.082 * c - 100.291 * d - 208.120 * e) / 256.0, 0, 255).astype(np.uint8)
        b = np.clip((298.082 * c + 516.412 * d) / 256.0, 0, 255).astype(np.uint8)
        rgb = np.stack((r, g, b), axis=2)
        rgb = _crop_visible_region(
            rgb,
            width,
            height,
            hpad,
            vpad,
            format_id,
            fmt_override=fmt_override,
        )
        rgb = _fix_1019_layout(rgb, format_id)
        return _rgb_image_from_array(rgb)

    if pf == "I420_LE":
        width &= ~1
        height &= ~1
        y_size = width * height
        uv_size = (width // 2) * (height // 2)
        needed = y_size + uv_size + uv_size

        if len(pixel_bytes) < needed:
            return None

        # Allow trailing padding bytes (device alignment may add extra bytes)
        if len(pixel_bytes) > needed:
            excess = len(pixel_bytes) - needed
            if excess > needed * 0.1:  # Warn if >10% excess
                logger.debug(
                    f"I420_LE {width}x{height}: payload has {excess} extra bytes "
                    f"({excess / needed * 100:.1f}% padding), truncating"
                )

        y = np.frombuffer(pixel_bytes[:y_size], dtype=np.uint8).reshape((height, width)).astype(np.float32)
        u = np.frombuffer(pixel_bytes[y_size:y_size + uv_size], dtype=np.uint8).reshape((height // 2, width // 2)).astype(np.float32)
        v = np.frombuffer(pixel_bytes[y_size + uv_size:y_size + uv_size + uv_size], dtype=np.uint8).reshape((height // 2, width // 2)).astype(np.float32)
        uu = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)
        vv = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)

        c = y - 16.0
        d = uu - 128.0
        e = vv - 128.0
        r = np.clip((298.082 * c + 408.583 * e) / 256.0, 0, 255).astype(np.uint8)
        g = np.clip((298.082 * c - 100.291 * d - 208.120 * e) / 256.0, 0, 255).astype(np.uint8)
        b = np.clip((298.082 * c + 516.412 * d) / 256.0, 0, 255).astype(np.uint8)
        rgb = np.stack((r, g, b), axis=2)
        return _rgb_image_from_array(rgb)

    if pf == "JPEG":
        try:
            return Image.open(io.BytesIO(pixel_bytes)).convert("RGB")
        except Exception:
            return None

    return None
