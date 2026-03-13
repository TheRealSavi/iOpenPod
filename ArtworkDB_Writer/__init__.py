"""
ArtworkDB Writer for iPod Classic/Nano.

Writes ArtworkDB binary files and .ithmb image files from PC music
file embedded album art.

Usage:
    from ArtworkDB_Writer import write_artworkdb

    # pc_file_paths maps track db_id → PC source file path
    db_id_to_art = write_artworkdb(
        ipod_path="/media/ipod",
        tracks=track_list,
        pc_file_paths={12345: "/home/user/Music/song.mp3", ...},
    )

    # Then set mhiiLink and artworkSize on each track in iTunesDB
    for track in tracks:
        art_info = db_id_to_art.get(track.db_id)
        if art_info:
            img_id, src_size = art_info
            track.mhii_link = img_id
            track.artwork_size = src_size
"""

from .artwork_writer import write_artworkdb, ArtworkEntry
from .art_extractor import extract_art, art_hash
from .rgb565 import (
    convert_art_for_ipod,
    image_from_bytes,
    rgb888_to_rgb565,
    get_artwork_formats,
    IPOD_CLASSIC_FORMATS,
    IPOD_NANO_1G2G_FORMATS,
    IPOD_PHOTO_FORMATS,
    IPOD_VIDEO_FORMATS,
    IPOD_NANO_4G_FORMATS,
    IPOD_NANO_5G_FORMATS,
    ALL_KNOWN_FORMATS,
)
# Re-export canonical format lookups from ipod_models
from ipod_models import ITHMB_FORMAT_MAP, ITHMB_SIZE_MAP, ithmb_formats_for_device

__all__ = [
    'write_artworkdb',
    'ArtworkEntry',
    'extract_art',
    'art_hash',
    'convert_art_for_ipod',
    'image_from_bytes',
    'rgb888_to_rgb565',
    'get_artwork_formats',
    'IPOD_CLASSIC_FORMATS',
    'IPOD_NANO_1G2G_FORMATS',
    'IPOD_PHOTO_FORMATS',
    'IPOD_VIDEO_FORMATS',
    'IPOD_NANO_4G_FORMATS',
    'IPOD_NANO_5G_FORMATS',
    'ALL_KNOWN_FORMATS',
    'ITHMB_FORMAT_MAP',
    'ITHMB_SIZE_MAP',
    'ithmb_formats_for_device',
]
