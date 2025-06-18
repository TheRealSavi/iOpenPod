import struct


def parse_mhni(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    imageName = {}

    childCount = struct.unpack("<I", data[offset + 12: offset + 16])[0]
    # a type 3 mhod

    imageName["correlationID"] = struct.unpack(
        "<I", data[offset + 16: offset + 20])[0]
    # maps to mhif correlationID. generates name of the file

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

    # Generate filename from correlation ID
    filename = f"F{imageName["correlationID"]}_1.ithmb"

    # Estimate pixmap dimensions
    imageName["estimatedPixmapHeight"] = (
        imageName["verticalPadding"] + imageName["imageHeight"]
    )
    imageName["estimatedPixmapWidth"] = (
        imageName["horizontalPadding"] + imageName["imageWidth"]
    )

   # Define known image sizes and their corresponding dimensions.
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
    # Allow a total pixel difference (height diff + width diff) of up to 3 pixels
    tolerance_pixels = 3

    best_candidate = None
    best_pixel_diff = float('inf')

    # Compare computed dimensions with the known candidates
    for size, props in known_sizes.items():
        candidate_height, candidate_width, candidate_format, candidate_desc = props
        diff_pixels = abs(imageName["estimatedPixmapHeight"] - candidate_height) + abs(
            imageName["estimatedPixmapWidth"] - candidate_width)
        print(
            f"Candidate {candidate_height}x{candidate_width} (size {size}) - diff: {diff_pixels} pixels")
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
        print(
            f"Selected image format based on computed dimensions with pixel diff {best_pixel_diff}")
    else:
        print(
            f"No matching image format found for computed dimensions: {imageName["estimatedPixmapHeight"]}x{imageName["estimatedPixmapWidth"]}")

    imageName["image_format"] = image_format

    # parse children
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        imageName[response["result"]["mhodType"]] = response["result"]

    return {"nextOffset": offset + chunk_length, "result": imageName}
