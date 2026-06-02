"""Locations.itdb.cbk writer — HASHAB-signed block checksums.

The cbk (checksum book) file contains SHA1 checksums of 1024-byte blocks
of Locations.itdb, plus a final SHA1 of all those checksums, signed with
HASHAB.

File format:
    [57 bytes]  HASHAB signature of final_sha1 (or 20 bytes for HASH58/72)
    [20 bytes]  final_sha1 = SHA1(all_block_sha1s concatenated)
    [Nx20 bytes] SHA1 of each 1024-byte block of Locations.itdb

For HASHAB (Nano 6G/7G), the header is 57 bytes.
For HASH58, the header would be 20 bytes.
For HASH72, the header would be 46 bytes.

Reference: libgpod itdb_sqlite.c mk_Locations_cbk()
"""

import hashlib
import logging
import os

from ipod_device import ChecksumType

logger = logging.getLogger(__name__)

# Block size for checksumming
BLOCK_SIZE = 1024


def _compute_block_sha1s(data: bytes) -> list[bytes]:
    """Compute SHA1 hash of each 1024-byte block.

    The last block may be smaller than 1024 bytes; it's still hashed.

    Args:
        data: Raw file contents.

    Returns:
        List of 20-byte SHA1 digests, one per block.
    """
    block_hashes = []
    offset = 0
    while offset < len(data):
        block = data[offset:offset + BLOCK_SIZE]
        block_hashes.append(hashlib.sha1(block).digest())
        offset += BLOCK_SIZE
    return block_hashes


def write_locations_cbk(
    cbk_path: str,
    locations_itdb_path: str,
    checksum_type: ChecksumType,
    firewire_id: bytes | None = None,
    ipod_path: str | None = None,
) -> None:
    """Generate and write the Locations.itdb.cbk checksum file.

    Args:
        cbk_path: Output path for the .cbk file.
        locations_itdb_path: Path to the Locations.itdb file to checksum.
        checksum_type: The device's checksum algorithm (HASHAB, HASH58, etc.).
        firewire_id: 8-byte FireWire GUID (required for HASHAB and HASH58).
        ipod_path: Mount point of iPod (used for HASH72 HashInfo fallback).

    Raises:
        ValueError: If firewire_id is missing when needed.
        FileNotFoundError: If Locations.itdb doesn't exist.
    """
    with open(locations_itdb_path, 'rb') as f:
        locations_data = f.read()

    # Compute block SHA1s
    block_sha1s = _compute_block_sha1s(locations_data)

    # Compute final SHA1 = SHA1(concatenation of all block SHA1s)
    all_sha1s = b''.join(block_sha1s)
    final_sha1 = hashlib.sha1(all_sha1s).digest()

    logger.debug("Locations.itdb: %d bytes, %d blocks, final SHA1: %s",
                 len(locations_data), len(block_sha1s), final_sha1.hex())

    # Generate header signature based on checksum type
    if checksum_type == ChecksumType.HASHAB:
        if not firewire_id or len(firewire_id) < 8:
            raise ValueError("FireWire ID required for HASHAB cbk signature")

        from iTunesDB_Writer.hashab import compute_hashab
        header = compute_hashab(final_sha1, firewire_id[:8])
        if len(header) != 57:
            raise RuntimeError(f"HASHAB returned {len(header)} bytes, expected 57")
        logger.debug("CBK header: HASHAB signature (%d bytes)", len(header))

    elif checksum_type == ChecksumType.HASH58:
        if not firewire_id or len(firewire_id) < 8:
            raise ValueError("FireWire ID required for HASH58 cbk signature")

        from iTunesDB_Writer.hash58 import compute_hash58
        header = compute_hash58(firewire_id, final_sha1)
        logger.debug("CBK header: HASH58 signature (%d bytes)", len(header))

    elif checksum_type == ChecksumType.HASH72:
        from iTunesDB_Writer.hash72 import (
            HashInfo,
            _hash_generate,
            extract_hash_info_to_dict,
            read_hash_info,
        )

        # Try centralized store first
        hash_info = None
        try:
            from ipod_device import get_current_device
            dev = get_current_device()
            if dev and dev.hash_info_iv and dev.hash_info_rndpart:
                hash_info = HashInfo(
                    uuid=b'\x00' * 20,
                    rndpart=dev.hash_info_rndpart,
                    iv=dev.hash_info_iv,
                )
        except Exception:
            pass

        if hash_info is None and ipod_path:
            try:
                hash_info = read_hash_info(ipod_path)
            except Exception:
                pass

        # Fallback: extract from existing iTunesCDB on device
        if hash_info is None and ipod_path:
            try:
                from ipod_device import resolve_itdb_path
                itdb_path = resolve_itdb_path(ipod_path)
                if itdb_path:
                    with open(itdb_path, "rb") as f:
                        itdb_data = f.read()
                    hd = extract_hash_info_to_dict(itdb_data)
                    if hd:
                        hash_info = HashInfo(
                            uuid=b'\x00' * 20,
                            rndpart=hd['rndpart'],
                            iv=hd['iv'],
                        )
                        logger.debug("CBK: extracted HashInfo from existing %s",
                                     os.path.basename(itdb_path))
            except Exception:
                pass

        if hash_info:
            header = _hash_generate(final_sha1, hash_info.iv, hash_info.rndpart)
            logger.debug("CBK header: HASH72 signature (%d bytes)", len(header))
        else:
            logger.warning("No HashInfo available for HASH72 cbk — writing final SHA1 only")
            header = final_sha1

    else:
        # No checksum needed — older devices or NONE
        # Just write the SHA1 as header (20 bytes)
        header = final_sha1

    # Write the cbk file: header + final_sha1 + block_sha1s
    with open(cbk_path, 'wb') as f:
        f.write(header)
        f.write(final_sha1)
        for bsha1 in block_sha1s:
            f.write(bsha1)

    total_size = len(header) + 20 + len(block_sha1s) * 20
    logger.info("Wrote Locations.itdb.cbk: %d bytes "
                "(%d-byte header + 20-byte final SHA1 + %d×20 block SHA1s)",
                total_size, len(header), len(block_sha1s))
