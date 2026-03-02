"""
HASHAB implementation for iPod Nano 6G and 7G.

Uses a WebAssembly module (calcHashAB.wasm) from dstaley/hashab — a clean-room
reimplementation of Apple's white-box AES signing algorithm.  The WASM binary
is executed via wasmtime-py, giving cross-platform support without compiling
native code.

Algorithm overview (4 phases inside the WASM module):
  1. CBC-MAC compression of UUID with AES
  2. Key material expansion (44 → 190 bytes)
  3. Initial buffer generation (190 → 16 bytes)
  4. White-box AES-128 encryption

The output is a 57-byte signature written at mhbd offset 0xAB.  This is
analogous to HASH58 (20 bytes at 0x58) and HASH72 (46 bytes at 0x72).

Source: https://github.com/dstaley/hashab (The Unlicense)
WASM release: https://github.com/dstaley/hashab/releases/tag/2025-01-04

Usage:
    from hashab import write_hashab

    with open("iTunesDB", "rb") as f:
        itdb_data = bytearray(f.read())

    firewire_id = bytes.fromhex("0011223344556677")  # From SysInfo
    write_hashab(itdb_data, firewire_id)

    with open("iTunesDB", "wb") as f:
        f.write(itdb_data)
"""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Header offsets (same as hash58/hash72 — shared mhbd layout)
OFFSET_DB_ID = 0x18          # 8 bytes — zeroed before hashing
OFFSET_HASHING_SCHEME = 0x30  # 2 bytes
OFFSET_UNK_0x32 = 0x32      # 20 bytes — zeroed for HASHAB (like HASH58)
OFFSET_HASH58 = 0x58         # 20 bytes — zeroed before hashing
OFFSET_HASH72 = 0x72         # 46 bytes — zeroed before hashing
OFFSET_HASHAB = 0xAB         # 57 bytes — the HASHAB signature lives here

HASHAB_SIZE = 57
ITDB_CHECKSUM_HASHAB = 4     # hashing_scheme value for HASHAB

# Path to the WASM module (shipped alongside this file)
_WASM_DIR = Path(__file__).parent / "wasm"
_WASM_PATH = _WASM_DIR / "calcHashAB.wasm"

# Lazy-loaded WASM engine (expensive to create — reuse across calls)
_wasm_instance = None
_wasm_store = None


def _get_wasm_instance():
    """Load the WASM module and return (store, instance).

    The module exports:
      memory         — linear memory
      getInputSha1() — returns pointer to 20-byte SHA1 input buffer
      getInputUuid() — returns pointer to 8-byte UUID input buffer
      getOutput()    — returns pointer to 57-byte output buffer
      calculateHash()— run the hash computation
    """
    global _wasm_instance, _wasm_store

    if _wasm_instance is not None:
        return _wasm_store, _wasm_instance

    try:
        import wasmtime
    except ImportError:
        raise ImportError(
            "wasmtime is required for HASHAB (iPod Nano 6G/7G). "
            "Install with: uv add wasmtime   or   pip install wasmtime"
        )

    if not _WASM_PATH.exists():
        raise FileNotFoundError(
            f"WASM module not found at {_WASM_PATH}. "
            "Download calcHashAB.wasm from "
            "https://github.com/dstaley/hashab/releases/tag/2025-01-04"
        )

    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module.from_file(engine, str(_WASM_PATH))
    instance = wasmtime.Instance(store, module, [])

    _wasm_store = store
    _wasm_instance = instance

    logger.debug("HASHAB WASM module loaded from %s", _WASM_PATH)
    return store, instance


def compute_hashab(sha1_digest: bytes, uuid: bytes) -> bytes:
    """
    Compute 57-byte HASHAB signature using the WASM module.

    Args:
        sha1_digest: 20-byte SHA1 hash of the iTunesDB (with hash fields zeroed)
        uuid: 8-byte FireWire GUID / UUID from SysInfo

    Returns:
        57-byte signature to write at mhbd offset 0xAB
    """
    if len(sha1_digest) != 20:
        raise ValueError(f"SHA1 must be 20 bytes, got {len(sha1_digest)}")
    if len(uuid) < 8:
        raise ValueError(f"UUID must be at least 8 bytes, got {len(uuid)}")

    store, instance = _get_wasm_instance()

    # Get exported functions and memory
    # wasmtime stubs type exports() return as a union; runtime types are correct
    exports = instance.exports(store)  # type: ignore[arg-type]
    memory = exports["memory"]
    get_input_sha1 = exports["getInputSha1"]
    get_input_uuid = exports["getInputUuid"]
    get_output = exports["getOutput"]
    calculate_hash = exports["calculateHash"]

    # Get pointers into WASM linear memory
    sha1_ptr = get_input_sha1(store)  # type: ignore[misc]
    uuid_ptr = get_input_uuid(store)  # type: ignore[misc]
    output_ptr = get_output(store)  # type: ignore[misc]

    # Write inputs into WASM memory
    mem_data = memory.data_ptr(store)  # type: ignore[union-attr]

    # Write SHA1 (20 bytes)
    for i in range(20):
        mem_data[sha1_ptr + i] = sha1_digest[i]

    # Write UUID (8 bytes)
    for i in range(8):
        mem_data[uuid_ptr + i] = uuid[i]

    # Execute the hash computation
    calculate_hash(store)  # type: ignore[misc]

    # Read 57-byte output
    result = bytes(mem_data[output_ptr + i] for i in range(HASHAB_SIZE))

    logger.debug("HASHAB computed: %s…", result[:4].hex())
    return result


def _compute_itunesdb_sha1_for_hashab(itdb_data: bytearray) -> bytes:
    """
    Compute SHA1 of iTunesDB with all hash fields zeroed for HASHAB.

    Zeroed fields before hashing:
    - db_id      (offset 0x18, 8 bytes)
    - unk_0x32   (offset 0x32, 20 bytes)
    - hash58     (offset 0x58, 20 bytes)
    - hash72     (offset 0x72, 46 bytes)
    - hashAB     (offset 0xAB, 57 bytes)

    We zero unk_0x32 (matching HASH58 behavior) because HASHAB devices
    (Nano 6G/7G) also maintain hash58 compatibility fields.
    """
    data = bytearray(itdb_data)

    data[OFFSET_DB_ID:OFFSET_DB_ID + 8] = b'\x00' * 8
    data[OFFSET_UNK_0x32:OFFSET_UNK_0x32 + 20] = b'\x00' * 20
    data[OFFSET_HASH58:OFFSET_HASH58 + 20] = b'\x00' * 20
    data[OFFSET_HASH72:OFFSET_HASH72 + 46] = b'\x00' * 46
    data[OFFSET_HASHAB:OFFSET_HASHAB + HASHAB_SIZE] = b'\x00' * HASHAB_SIZE

    return hashlib.sha1(bytes(data)).digest()


def write_hashab(itdb_data: bytearray, firewire_id: bytes) -> None:
    """
    Compute and write HASHAB signature to iTunesDB data in-place.

    Steps:
    1. Zero db_id, unk_0x32, hash58, hash72, hashAB
    2. Set hashing_scheme to 4 (HASHAB)
    3. Compute SHA1 of entire database
    4. Call WASM module with SHA1 + UUID
    5. Write 57-byte result at offset 0xAB
    6. Restore backed-up fields

    Args:
        itdb_data: Mutable bytearray of complete iTunesDB file
        firewire_id: 8+ byte FireWire GUID from /iPod_Control/Device/SysInfo

    Raises:
        ValueError: If iTunesDB is too small or FireWire ID is invalid
    """
    min_size = OFFSET_HASHAB + HASHAB_SIZE  # 0xAB + 57 = 0xE4 = 228
    if len(itdb_data) < min_size:
        raise ValueError(
            f"iTunesDB file too small ({len(itdb_data)} bytes), "
            f"need at least {min_size} (0x{min_size:X})"
        )

    if itdb_data[:4] != b'mhbd':
        raise ValueError("Invalid iTunesDB: expected 'mhbd' header")

    if len(firewire_id) < 8:
        raise ValueError(
            f"FireWire ID must be at least 8 bytes, got {len(firewire_id)}"
        )

    # Backup fields that will be zeroed for SHA1 computation
    backup_db_id = bytes(itdb_data[OFFSET_DB_ID:OFFSET_DB_ID + 8])
    backup_unk32 = bytes(itdb_data[OFFSET_UNK_0x32:OFFSET_UNK_0x32 + 20])

    # Set hashing scheme to HASHAB (4)
    itdb_data[OFFSET_HASHING_SCHEME:OFFSET_HASHING_SCHEME + 2] = \
        ITDB_CHECKSUM_HASHAB.to_bytes(2, 'little')

    # Compute SHA1 with hash fields zeroed
    sha1_digest = _compute_itunesdb_sha1_for_hashab(itdb_data)

    # Compute HASHAB via WASM
    signature = compute_hashab(sha1_digest, firewire_id[:8])

    if len(signature) != HASHAB_SIZE:
        raise RuntimeError(
            f"WASM returned {len(signature)} bytes, expected {HASHAB_SIZE}"
        )

    # Write signature to mhbd header
    itdb_data[OFFSET_HASHAB:OFFSET_HASHAB + HASHAB_SIZE] = signature

    # Restore backed-up fields
    itdb_data[OFFSET_DB_ID:OFFSET_DB_ID + 8] = backup_db_id
    itdb_data[OFFSET_UNK_0x32:OFFSET_UNK_0x32 + 20] = backup_unk32

    logger.info("HASHAB signature written at offset 0x%X (%d bytes)",
                OFFSET_HASHAB, HASHAB_SIZE)


def read_firewire_id(ipod_path: str) -> bytes:
    """Return the FireWire GUID for the connected iPod.

    Reads from the centralised DeviceInfo store.  Raises if not available.
    """
    from device_info import get_current_device
    device = get_current_device()
    if device is not None:
        fwid = device.firewire_id_bytes
        if fwid:
            return fwid
    raise RuntimeError(
        "FireWire GUID not available. Device info was not populated "
        "by the device scanner."
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python hashab.py <ipod_path> <itunesdb_path>")
        print("Example: python hashab.py /media/ipod /media/ipod/iPod_Control/iTunes/iTunesDB")
        sys.exit(1)

    ipod_path = sys.argv[1]
    itunesdb_path = sys.argv[2]

    try:
        firewire_id = read_firewire_id(ipod_path)
        print(f"FireWire ID: {firewire_id.hex()}")

        with open(itunesdb_path, 'rb') as f:
            itdb_data = bytearray(f.read())

        print(f"Read {len(itdb_data)} bytes from iTunesDB")

        write_hashab(itdb_data, firewire_id)
        print("HASHAB computed successfully!")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
