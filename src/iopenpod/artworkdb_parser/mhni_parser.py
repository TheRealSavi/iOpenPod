from iopenpod.artworkdb_shared.mhni import infer_image_format, read_mhni_fields


def parse_mhni(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    imageName = {}
    fields = read_mhni_fields(data, offset)

    childCount = fields.child_count
    # a type 3 mhod

    imageName["correlationID"] = fields.format_id
    # maps to mhif correlationID. generates name of the file
    # Also serves as the format_id to identify image format (libgpod approach)

    imageName["ithmbOffset"] = fields.ithmb_offset
    # where the image data starts in the .ithmb file

    imageName["imgSize"] = fields.image_size
    # in bytes

    imageName["verticalPadding"] = fields.vertical_padding
    imageName["horizontalPadding"] = fields.horizontal_padding

    imageName["imageHeight"] = fields.image_height
    imageName["imageWidth"] = fields.image_width

    imageName["unk1"] = fields.unk1
    # always 0

    imageName["imgSize2"] = fields.image_size_2
    # Same as imgSize, seen after iTunes 7.4

    # Estimate pixmap dimensions (for debugging/fallback)
    imageName["estimatedPixmapHeight"] = fields.estimated_pixmap_height
    imageName["estimatedPixmapWidth"] = fields.estimated_pixmap_width
    imageName["image_format"] = infer_image_format(fields)

    # parse children
    next_offset = offset + header_length
    for _i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        imageName[response["result"]["mhodType"]] = response["result"]

    return {"nextOffset": offset + chunk_length, "result": imageName}
