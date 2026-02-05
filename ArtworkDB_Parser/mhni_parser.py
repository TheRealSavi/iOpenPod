import struct

# Format ID (correlationID) to format mapping from libgpod itdb_device.c
# This is the authoritative way to identify image formats - by format_id, not by size guessing
# Format: format_id: (height, width, pixel format, description)
FORMAT_ID_MAP = {
    # iPod Photo/Color cover art
    1016: (140, 140, "RGB565_LE", "iPod Photo album art large"),
    1017: (56, 56, "RGB565_LE", "iPod Photo album art small"),
    # iPod Photo photos
    1009: (42, 30, "RGB565_LE", "iPod Photo list thumbnail"),
    1013: (220, 176, "RGB565_BE_90", "iPod Photo full screen (rotated)"),
    1015: (130, 88, "RGB565_LE", "iPod Photo/Video preview"),
    1019: (720, 480, "UYVY", "iPod Photo/Video NTSC TV output"),
    # iPod Nano (1G-2G) cover art
    1027: (100, 100, "RGB565_LE", "iPod Nano album art large"),
    1031: (42, 42, "RGB565_LE", "iPod Nano album art small"),
    # iPod Nano photos
    1023: (176, 132, "RGB565_BE", "iPod Nano full screen"),
    1032: (42, 37, "RGB565_LE", "iPod Nano list thumbnail"),
    # iPod Video cover art
    1028: (100, 100, "RGB565_LE", "iPod Video album art small"),
    1029: (200, 200, "RGB565_LE", "iPod Video album art large"),
    # iPod Video photos
    1024: (320, 240, "RGB565_LE", "iPod Video full screen"),
    1036: (50, 41, "RGB565_LE", "iPod Video list thumbnail"),
    # iPod Classic (all gens) & Nano 3G cover art
    1055: (128, 128, "RGB565_LE", "iPod Classic album art medium"),
    1056: (128, 128, "RGB565_LE", "iPod Classic album art (alt)"),
    1060: (320, 320, "RGB565_LE", "iPod Classic album art large"),
    1061: (56, 56, "RGB565_LE", "iPod Classic album art small"),
    1068: (128, 128, "RGB565_LE", "iPod Classic album art medium (alt)"),
    # iPod Classic photos
    1066: (64, 64, "RGB565_LE", "iPod Classic photo thumbnail"),
    1067: (720, 480, "I420_LE", "iPod Classic TV output (YUV)"),
    # iPod Nano 4G cover art
    1071: (240, 240, "RGB565_LE", "iPod Nano 4G album art large"),
    1074: (50, 50, "RGB565_LE", "iPod Nano 4G album art tiny"),
    1078: (80, 80, "RGB565_LE", "iPod Nano 4G album art small"),
    1084: (240, 240, "RGB565_LE", "iPod Nano 4G album art (alt)"),
    # iPod Nano 5G cover art
    1073: (240, 240, "RGB565_LE", "iPod Nano 5G album art large"),
    # iPod Nano 4G/5G photos
    1079: (80, 80, "RGB565_LE", "iPod Nano 4G/5G photo thumbnail"),
    1083: (240, 320, "RGB565_LE", "iPod Nano 4G photo full screen"),
    1087: (384, 384, "RGB565_LE", "iPod Nano 5G photo large"),
}


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

    # Fallback: known image sizes for when format_id is unknown
    # Format: image size: (height, width, pixel format, description)
    known_sizes = {
        691200: (480, 720, "UYVY", "PhotoPod and VideoPod NTSC image"),
        153600: (240, 320, "RGB565_LE", "VideoPod full screen"),
        80000: (200, 200, "RGB565_LE", "VideoPod album art big version"),
        77440: (176, 220, "RGB565_BE_90", "PhotoPod full screen"),
        46464: (132, 176, "RGB565_BE", "Nano full screen"),
        39200: (140, 140, "RGB565_LE", "PhotoPod album art big version"),
        22880: (88, 130, "RGB565_LE", "PhotoPod and VideoPod video preview"),
        20000: (100, 100, "RGB565_LE", "VideoPod album art small version, Nano album art big version"),
        6272: (56, 56, "RGB565_LE", "PhotoPod album art small version"),
        4100: (41, 50, "RGB565_LE", "VideoPod list thumbnail"),
        3528: (42, 42, "RGB565_LE", "Nano album art small version"),
        3108: (37, 42, "RGB565_LE", "Nano list thumbnail"),
        2520: (30, 42, "RGB565_LE", "PhotoPod list thumbnail"),
    }

    image_format = None

    # PREFERRED: Use format_id (correlationID) lookup - this is how libgpod does it
    format_id = imageName["correlationID"]
    if format_id in FORMAT_ID_MAP:
        fmt_info = FORMAT_ID_MAP[format_id]
        image_format = {
            "height": fmt_info[0],
            "width": fmt_info[1],
            "format": fmt_info[2],
            "description": fmt_info[3],
            "format_id": format_id,
        }
    else:
        # FALLBACK: Match by size/dimensions (less reliable)
        # Allow a total pixel difference (height diff + width diff) of up to 6 pixels
        tolerance_pixels = 6
        best_candidate = None
        best_pixel_diff = float('inf')

        # Compare computed dimensions with the known candidates
        for size, props in known_sizes.items():
            candidate_height, candidate_width, candidate_format, candidate_desc = props
            diff_pixels = abs(imageName["estimatedPixmapHeight"] - candidate_height) + abs(
                imageName["estimatedPixmapWidth"] - candidate_width)
            if diff_pixels < best_pixel_diff:
                best_pixel_diff = diff_pixels
                best_candidate = props

        if best_candidate is not None and best_pixel_diff <= tolerance_pixels:
            image_format = {
                "height": best_candidate[0],
                "width": best_candidate[1],
                "format": best_candidate[2],
                "description": best_candidate[3],
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
