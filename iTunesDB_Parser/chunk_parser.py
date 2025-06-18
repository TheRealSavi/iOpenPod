import struct


def parse_chunk(data, offset) -> dict:
    chunk_type = data[offset:offset + 4].decode("utf-8")
    header_length = struct.unpack("<I", data[offset + 4:offset + 8])[0]
    chunk_length = struct.unpack("<I", data[offset + 8:offset + 12])[0]

    match chunk_type:
        case "mhbd":
            # database
            from .mhbd_parser import parse_db
            result = parse_db(data, offset, header_length, chunk_length)
            return result
        case "mhsd":
            # dataset
            from .mhsd_parser import parse_dataset
            result = parse_dataset(data, offset, header_length, chunk_length)
            return result
        case "mhlt":
            # track list
            from .mhlt_parser import parse_trackList
            result = parse_trackList(data, offset, header_length, chunk_length)
            return result
        case "mhit":
            # Track Item
            from .mhit_parser import parse_trackItem
            result = parse_trackItem(data, offset, header_length, chunk_length)
            return result
        case "mhlp":
            # playlist list
            return {}
        case "mhyp":
            # playlist
            return {}
        case "mhip":
            # playlist item
            return {}
        case "mhod":
            # data object
            from .mhod_parser import parse_mhod
            result = parse_mhod(data, offset, header_length, chunk_length)
            return result
        case "mhla":
            # Album List
            from .mhla_parser import parse_albumList
            result = parse_albumList(data, offset, header_length, chunk_length)
            return result
        case "mhia":
            # Album Item
            from .mhia_parser import parse_albumItem
            result = parse_albumItem(data, offset, header_length, chunk_length)
            return result
        case _:
            raise ValueError(f"Unknown chunk type: {chunk_type}")
