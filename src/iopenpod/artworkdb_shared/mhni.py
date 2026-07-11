"""MHNI field and ArtworkDB format-inference helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iopenpod.device import ITHMB_FORMAT_MAP
from iopenpod.device.artwork_presets import artwork_format_candidates

from .binary import read_i16, read_u16, read_u32


@dataclass(frozen=True)
class MhniFields:
    child_count: int
    format_id: int
    ithmb_offset: int
    image_size: int
    vertical_padding: int
    horizontal_padding: int
    image_height: int
    image_width: int
    unk1: int
    image_size_2: int

    @property
    def estimated_pixmap_height(self) -> int:
        return self.vertical_padding + self.image_height

    @property
    def estimated_pixmap_width(self) -> int:
        return self.horizontal_padding + self.image_width


def read_mhni_fields(data: bytes | bytearray, offset: int) -> MhniFields:
    return MhniFields(
        child_count=read_u32(data, offset + 12),
        format_id=read_u32(data, offset + 16),
        ithmb_offset=read_u32(data, offset + 20),
        image_size=read_u32(data, offset + 24),
        vertical_padding=read_i16(data, offset + 28),
        horizontal_padding=read_i16(data, offset + 30),
        image_height=read_u16(data, offset + 32),
        image_width=read_u16(data, offset + 34),
        unk1=read_u32(data, offset + 36),
        image_size_2=read_u32(data, offset + 40),
    )


def default_stride_pixels_for_format(fmt: Any, width: int) -> int:
    if fmt is None:
        return int(width)
    pixel_format = fmt.pixel_format
    if pixel_format in ("RGB565_LE", "RGB565_BE", "RGB565_BE_90", "RGB555_LE", "RGB555_BE", "UYVY"):
        return max(int(width), int(fmt.row_bytes // 2) if fmt.row_bytes else int(width))
    if pixel_format.startswith("REC_RGB555"):
        return max(int(width), int(fmt.row_bytes // 2) if fmt.row_bytes else int(width))
    return int(width)


def expected_size_for_format(
    fmt: Any,
    width: int | None = None,
    height: int | None = None,
    stride_pixels: int | None = None,
) -> int:
    if fmt is None:
        return 0

    visible_width = int(fmt.width if width is None else width)
    visible_height = int(fmt.height if height is None else height)
    pixel_format = fmt.pixel_format
    stride = int(stride_pixels) if stride_pixels is not None else default_stride_pixels_for_format(fmt, visible_width)

    if pixel_format in (
        "RGB565_LE",
        "RGB565_BE",
        "RGB565_BE_90",
        "RGB555_LE",
        "RGB555_BE",
        "UYVY",
    ) or pixel_format.startswith("REC_RGB555"):
        return stride * visible_height * 2
    if pixel_format == "I420_LE":
        even_w = visible_width & ~1
        even_h = visible_height & ~1
        return (even_w * even_h * 3) // 2
    if pixel_format == "JPEG":
        return 0
    return stride * visible_height * 2


def expected_size_bytes(
    format_id: int,
    width: int,
    height: int,
    stride_pixels: int | None = None,
    fmt_override: Any = None,
) -> int:
    fmt = fmt_override if fmt_override is not None else ITHMB_FORMAT_MAP.get(format_id)
    return expected_size_for_format(fmt, width, height, stride_pixels)


def _format_dict(fmt: Any, format_id: int, score: float | None = None) -> dict[str, Any]:
    result = {
        "height": fmt.height,
        "width": fmt.width,
        "format": fmt.pixel_format,
        "description": fmt.description,
        "format_id": format_id,
    }
    if score is not None:
        result["score"] = score
    return result


def _candidate_is_compatible(fmt: Any, fields: MhniFields) -> tuple[bool, int, int]:
    expected = expected_size_for_format(fmt)
    corr_exact = expected > 0 and expected == fields.image_size
    est_w = fields.estimated_pixmap_width
    est_h = fields.estimated_pixmap_height
    corr_close = (
        est_w > 0
        and est_h > 0
        and (
            (abs(est_w - fmt.width) <= 2 and abs(est_h - fmt.height) <= 2)
            or (abs(est_w - fmt.height) <= 2 and abs(est_h - fmt.width) <= 2)
        )
    )
    if expected == 0 and corr_close:
        corr_exact = True
    size_delta = abs(fields.image_size - expected) if expected > 0 else 0
    dim_delta = abs(est_w - fmt.width) + abs(est_h - fmt.height)
    return corr_exact or corr_close, size_delta, dim_delta


def infer_image_format(fields: MhniFields) -> dict[str, Any] | None:
    candidates = artwork_format_candidates()
    same_id_candidates = [
        candidate
        for candidate in candidates
        if candidate.format_id == fields.format_id
    ]

    if same_id_candidates:
        best_match = None
        best_score = float("inf")
        for candidate in same_id_candidates:
            compatible, size_delta, dim_delta = _candidate_is_compatible(candidate, fields)
            if not compatible:
                continue
            score = size_delta + dim_delta
            if score < best_score:
                best_match = candidate
                best_score = score
        if best_match is not None:
            return _format_dict(best_match, fields.format_id)

    mapped = ITHMB_FORMAT_MAP.get(fields.format_id)
    if mapped is not None:
        compatible, _size_delta, _dim_delta = _candidate_is_compatible(mapped, fields)
        if compatible:
            return _format_dict(mapped, fields.format_id)

    best_candidate = None
    best_score = float("inf")
    est_w = fields.estimated_pixmap_width
    est_h = fields.estimated_pixmap_height
    for candidate in candidates:
        dim_diff = abs(est_h - candidate.height) + abs(est_w - candidate.width)
        expected = expected_size_for_format(candidate)
        if expected > 0:
            size_delta = abs(fields.image_size - expected)
            score = dim_diff + (size_delta / max(1, candidate.row_bytes, candidate.width))
        else:
            score = dim_diff
        if score < best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is not None:
        return _format_dict(best_candidate, best_candidate.format_id, best_score)
    return None
