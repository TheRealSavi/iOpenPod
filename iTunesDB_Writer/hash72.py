"""
HASH72 implementation for iPod Classic 1G, Nano 4G/5G.
Ported from libgpod's itdb_hash72.c.

IMPORTANT: This requires a HashInfo file that must be extracted from a valid
iTunes sync. The HashInfo file contains the IV and random bytes needed to
generate signatures.

If you don't have a HashInfo file:
1. Sync once with iTunes (creates /iPod_Control/Device/HashInfo)
2. OR use extract_hash_info() with a known-good iTunesDB from iTunes

Usage:
    from hash72 import write_hash72

    with open("iTunesDB", "rb") as f:
        itdb_data = bytearray(f.read())

    # Requires HashInfo file to exist at /iPod_Control/Device/HashInfo
    write_hash72(itdb_data, ipod_path="/media/ipod")

    with open("iTunesDB", "wb") as f:
        f.write(itdb_data)
"""

import hashlib
import os
from typing import Optional

# AES-128 key (from libgpod itdb_hash72.c line 40)
AES_KEY = bytes([
    0x61, 0x8c, 0xa1, 0x0d, 0xc7, 0xf5, 0x7f, 0xd3,
    0xb4, 0x72, 0x3e, 0x08, 0x15, 0x74, 0x63, 0xd7
])

# Hash scheme identifier for HASH72
ITDB_CHECKSUM_HASH72 = 2

# Header offsets
OFFSET_DB_ID = 0x18       # 8 bytes
OFFSET_UNK_0x32 = 0x32    # 20 bytes
OFFSET_HASHING_SCHEME = 0x30  # 2 bytes (was 0x46 - wrong!)
OFFSET_HASH58 = 0x58      # 20 bytes
OFFSET_HASH72 = 0x72      # 46 bytes (NOT at 0x58!)

# HashInfo file structure
HASHINFO_HEADER = b"HASHv0"
HASHINFO_HEADER_LEN = 6
HASHINFO_UUID_LEN = 20
HASHINFO_RNDPART_LEN = 12
HASHINFO_IV_LEN = 16


class HashInfo:
    """Parsed HashInfo file data."""

    def __init__(self, uuid: bytes, rndpart: bytes, iv: bytes):
        self.uuid = uuid
        self.rndpart = rndpart
        self.iv = iv


def _get_hash_info_path(ipod_path: str) -> str:
    """Get path to HashInfo file."""
    return os.path.join(ipod_path, "iPod_Control", "Device", "HashInfo")


def read_hash_info(ipod_path: str) -> Optional[HashInfo]:
    """
    Read and parse HashInfo file from iPod.

    HashInfo structure (54 bytes total):
    - header[6]: "HASHv0"
    - uuid[20]: Device UUID (should match FirewireGuid)
    - rndpart[12]: Random bytes for signature
    - iv[16]: AES initialization vector

    Args:
        ipod_path: Mount point of iPod

    Returns:
        HashInfo object or None if file doesn't exist
    """
    path = _get_hash_info_path(ipod_path)

    if not os.path.exists(path):
        return None

    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 54:
        return None

    if data[:6] != HASHINFO_HEADER:
        return None

    # Parse structure
    uuid = data[6:26]
    rndpart = data[26:38]
    iv = data[38:54]

    return HashInfo(uuid, rndpart, iv)


def write_hash_info(ipod_path: str, uuid: bytes, iv: bytes, rndpart: bytes) -> bool:
    """
    Write HashInfo file to iPod.

    Args:
        ipod_path: Mount point of iPod
        uuid: 20-byte device UUID
        iv: 16-byte AES IV
        rndpart: 12-byte random bytes

    Returns:
        True if successful
    """
    if len(uuid) != 20 or len(iv) != 16 or len(rndpart) != 12:
        return False

    data = HASHINFO_HEADER + uuid + rndpart + iv

    path = _get_hash_info_path(ipod_path)
    device_dir = os.path.dirname(path)
    os.makedirs(device_dir, exist_ok=True)

    with open(path, 'wb') as f:
        f.write(data)

    return True


def _compute_itunesdb_sha1(itdb_data: bytearray) -> bytes:
    """
    Compute SHA1 of iTunesDB with hash fields zeroed.

    From libgpod itdb_hash72_compute_itunesdb_sha1():
    - db_id (offset 0x18, 8 bytes) is zeroed
    - hash58 (offset 0x58, 20 bytes) is zeroed
    - hash72 (offset 0x58, 46 bytes) is zeroed

    NOTE: Unlike HASH58, unk_0x32 is NOT zeroed for HASH72!
    libgpod backs it up and restores it, but since it's never zeroed,
    we don't need to do anything with it.
    """
    # Work on a copy to avoid modifying original
    data = bytearray(itdb_data)

    # Zero fields for hash computation (same as libgpod)
    # Note: hash58 and hash72 share the same offset 0x58
    data[OFFSET_DB_ID:OFFSET_DB_ID + 8] = b'\x00' * 8
    data[OFFSET_HASH58:OFFSET_HASH58 + 20] = b'\x00' * 20
    data[OFFSET_HASH72:OFFSET_HASH72 + 46] = b'\x00' * 46

    return hashlib.sha1(bytes(data)).digest()


def _hash_generate(sha1: bytes, iv: bytes, rndpart: bytes) -> bytes:
    """
    Generate 46-byte signature using AES encryption.

    Signature format:
    - bytes 0-1: 0x01 0x00 (prefix)
    - bytes 2-13: rndpart (12 bytes)
    - bytes 14-45: AES-CBC encrypted (sha1 + rndpart) (32 bytes)

    Args:
        sha1: 20-byte SHA1 of iTunesDB
        iv: 16-byte initialization vector
        rndpart: 12-byte random bytes

    Returns:
        46-byte signature
    """
    try:
        from Crypto.Cipher import AES
    except ImportError:
        try:
            from Cryptodome.Cipher import AES  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "PyCryptodome is required for HASH72. "
                "Install with: pip install pycryptodome"
            )

    # Plaintext: sha1 (20 bytes) + rndpart (12 bytes) = 32 bytes
    plaintext = sha1 + rndpart

    # AES-CBC encrypt
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(plaintext)

    # Build signature
    signature = bytearray(46)
    signature[0] = 0x01
    signature[1] = 0x00
    signature[2:14] = rndpart
    signature[14:46] = encrypted

    return bytes(signature)


def _hash_extract(signature: bytes, sha1: bytes) -> Optional[tuple]:
    """
    Extract IV and random bytes from a valid signature.

    This can be used to create a HashInfo file from a known-good
    iTunes-generated iTunesDB.

    Algorithm from libgpod itdb_hash72.c hash_extract():

    The signature was created by:
        C = AES_encrypt_CBC(plaintext, IV) where plaintext = sha1 + rndpart

    In CBC mode, the first block is:
        C_0 = AES_encrypt(P_0 XOR IV) where P_0 = sha1[:16]

    To recover IV, we decrypt C_0 using sha1[:16] as a fake IV:
        output = AES_decrypt(C_0) XOR sha1[:16]
               = (P_0 XOR IV) XOR sha1[:16]
               = (sha1[:16] XOR IV) XOR sha1[:16]
               = IV

    The libgpod code also does a sanity check comparing plaintext[16:32]
    to output[16:32], but since only the first 16 bytes are decrypted,
    output[16:32] is always equal to plaintext[16:32]. We keep this check
    for compatibility.

    Args:
        signature: 46-byte signature from valid iTunesDB
        sha1: 20-byte SHA1 that was used to generate the signature

    Returns:
        (iv, rndpart) tuple or None if invalid
    """
    try:
        from Crypto.Cipher import AES
    except ImportError:
        try:
            from Cryptodome.Cipher import AES  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "PyCryptodome is required for HASH72. "
                "Install with: pip install pycryptodome"
            )

    if len(signature) < 46 or signature[0] != 0x01 or signature[1] != 0x00:
        return None

    # Build plaintext = sha1 + rndpart (matches libgpod)
    rndpart = signature[2:14]
    plaintext = bytearray(32)
    plaintext[:20] = sha1
    plaintext[20:32] = rndpart

    # Initialize output as copy of plaintext (matches libgpod: memcpy(output, plaintext, 32))
    output = bytearray(plaintext)

    # AES-CBC decrypt first 16 bytes only, using sha1[:16] as IV
    # This recovers the real IV through the XOR cancellation described above
    cipher = AES.new(AES_KEY, AES.MODE_CBC, bytes(plaintext[:16]))
    decrypted_block = cipher.decrypt(bytes(signature[14:30]))
    output[:16] = decrypted_block

    # Sanity check from libgpod - always passes since output[16:32] was
    # copied from plaintext[16:32] and never modified
    if bytes(plaintext[16:32]) != bytes(output[16:32]):
        return None

    # The IV is now in output[:16]
    iv = bytes(output[:16])

    return (iv, bytes(rndpart))


def extract_hash_info(ipod_path: str, valid_itdb_data: bytes) -> bool:
    """
    Extract HashInfo from a valid iTunes-generated iTunesDB.

    Use this when you have an iTunesDB that was created by iTunes
    but you don't have a HashInfo file.

    Args:
        ipod_path: Mount point of iPod
        valid_itdb_data: Contents of valid iTunes-generated iTunesDB

    Returns:
        True if HashInfo was successfully extracted and saved
    """
    if len(valid_itdb_data) < 0xA0:
        return False

    if valid_itdb_data[:4] != b'mhbd':
        return False

    # Get existing hash72 from CORRECT offset (0x72)
    hash72 = bytes(valid_itdb_data[OFFSET_HASH72:OFFSET_HASH72 + 46])

    # Check for valid signature marker
    if hash72[0:2] != bytes([0x01, 0x00]):
        # Not a valid hash72 signature
        return False

    # Compute SHA1
    itdb_copy = bytearray(valid_itdb_data)
    sha1 = _compute_itunesdb_sha1(itdb_copy)

    # Extract IV and rndpart
    result = _hash_extract(hash72, sha1)
    if result is None:
        return False

    iv, rndpart = result

    # Get UUID from device (or use zeros if not available)
    try:
        from .hash58 import read_firewire_id
        fw_id = read_firewire_id(ipod_path)
        uuid = bytearray(20)
        uuid[:len(fw_id)] = fw_id
    except Exception:
        uuid = bytes(20)

    return write_hash_info(ipod_path, bytes(uuid), iv, rndpart)


def extract_hash_info_to_dict(valid_itdb_data: bytes) -> dict | None:
    """
    Extract HashInfo from a valid iTunes-generated iTunesDB.

    Returns the extracted info as a dict instead of writing to disk.

    Args:
        valid_itdb_data: Contents of valid iTunes-generated iTunesDB

    Returns:
        Dict with 'iv' and 'rndpart' keys, or None if extraction failed
    """
    if len(valid_itdb_data) < 0xA0:
        return None

    if valid_itdb_data[:4] != b'mhbd':
        return None

    # Get existing hash72 from CORRECT offset (0x72)
    hash72 = bytes(valid_itdb_data[OFFSET_HASH72:OFFSET_HASH72 + 46])

    # Check for valid signature marker
    if hash72[0:2] != bytes([0x01, 0x00]):
        return None

    # Compute SHA1
    itdb_copy = bytearray(valid_itdb_data)
    sha1 = _compute_itunesdb_sha1(itdb_copy)

    # Extract IV and rndpart
    result = _hash_extract(hash72, sha1)
    if result is None:
        return None

    iv, rndpart = result
    return {'iv': iv, 'rndpart': rndpart}


def compute_hash72(ipod_path: str, itdb_data: bytes) -> bytes:
    """
    Compute HASH72 signature for iTunesDB data.

    Args:
        ipod_path: Mount point of iPod (for reading HashInfo)
        itdb_data: Complete iTunesDB file contents

    Returns:
        46-byte signature

    Raises:
        FileNotFoundError: If HashInfo file doesn't exist
    """
    hash_info = read_hash_info(ipod_path)
    if hash_info is None:
        raise FileNotFoundError(
            f"HashInfo file not found at {_get_hash_info_path(ipod_path)}. "
            "Sync once with iTunes to create it, or use extract_hash_info() "
            "with a valid iTunes-generated iTunesDB."
        )

    sha1 = _compute_itunesdb_sha1(bytearray(itdb_data))
    return _hash_generate(sha1, hash_info.iv, hash_info.rndpart)


def write_hash72(itdb_data: bytearray, ipod_path: str) -> None:
    """
    Compute and write HASH72 checksum to iTunesDB data in-place.

    Args:
        itdb_data: Mutable bytearray of complete iTunesDB file
        ipod_path: Mount point of iPod (for reading HashInfo)

    Raises:
        ValueError: If iTunesDB is too small
        FileNotFoundError: If HashInfo file doesn't exist
    """
    if len(itdb_data) < 0x6C:
        raise ValueError(f"iTunesDB file too small ({len(itdb_data)} bytes)")

    if itdb_data[:4] != b'mhbd':
        raise ValueError("Invalid iTunesDB: expected 'mhbd' header")

    # Set hashing scheme
    itdb_data[OFFSET_HASHING_SCHEME:OFFSET_HASHING_SCHEME + 2] = \
        ITDB_CHECKSUM_HASH72.to_bytes(2, 'little')

    # Compute and write signature
    signature = compute_hash72(ipod_path, bytes(itdb_data))
    itdb_data[OFFSET_HASH72:OFFSET_HASH72 + 46] = signature


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python hash72.py <ipod_path> <itunesdb_path>")
        print("Example: python hash72.py /media/ipod /media/ipod/iPod_Control/iTunes/iTunesDB")
        sys.exit(1)

    ipod_path = sys.argv[1]
    itunesdb_path = sys.argv[2]

    try:
        # Check for HashInfo
        hash_info = read_hash_info(ipod_path)
        if hash_info:
            print(f"HashInfo found: IV={hash_info.iv.hex()[:16]}...")
        else:
            print("HashInfo not found. Attempting to extract from iTunesDB...")
            with open(itunesdb_path, 'rb') as f:
                itdb_data = f.read()
            if extract_hash_info(ipod_path, itdb_data):
                print("HashInfo extracted and saved successfully!")
            else:
                print("Failed to extract HashInfo. Sync with iTunes first.")
                sys.exit(1)

        with open(itunesdb_path, 'rb') as f:
            itdb_data = bytearray(f.read())

        print(f"Read {len(itdb_data)} bytes from iTunesDB")

        write_hash72(itdb_data, ipod_path)
        print("Hash computed successfully!")

        # Write back (uncomment to actually write)
        # with open(itunesdb_path, 'wb') as f:
        #     f.write(itdb_data)
        # print("iTunesDB updated!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
