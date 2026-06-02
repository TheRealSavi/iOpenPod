import struct

from ipod_device import ITHMB_FORMAT_MAP
from ipod_device.artwork_presets import artwork_format_candidates


def _expected_img_size_bytes(candidate) -> int:
    pf = candidate.pixel_format
    if pf in (
        "RGB565_LE",
        "RGB565_BE",
        "RGB565_BE_90",
        "UYVY",
        "RGB555_LE",
        "RGB555_BE",
    ):
        return candidate.row_bytes * candidate.height
    if pf.startswith("REC_RGB555"):
        return candidate.row_bytes * candidate.height
    if pf == "I420_LE":
        w = candidate.width & ~1
        h = candidate.height & ~1
        return (w * h * 3) // 2
    if pf == "JPEG":
        return 0
    return 0


def parse_mhni(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    imageName = {}

    childCount = struct.unpack("<I", data[offset + 12: offset + 16])[0]
    # a type 3 mhod

    imageName["correlationID"] = struct.unpack(
        "<I", data[offset + 16: offset + 20])[0]
    # maps to mhif correlationID. generates name of the file
    # Also serves as the format_id to identify image format (libgpod approach)

    imageName["ithmbOffset"] = struct.unpack(
        "<I", data[offset + 20: offset + 24])[0]
    # where the image data starts in the .ithmb file

    imageName["imgSize"] = struct.unpack(
        "<I", data[offset + 24: offset + 28])[0]
    # in bytes

    imageName["verticalPadding"] = struct.unpack("<h", data[offset + 28: offset + 30])[
        0
    ]
    imageName["horizontalPadding"] = struct.unpack(
        "<h", data[offset + 30: offset + 32]
    )[0]

    imageName["imageHeight"] = struct.unpack(
        "<H", data[offset + 32: offset + 34])[0]
    imageName["imageWidth"] = struct.unpack(
        "<H", data[offset + 34: offset + 36])[0]

    imageName["unk1"] = struct.unpack("<I", data[offset + 36: offset + 40])[0]
    # always 0

    imageName["imgSize2"] = struct.unpack(
        "<I", data[offset + 40: offset + 44])[0]
    # Same as imgSize, seen after iTunes 7.4

    # Estimate pixmap dimensions (for debugging/fallback)
    imageName["estimatedPixmapHeight"] = (
        imageName["verticalPadding"] + imageName["imageHeight"]
    )
    imageName["estimatedPixmapWidth"] = (
        imageName["horizontalPadding"] + imageName["imageWidth"]
    )

    image_format = None

    format_id = imageName["correlationID"]
    candidates = artwork_format_candidates()
    same_id_candidates = [
        candidate
        for candidate in candidates
        if candidate.format_id == format_id
    ]
    est_w = imageName["estimatedPixmapWidth"]
    est_h = imageName["estimatedPixmapHeight"]
    img_size = imageName["imgSize"]

    # Prefer correlationID mapping only when it is plausibly compatible with
    # observed MHNI geometry or payload size. Some legacy/corrupt databases
    # carry mismatched correlation IDs (e.g. 140x140 metadata for ~57x58 data).
    if same_id_candidates:
        best_match = None
        best_match_score = float("inf")
        for af in same_id_candidates:
            expected = _expected_img_size_bytes(af)
            corr_exact = expected > 0 and expected == img_size
            corr_close = (
                est_w > 0
                and est_h > 0
                and (
                    (abs(est_w - af.width) <= 2 and abs(est_h - af.height) <= 2)
                    or (abs(est_w - af.height) <= 2 and abs(est_h - af.width) <= 2)
                )
            )
            # For variable-sized payloads (e.g. JPEG), trust correlation ID + geometry.
            if expected == 0 and corr_close:
                corr_exact = True
            if not (corr_exact or corr_close):
                continue

            size_delta = abs(img_size - expected) if expected > 0 else 0
            dim_delta = abs(est_w - af.width) + abs(est_h - af.height)
            score = size_delta + dim_delta
            if score < best_match_score:
                best_match = af
                best_match_score = score

        if best_match is not None:
            image_format = {
                "height": best_match.height,
                "width": best_match.width,
                "format": best_match.pixel_format,
                "description": best_match.description,
                "format_id": format_id,
            }

    if image_format is None:
        af = ITHMB_FORMAT_MAP.get(format_id)
    else:
        af = None

    if image_format is None and af is not None:
        expected = _expected_img_size_bytes(af)
        corr_exact = expected > 0 and expected == img_size
        corr_close = (
            est_w > 0
            and est_h > 0
            and (
                (abs(est_w - af.width) <= 2 and abs(est_h - af.height) <= 2)
                or (abs(est_w - af.height) <= 2 and abs(est_h - af.width) <= 2)
            )
        )
        # For variable-sized payloads (e.g. JPEG), trust correlation ID + geometry.
        if expected == 0 and corr_close:
            corr_exact = True
        if corr_exact or corr_close:
            image_format = {
                "height": af.height,
                "width": af.width,
                "format": af.pixel_format,
                "description": af.description,
                "format_id": format_id,
            }

    if image_format is None:
        # Fallback: choose the candidate that best matches observed geometry
        # and payload pixel count.
        best_candidate = None
        best_score = float("inf")

        for candidate in candidates:
            dim_diff = abs(est_h - candidate.height) + abs(est_w - candidate.width)
            expected = _expected_img_size_bytes(candidate)
            if expected > 0:
                size_delta = abs(img_size - expected)
                score = dim_diff + (
                    size_delta / max(1, candidate.row_bytes, candidate.width)
                )
            else:
                score = dim_diff
            if score < best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is not None:
            image_format = {
                "height": best_candidate.height,
                "width": best_candidate.width,
                "format": best_candidate.pixel_format,
                "description": best_candidate.description,
                "format_id": best_candidate.format_id,
                "score": best_score,
            }

    imageName["image_format"] = image_format

    # parse children
    next_offset = offset + header_length
    for _i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        imageName[response["result"]["mhodType"]] = response["result"]

    return {"nextOffset": offset + chunk_length, "result": imageName}
