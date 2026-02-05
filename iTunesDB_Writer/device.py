"""
iPod device detection and identification.
Based on libgpod's itdb_device.c.

This module handles:
- Reading SysInfo file for device identification
- Detecting which checksum type a device requires
- Getting FireWire GUID for hash computation
"""

import os
import re
from enum import IntEnum
from typing import Optional


class ChecksumType(IntEnum):
    """Checksum types for different iPod generations."""
    NONE = 0           # Pre-2007 iPods: no checksum needed
    HASH58 = 1         # iPod Nano 3G
    HASH72 = 2         # iPod Classic (all), Nano 4G/5G
    UNSUPPORTED = 98   # iPod Nano 6G/7G (HASHAB - not reverse-engineered)
    UNKNOWN = 99       # Unknown device


# Device model patterns and their checksum requirements
# Based on libgpod itdb_device.c itdb_device_get_checksum_type()
#
# HASH58: Nano 3G, Nano 4G, Classic 2G*, Classic 3G*
# HASH72: Nano 5G, Classic 1G (and iPhones/iPod Touches - not supported here)
# HASHAB: Nano 6G/7G - UNSUPPORTED (never reverse-engineered)
#
# *Note: "Classic 2G/3G" in libgpod refers to the 6.5G/7G iPod Video variants,
# NOT the iPod Classic product line. The actual "iPod Classic" (released 2007)
# uses HASH72 according to multiple sources including Clickwheel library.
# However, libgpod's model detection may vary. When in doubt, check HashInfo existence.

DEVICE_CHECKSUMS = {
    # iPod Classic - HASH72 (per Clickwheel and real-world testing)
    # Model numbers: MB029 (80GB), MB147 (160GB), MC293 (160GB 2G), etc.
    'MB029': ChecksumType.HASH72,  # Classic 1G 80GB (Sept 2007)
    'MB147': ChecksumType.HASH72,  # Classic 1G 160GB (Sept 2007)
    'MB562': ChecksumType.HASH72,  # Classic 1G 80GB (late 2007)
    'MB565': ChecksumType.HASH72,  # Classic 1G 160GB (late 2007)
    'MC293': ChecksumType.HASH72,  # Classic 2G 160GB (Sept 2009)
    'MC297': ChecksumType.HASH72,  # Classic 2G 160GB (Sept 2009)

    # iPod Nano 3G - HASH58 (confirmed in libgpod)
    'MA978': ChecksumType.HASH58,  # Nano 3G 4GB
    'MA980': ChecksumType.HASH58,  # Nano 3G 8GB
    'MB261': ChecksumType.HASH58,  # Nano 3G 4GB
    'MB249': ChecksumType.HASH58,  # Nano 3G 8GB

    # iPod Nano 4G - HASH58 (confirmed in libgpod)
    'MB754': ChecksumType.HASH58,  # Nano 4G 8GB
    'MB903': ChecksumType.HASH58,  # Nano 4G 4GB
    'MB907': ChecksumType.HASH58,  # Nano 4G 8GB
    'MB909': ChecksumType.HASH58,  # Nano 4G 16GB

    # iPod Nano 5G - HASH72 (confirmed in libgpod)
    'MC031': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC040': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC049': ChecksumType.HASH72,  # Nano 5G 16GB
    'MC050': ChecksumType.HASH72,  # Nano 5G 16GB
    'MC060': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC062': ChecksumType.HASH72,  # Nano 5G 16GB

    # iPod Nano 6G/7G - UNSUPPORTED (HASHAB never reverse-engineered)
    'MC525': ChecksumType.UNSUPPORTED,  # Nano 6G 8GB
    'MC526': ChecksumType.UNSUPPORTED,  # Nano 6G 8GB
    'MC688': ChecksumType.UNSUPPORTED,  # Nano 6G 16GB
    'MC689': ChecksumType.UNSUPPORTED,  # Nano 6G 16GB
    'MD476': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
    'MD477': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
    'MD481': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
}

# Older iPods that don't need any checksum
NO_CHECKSUM_MODELS = {
    # iPod 1G-5G, Mini, Photo
    'M8541', 'M8697', 'M8709', 'M8740', 'M8741',  # 1G/2G
    'M8976', 'M9244', 'M9245', 'M9282',            # 3G
    'M9282', 'M9585', 'M9586', 'M9724', 'M9725',  # 4G
    'M9800', 'M9829', 'M9830', 'M9831', 'M9834',  # Photo
    'MA002', 'MA003', 'MA004', 'MA005', 'MA006',  # 5G
    'MA099', 'MA107', 'MA147', 'MA148', 'MA350',  # 5G
    'MA446', 'MA448', 'MA450', 'MA497',            # 5G
    'M9160', 'M9436', 'M9437', 'M9460', 'M9800',  # Mini
    'M9801', 'M9802', 'M9803', 'M9804', 'M9805',  # Mini
    'M9806', 'M9807', 'M9809',                      # Mini
    # Nano 1G-2G
    'MA004', 'MA005', 'MA099', 'MA107', 'MA350',
    'MA477', 'MA487', 'MA497', 'MA725', 'MA726',
    'MA727', 'MA428', 'MA464', 'MA477', 'MA484',
}


# Comprehensive iPod model database
# Maps model numbers to (name, generation, capacity, color)
# Based on libgpod's ipod_info_table from itdb_device.c
IPOD_MODELS = {
    # iPod Classic (2007-2014)
    'MB029': ("iPod Classic", "1st Gen", "80GB", "Silver"),
    'MB147': ("iPod Classic", "1st Gen", "160GB", "Silver"),
    'MB150': ("iPod Classic", "1st Gen", "160GB", "Black"),
    'MB562': ("iPod Classic", "1st Gen", "80GB", "Silver"),
    'MB565': ("iPod Classic", "1st Gen", "160GB", "Silver"),
    'MC293': ("iPod Classic", "2nd Gen", "160GB", "Silver"),
    'MC297': ("iPod Classic", "2nd Gen", "160GB", "Black"),

    # iPod (Original / Scroll Wheel)
    'M8541': ("iPod", "1st Gen", "5GB", "White"),
    'M8697': ("iPod", "1st Gen", "5GB", "White"),
    'M8709': ("iPod", "1st Gen", "10GB", "White"),
    'M8740': ("iPod", "2nd Gen", "10GB", "White"),
    'M8741': ("iPod", "2nd Gen", "20GB", "White"),
    'M8948': ("iPod", "2nd Gen", "20GB", "White"),

    # iPod (Touch Wheel / Dock Connector)
    'M8976': ("iPod", "3rd Gen", "10GB", "White"),
    'M9244': ("iPod", "3rd Gen", "15GB", "White"),
    'M9245': ("iPod", "3rd Gen", "30GB", "White"),
    'M9460': ("iPod", "3rd Gen", "40GB", "White"),

    # iPod (Click Wheel / 4th Gen)
    'M9282': ("iPod", "4th Gen", "20GB", "White"),
    'M9585': ("iPod U2", "4th Gen", "20GB", "Black"),
    'M9586': ("iPod U2", "4th Gen", "20GB", "Black"),

    # iPod Photo / Color
    'M9829': ("iPod Photo", "4th Gen", "30GB", "White"),
    'M9830': ("iPod Photo", "4th Gen", "60GB", "White"),
    'M9831': ("iPod Photo U2", "4th Gen", "20GB", "Black"),
    'M9834': ("iPod Photo", "4th Gen", "40GB", "White"),
    'MA079': ("iPod Photo", "4th Gen", "30GB", "White"),
    'MA127': ("iPod Photo U2", "4th Gen", "20GB", "Black"),

    # iPod Video (5th Gen)
    'MA002': ("iPod Video", "5th Gen", "30GB", "White"),
    'MA003': ("iPod Video", "5th Gen", "60GB", "White"),
    'MA005': ("iPod Video U2", "5th Gen", "30GB", "Black"),
    'MA099': ("iPod Video", "5th Gen", "30GB", "Black"),
    'MA107': ("iPod Video", "5th Gen", "60GB", "Black"),
    'MA146': ("iPod Video", "5th Gen", "30GB", "White"),
    'MA147': ("iPod Video", "5th Gen", "60GB", "White"),
    'MA148': ("iPod Video U2", "5th Gen", "30GB", "Black"),

    # iPod Video (5.5th Gen / Enhanced)
    'MA444': ("iPod Video", "5.5th Gen", "30GB", "White"),
    'MA446': ("iPod Video", "5.5th Gen", "30GB", "Black"),
    'MA448': ("iPod Video", "5.5th Gen", "60GB", "Black"),
    'MA450': ("iPod Video", "5.5th Gen", "80GB", "Black"),
    'MA664': ("iPod Video", "5.5th Gen", "80GB", "Black"),

    # iPod Mini
    'M9160': ("iPod Mini", "1st Gen", "4GB", "Silver"),
    'M9436': ("iPod Mini", "1st Gen", "4GB", "Blue"),
    'M9437': ("iPod Mini", "1st Gen", "4GB", "Pink"),
    'M9438': ("iPod Mini", "1st Gen", "4GB", "Green"),
    'M9439': ("iPod Mini", "1st Gen", "4GB", "Gold"),
    'M9800': ("iPod Mini", "2nd Gen", "4GB", "Silver"),
    'M9801': ("iPod Mini", "2nd Gen", "6GB", "Silver"),
    'M9802': ("iPod Mini", "2nd Gen", "4GB", "Blue"),
    'M9803': ("iPod Mini", "2nd Gen", "6GB", "Blue"),
    'M9804': ("iPod Mini", "2nd Gen", "4GB", "Pink"),
    'M9805': ("iPod Mini", "2nd Gen", "6GB", "Pink"),
    'M9806': ("iPod Mini", "2nd Gen", "4GB", "Green"),
    'M9807': ("iPod Mini", "2nd Gen", "6GB", "Green"),

    # iPod Nano (1st Gen)
    # Note: MA350, MA352, MA426, MA428 confirmed for Nano 1st Gen
    'MA350': ("iPod Nano", "1st Gen", "1GB", "Black"),
    'MA352': ("iPod Nano", "1st Gen", "2GB", "Black"),
    'MA426': ("iPod Nano", "1st Gen", "4GB", "Black"),
    'MA428': ("iPod Nano", "1st Gen", "4GB", "White"),
    'MA099B': ("iPod Nano", "1st Gen", "2GB", "Black"),  # UK model

    # iPod Nano (2nd Gen)
    'MA477': ("iPod Nano", "2nd Gen", "2GB", "Silver"),
    'MA484': ("iPod Nano", "2nd Gen", "4GB", "Silver"),
    'MA487': ("iPod Nano", "2nd Gen", "8GB", "Black"),
    'MA497': ("iPod Nano", "2nd Gen", "4GB", "Blue"),
    'MA725': ("iPod Nano", "2nd Gen", "4GB", "Pink"),
    'MA726': ("iPod Nano", "2nd Gen", "4GB", "Green"),
    'MA727': ("iPod Nano", "2nd Gen", "2GB", "Pink"),

    # iPod Nano (3rd Gen - "Fat" Nano with video)
    'MA978': ("iPod Nano", "3rd Gen", "4GB", "Silver"),
    'MA979': ("iPod Nano", "3rd Gen", "8GB", "Silver"),
    'MA980': ("iPod Nano", "3rd Gen", "8GB", "Black"),
    'MB245': ("iPod Nano", "3rd Gen", "4GB", "Blue"),
    'MB249': ("iPod Nano", "3rd Gen", "8GB", "Blue"),
    'MB253': ("iPod Nano", "3rd Gen", "4GB", "Green"),
    'MB257': ("iPod Nano", "3rd Gen", "8GB", "Green"),
    'MB261': ("iPod Nano", "3rd Gen", "4GB", "Red"),

    # iPod Nano (4th Gen - Tall Nano)
    'MB598': ("iPod Nano", "4th Gen", "8GB", "Silver"),
    'MB654': ("iPod Nano", "4th Gen", "8GB", "Purple"),
    'MB732': ("iPod Nano", "4th Gen", "16GB", "Black"),
    'MB742': ("iPod Nano", "4th Gen", "8GB", "Black"),
    'MB748': ("iPod Nano", "4th Gen", "4GB", "Silver"),
    'MB754': ("iPod Nano", "4th Gen", "8GB", "Pink"),
    'MB903': ("iPod Nano", "4th Gen", "4GB", "Silver"),
    'MB907': ("iPod Nano", "4th Gen", "8GB", "Blue"),
    'MB909': ("iPod Nano", "4th Gen", "16GB", "Silver"),

    # iPod Nano (5th Gen - Camera Nano)
    'MC027': ("iPod Nano", "5th Gen", "8GB", "Silver"),
    'MC031': ("iPod Nano", "5th Gen", "8GB", "Black"),
    'MC040': ("iPod Nano", "5th Gen", "8GB", "Purple"),
    'MC049': ("iPod Nano", "5th Gen", "16GB", "Silver"),
    'MC050': ("iPod Nano", "5th Gen", "16GB", "Black"),
    'MC060': ("iPod Nano", "5th Gen", "8GB", "Green"),
    'MC062': ("iPod Nano", "5th Gen", "16GB", "Purple"),
    'MC064': ("iPod Nano", "5th Gen", "8GB", "Pink"),
    'MC066': ("iPod Nano", "5th Gen", "8GB", "Orange"),
    'MC068': ("iPod Nano", "5th Gen", "8GB", "Yellow"),
    'MC072': ("iPod Nano", "5th Gen", "8GB", "Blue"),

    # iPod Nano (6th Gen - Touchscreen Square)
    'MC525': ("iPod Nano", "6th Gen", "8GB", "Graphite"),
    'MC526': ("iPod Nano", "6th Gen", "8GB", "Silver"),
    'MC540': ("iPod Nano", "6th Gen", "8GB", "Blue"),
    'MC688': ("iPod Nano", "6th Gen", "16GB", "Graphite"),
    'MC689': ("iPod Nano", "6th Gen", "16GB", "Silver"),
    'MC690': ("iPod Nano", "6th Gen", "16GB", "Blue"),
    'MC691': ("iPod Nano", "6th Gen", "16GB", "Green"),
    'MC692': ("iPod Nano", "6th Gen", "16GB", "Orange"),
    'MC693': ("iPod Nano", "6th Gen", "16GB", "Pink"),

    # iPod Nano (7th Gen - Tall Touchscreen)
    'MD476': ("iPod Nano", "7th Gen", "16GB", "Slate"),
    'MD477': ("iPod Nano", "7th Gen", "16GB", "Silver"),
    'MD478': ("iPod Nano", "7th Gen", "16GB", "Purple"),
    'MD479': ("iPod Nano", "7th Gen", "16GB", "Pink"),
    'MD480': ("iPod Nano", "7th Gen", "16GB", "Yellow"),
    'MD481': ("iPod Nano", "7th Gen", "16GB", "Green"),

    # iPod Shuffle (1st Gen)
    'M9724': ("iPod Shuffle", "1st Gen", "512MB", "White"),
    'M9725': ("iPod Shuffle", "1st Gen", "1GB", "White"),

    # iPod Shuffle (2nd Gen)
    'MA564': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    'MA947': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MA949': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MA951': ("iPod Shuffle", "2nd Gen", "1GB", "Orange"),
    'MA953': ("iPod Shuffle", "2nd Gen", "1GB", "Pink"),
    'MB225': ("iPod Shuffle", "2nd Gen", "2GB", "Silver"),
    'MB518': ("iPod Shuffle", "2nd Gen", "1GB", "Red"),

    # iPod Shuffle (3rd Gen - Buttonless)
    'MC164': ("iPod Shuffle", "3rd Gen", "4GB", "Silver"),
    'MC305': ("iPod Shuffle", "3rd Gen", "4GB", "Black"),
    'MC306': ("iPod Shuffle", "3rd Gen", "2GB", "Silver"),
    'MC307': ("iPod Shuffle", "3rd Gen", "2GB", "Black"),
    'MC381': ("iPod Shuffle", "3rd Gen", "2GB", "Silver"),
    'MC384': ("iPod Shuffle", "3rd Gen", "2GB", "Pink"),

    # iPod Shuffle (4th Gen - With Buttons)
    'MC749': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MC750': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MC751': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MC752': ("iPod Shuffle", "4th Gen", "2GB", "Orange"),
    'MC753': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MD773': ("iPod Shuffle", "4th Gen", "2GB", "Space Gray"),
    'MD774': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MD775': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MD776': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MD777': ("iPod Shuffle", "4th Gen", "2GB", "Yellow"),
    'MD778': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MD779': ("iPod Shuffle", "4th Gen", "2GB", "Red"),
}


def read_sysinfo(ipod_path: str) -> dict:
    """
    Parse SysInfo file from iPod.

    The SysInfo file contains device identification info:
    - ModelNumStr: Device model (e.g., "xA623")
    - FirewireGuid: Device GUID for hash computation
    - pszSerialNumber: Serial number
    - BoardHwName: Hardware identifier
    - visibleBuildID: Firmware version

    Args:
        ipod_path: Mount point of iPod

    Returns:
        Dictionary of SysInfo key-value pairs

    Raises:
        FileNotFoundError: If SysInfo doesn't exist
    """
    sysinfo_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")

    if not os.path.exists(sysinfo_path):
        raise FileNotFoundError(f"SysInfo not found at {sysinfo_path}")

    sysinfo = {}
    with open(sysinfo_path, 'r', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                sysinfo[key.strip()] = value.strip()

    return sysinfo


def _extract_model_number(model_str: str) -> Optional[str]:
    """
    Extract model number from ModelNumStr.

    ModelNumStr format varies:
    - "xA623" -> "MA623"
    - "MC293" -> "MC293"
    - "M9282" -> "M9282"
    """
    if not model_str:
        return None

    # Remove leading 'x' if present (some devices use xANNN format)
    if model_str.startswith('x'):
        model_str = 'M' + model_str[1:]

    # Extract model number (typically 5 characters: MXXXX or MAXXXX)
    match = re.match(r'^(M[A-Z]?\d{3,4})', model_str.upper())
    if match:
        return match.group(1)

    return model_str.upper()[:5] if len(model_str) >= 5 else model_str.upper()


def get_firewire_id(ipod_path: str) -> bytes:
    """
    Get FireWire GUID from iPod SysInfo.

    Args:
        ipod_path: Mount point of iPod

    Returns:
        FireWire GUID as bytes (typically 8 bytes)

    Raises:
        FileNotFoundError: If SysInfo doesn't exist
        KeyError: If FirewireGuid not in SysInfo
    """
    sysinfo = read_sysinfo(ipod_path)

    guid = sysinfo.get('FirewireGuid')
    if guid is None:
        raise KeyError("FirewireGuid not found in SysInfo")

    # Remove optional '0x' prefix
    if guid.startswith('0x') or guid.startswith('0X'):
        guid = guid[2:]

    return bytes.fromhex(guid)


def detect_checksum_type(ipod_path: str) -> ChecksumType:
    """
    Detect which checksum type an iPod requires.

    Detection order:
    1. Check for model number in SysInfo
    2. Match against known device database
    3. Check for HashInfo file (indicates HASH72)
    4. Default to UNKNOWN

    Args:
        ipod_path: Mount point of iPod

    Returns:
        ChecksumType enum value
    """
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        # No SysInfo = probably not an iPod or very old
        return ChecksumType.NONE

    # Try to get model number
    model_str = sysinfo.get('ModelNumStr', '')
    model_num = _extract_model_number(model_str)

    if model_num:
        # Check no-checksum models first
        for prefix in NO_CHECKSUM_MODELS:
            if model_num.startswith(prefix):
                return ChecksumType.NONE

        # Check known devices with checksums
        for prefix, checksum in DEVICE_CHECKSUMS.items():
            if model_num.startswith(prefix):
                return checksum

    # Check for HashInfo file (indicates HASH72-capable device that was synced)
    hash_info_path = os.path.join(ipod_path, "iPod_Control", "Device", "HashInfo")
    if os.path.exists(hash_info_path):
        return ChecksumType.HASH72

    # Check firmware version for hints
    firmware = sysinfo.get('visibleBuildID', '')
    if firmware:
        # Later firmware versions require checksums
        try:
            version = int(firmware.split('.')[0])
            if version >= 2:
                return ChecksumType.UNKNOWN  # Needs investigation
        except (ValueError, IndexError):
            pass

    # If we have a FireWire ID, it's probably a post-2007 device
    if 'FirewireGuid' in sysinfo:
        # Conservative: return UNKNOWN so user knows to investigate
        return ChecksumType.UNKNOWN

    # Older iPods without FireWire ID don't need checksums
    return ChecksumType.NONE


def get_model_info(model_number: Optional[str]) -> tuple[str, str, str, str] | None:
    """
    Get detailed model information from model number.

    Args:
        model_number: 5-char model number (e.g., 'MC293')

    Returns:
        Tuple of (name, generation, capacity, color) or None if not found
    """
    if not model_number:
        return None

    # Exact match first
    if model_number in IPOD_MODELS:
        return IPOD_MODELS[model_number]

    # Try prefix matching (some models share prefixes)
    for prefix, info in IPOD_MODELS.items():
        if model_number.startswith(prefix[:4]):
            return info

    return None


def get_friendly_model_name(model_number: Optional[str]) -> str:
    """
    Get a user-friendly model name string.

    Args:
        model_number: 5-char model number (e.g., 'MC293')

    Returns:
        Friendly name like "iPod Classic 160GB Silver (2nd Gen)"
    """
    info = get_model_info(model_number)
    if info:
        name, gen, capacity, color = info
        return f"{name} {capacity} {color} ({gen})"
    return f"Unknown iPod ({model_number})" if model_number else "Unknown iPod"


def get_device_info(ipod_path: str) -> dict:
    """
    Get comprehensive device information.

    Args:
        ipod_path: Mount point of iPod

    Returns:
        Dictionary with device details including:
        - model: Model number
        - serial: Serial number
        - firmware: Firmware version
        - firewire_id: FireWire GUID
        - checksum_type: Required checksum type
        - checksum_name: Human-readable checksum name
    """
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        return {
            'error': 'SysInfo not found',
            'checksum_type': ChecksumType.NONE,
            'checksum_name': 'None (pre-2007 or not an iPod)',
        }

    checksum_type = detect_checksum_type(ipod_path)

    checksum_names = {
        ChecksumType.NONE: 'None (no checksum required)',
        ChecksumType.HASH58: 'HASH58 (Nano 3G - fully supported)',
        ChecksumType.HASH72: 'HASH72 (Classic/Nano 4G-5G - requires HashInfo)',
        ChecksumType.UNSUPPORTED: 'UNSUPPORTED (Nano 6G/7G - HASHAB not reverse-engineered)',
        ChecksumType.UNKNOWN: 'Unknown (device not in database)',
    }

    model_str = sysinfo.get('ModelNumStr', '')
    model_num = _extract_model_number(model_str)
    model_info = get_model_info(model_num)

    return {
        'model': model_num,
        'model_raw': model_str,
        'model_name': model_info[0] if model_info else 'Unknown',
        'model_generation': model_info[1] if model_info else '',
        'model_capacity': model_info[2] if model_info else '',
        'model_color': model_info[3] if model_info else '',
        'friendly_name': get_friendly_model_name(model_num),
        'serial': sysinfo.get('pszSerialNumber', ''),
        'firmware': sysinfo.get('visibleBuildID', ''),
        'board': sysinfo.get('BoardHwName', ''),
        'firewire_id': sysinfo.get('FirewireGuid', ''),
        'checksum_type': checksum_type,
        'checksum_name': checksum_names.get(checksum_type, 'Unknown'),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python device.py <ipod_path>")
        print("Example: python device.py E:")
        sys.exit(1)

    ipod_path = sys.argv[1]

    info = get_device_info(ipod_path)

    print("iPod Device Information")
    print("=" * 40)
    for key, value in info.items():
        print(f"{key:15}: {value}")
