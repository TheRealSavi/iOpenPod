"""
iTunesDB Writer module for iOpenPod.

This module provides write support for iPod Classic/Nano iTunesDB files.

Supported devices:
- Pre-2007 iPods (1G-5G, Mini, Photo): No hash required
- iPod Nano 3G, Nano 4G: HASH58 (fully portable, needs FireWire ID)
- iPod Classic (all generations), Nano 5G: HASH72 (requires HashInfo file)

NOT supported (out of scope):
- iPod Nano 6G/7G: HASHAB algorithm was never reverse-engineered

Usage:
    from iTunesDB_Writer import write_checksum, detect_checksum_type

    checksum_type = detect_checksum_type(ipod_path)
    with open(itunesdb_path, 'rb') as f:
        itdb_data = bytearray(f.read())

    success = write_checksum(itdb_data, ipod_path)
"""

from .device import (
    ChecksumType,
    detect_checksum_type,
    read_sysinfo,
    get_firewire_id,
)

from .hash58 import (
    compute_hash58,
    write_hash58,
)

from .hash72 import (
    compute_hash72,
    write_hash72,
    read_hash_info,
    extract_hash_info,
    extract_hash_info_to_dict,
)

from .mhit_writer import TrackInfo, write_mhit
from .mhbd_writer import write_itunesdb, write_mhbd, add_tracks_to_itunesdb, extract_db_info


def write_checksum(itdb_data: bytearray, ipod_path: str) -> bool:
    """
    Write appropriate checksum to iTunesDB based on device type.

    Args:
        itdb_data: Mutable bytearray of complete iTunesDB file
        ipod_path: Mount point of iPod

    Returns:
        True if checksum was written successfully

    Raises:
        ValueError: For unsupported devices (iPod Nano 6G/7G)
    """
    checksum_type = detect_checksum_type(ipod_path)

    if checksum_type == ChecksumType.NONE:
        # No hash needed for older iPods
        return True

    elif checksum_type == ChecksumType.HASH58:
        firewire_id = get_firewire_id(ipod_path)
        write_hash58(itdb_data, firewire_id)
        return True

    elif checksum_type == ChecksumType.HASH72:
        write_hash72(itdb_data, ipod_path)
        return True

    else:
        raise ValueError(
            f"Unsupported checksum type: {checksum_type}. "
            "iPod Nano 6G/7G devices use HASHAB which is not supported."
        )


__all__ = [
    'ChecksumType',
    'detect_checksum_type',
    'read_sysinfo',
    'get_firewire_id',
    'compute_hash58',
    'write_hash58',
    'compute_hash72',
    'write_hash72',
    'read_hash_info',
    'extract_hash_info',
    'extract_hash_info_to_dict',
    'write_checksum',
    # Writer
    'TrackInfo',
    'write_mhit',
    'write_mhbd',
    'write_itunesdb',
    'add_tracks_to_itunesdb',
    'extract_db_info',
]
