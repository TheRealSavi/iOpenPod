import struct

from ipod_models import ITHMB_FORMAT_MAP


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

    # PREFERRED: Use format_id (correlationID) lookup — single source of
    # truth is ipod_models.ITHMB_FORMAT_MAP (replaces local FORMAT_ID_MAP).
    format_id = imageName["correlationID"]
    af = ITHMB_FORMAT_MAP.get(format_id)
    if af is not None:
        image_format = {
            "height": af.height,
            "width": af.width,
            "format": af.pixel_format,
            "description": af.description,
            "format_id": format_id,
        }
    else:
        # FALLBACK: Match by estimated dimensions (less reliable).
        # Iterate all known formats and pick the closest match within
        # a 6-pixel tolerance (sum of height + width difference).
        tolerance_pixels = 6
        best_candidate = None
        best_pixel_diff = float('inf')

        for candidate in ITHMB_FORMAT_MAP.values():
            diff_pixels = (
                abs(imageName["estimatedPixmapHeight"] - candidate.height)
                + abs(imageName["estimatedPixmapWidth"] - candidate.width)
            )
            if diff_pixels < best_pixel_diff:
                best_pixel_diff = diff_pixels
                best_candidate = candidate

        if best_candidate is not None and best_pixel_diff <= tolerance_pixels:
            image_format = {
                "height": best_candidate.height,
                "width": best_candidate.width,
                "format": best_candidate.pixel_format,
                "description": best_candidate.description,
                "pixel_diff": best_pixel_diff,
            }

    imageName["image_format"] = image_format

    # parse children
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        imageName[response["result"]["mhodType"]] = response["result"]

    return {"nextOffset": offset + chunk_length, "result": imageName}
