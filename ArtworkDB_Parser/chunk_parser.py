import struct


def parse_chunk(data, offset) -> dict:
    chunk_type = data[offset: offset + 4].decode("utf-8")
    header_length = struct.unpack("<I", data[offset + 4: offset + 8])[0]
    chunk_length = struct.unpack("<I", data[offset + 8: offset + 12])[0]

    match chunk_type:
        case "mhfd":
            # Data file
            from .mhfd_parser import parse_mhfd

            result = parse_mhfd(data, offset, header_length, chunk_length)
            return result
        case "mhsd":
            # Data Set
            from .mhsd_parser import parse_mhsd

            result = parse_mhsd(data, offset, header_length, chunk_length)
            return result
        case "mhli":
            # Image List
            from .mhli_parser import parse_mhli

            result = parse_mhli(data, offset, header_length, chunk_length)
            return result
        case "mhii":
            # Image Item
            from .mhii_parser import parse_imageItem

            result = parse_imageItem(data, offset, header_length, chunk_length)
            return result
        case "mhni":
            # Image Name
            from .mhni_parser import parse_mhni

            result = parse_mhni(data, offset, header_length, chunk_length)
            return result
        case "mhla":
            # Photo Album List
            return
        case "mhba":
            # Photo Album
            return
        case "mhia":
            # Photo Album Item
            return
        case "mhlf":
            # File List
            return
        case "mhif":
            # File Item
            return
        case "mhod":
            # Data Object
            from .mhod_parser import parse_mhod

            result = parse_mhod(data, offset, header_length, chunk_length)
            return result
        case "mhaf":
            # Unknown
            return {}
        case _:
            raise ValueError(f"Unknown chunk type: {chunk_type}")
