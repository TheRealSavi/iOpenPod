"""Pure database signature finalization and verification.

Database field locations come from the shared definition. HASHAB scheme and
random-envelope evidence is recorded in ADR-0169.
"""

import hashlib
import hmac
import importlib.resources
import math
from base64 import b64decode
from dataclasses import dataclass
from functools import cache
from typing import Protocol, cast

import wasmtime
from Crypto.Cipher import AES

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.shared.binary_struct import binary_fields


class _AESBlockCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _AESFactory(Protocol):
    def __call__(
        self, key: bytes, mode: int, iv: bytes | None = None
    ) -> _AESBlockCipher: ...


# PyCryptodome's overload includes an untyped CTR ``counter`` parameter, which
# makes the complete ``AES.new`` member partially Unknown to strict Pyright even
# for the fully typed CBC and ECB calls used here.  Keep that stub defect at one
# adapter boundary while exposing only the modes and byte interface we consume.
_AES_NEW = cast("_AESFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]


def _multiply(left: int, right: int) -> int:
    value = 0
    for _ in range(8):
        if right & 1:
            value ^= left
        left = ((left << 1) ^ (0x11B if left & 0x80 else 0)) & 255
        right >>= 1
    return value


def _substitute(value: int) -> int:
    inverse = 0
    if value:
        inverse = 1
        for _ in range(254):
            inverse = _multiply(inverse, value)
    result = inverse ^ 0x63
    for shift in range(1, 5):
        result ^= ((inverse << shift) | (inverse >> (8 - shift))) & 255
    return result


_SBOX = bytes(_substitute(i) for i in range(256))
_INVERSE = bytes(_SBOX.index(i) for i in range(256))
_SEED = bytes.fromhex("6723fe304533f890992107c1d012b2a10781")
_FIELDS = {field.attribute_name: field.schema for field in binary_fields(MhbdHeader)}


def _hash58_key(guid: bytes) -> bytes:
    if len(guid) != 8:
        raise ValueError("HASH58 requires exactly eight FireWire GUID bytes.")
    derived = bytearray()
    for left, right in zip(guid[::2], guid[1::2], strict=True):
        value = math.lcm(left, right) if left and right else 1
        for part in (value >> 8, value & 255):
            derived.extend((_SBOX[part], _INVERSE[part]))
    return hashlib.sha1(_SEED + derived).digest()


def sign_hash58(data: bytes, guid: bytes) -> bytes:
    key = _hash58_key(guid)
    if data[:4] != b"mhbd" or len(data) < 12:
        raise ValueError("HASH58 requires an iTunesDB root.")
    header_size = int.from_bytes(data[4:8], "little")
    if header_size > len(data):
        raise ValueError("The iTunesDB root header is truncated.")
    output = bytearray(data)
    normalized = bytearray(data)
    for name in ("db_id", "unk0x32", "hash58", "hashing_scheme"):
        schema = _FIELDS[name]
        if schema.offset + schema.size > header_size:
            raise ValueError(f"The retained root header cannot hold {name}.")
        normalized[schema.offset : schema.offset + schema.size] = bytes(schema.size)
    scheme = _FIELDS["hashing_scheme"]
    normalized[scheme.offset : scheme.offset + scheme.size] = (1).to_bytes(
        scheme.size, "little"
    )
    output[scheme.offset : scheme.offset + scheme.size] = (1).to_bytes(
        scheme.size, "little"
    )
    signature = _FIELDS["hash58"]
    output[signature.offset : signature.offset + signature.size] = hmac.digest(
        key, normalized, "sha1"
    )
    return bytes(output)


def verify_hash58(data: bytes, guid: bytes) -> bool:
    return hmac.compare_digest(data, sign_hash58(data, guid))


_HASH72_KEY = bytes.fromhex("618ca10dc7f57fd3b4723e08157463d7")


@dataclass(frozen=True, slots=True)
class Hash72Material:
    uuid: bytes
    random_part: bytes
    iv: bytes


def parse_hash_info(data: bytes) -> Hash72Material:
    """Parse the device-bound 54-byte ``HashInfo`` record."""

    if len(data) != 54 or data[:6] != b"HASHv0":
        raise ValueError("HashInfo must be one 54-byte HASHv0 record.")
    return Hash72Material(data[6:26], data[26:38], data[38:54])


def compute_hash58(guid: bytes, payload: bytes) -> bytes:
    """Return the HASH58 HMAC for an arbitrary payload such as a CBK digest."""

    return hmac.digest(_hash58_key(guid), payload, "sha1")


def compute_hash72_signature(digest: bytes, iv: bytes, random_part: bytes) -> bytes:
    """Return the 46-byte HASH72 envelope for one 20-byte digest."""

    if len(digest) != 20:
        raise ValueError("HASH72 requires a 20-byte SHA1 digest.")
    if len(iv) != 16 or len(random_part) != 12:
        raise ValueError("HASH72 requires a 16-byte IV and 12 random bytes.")
    encrypted = _AES_NEW(_HASH72_KEY, AES.MODE_CBC, iv).encrypt(digest + random_part)
    return b"\x01\x00" + random_part + encrypted


def sign_hash72(
    data: bytes,
    iv: bytes,
    random_part: bytes,
    *,
    hashing_scheme: int = 2,
) -> bytes:
    """Finalize one physical iTunesDB/iTunesCDB with a HASH72 signature.

    ``iv`` and ``random_part`` are device-bound material retained in the
    device's HashInfo record or recoverable from its valid iTunes signature.
    They are explicit byte inputs so iPodDB remains independent of Storage.
    A retained Classic dual signature uses scheme 1 before HASH58 is signed;
    standalone HASH72 output uses scheme 2.
    """

    if len(iv) != 16 or len(random_part) != 12:
        raise ValueError("HASH72 requires a 16-byte IV and 12 random bytes.")
    if hashing_scheme not in (1, 2):
        raise ValueError("HASH72 requires a HASH58 or HASH72 hashing scheme.")
    output, normalized, header_size = _signature_buffers(data)
    _zero_signature_field(normalized, header_size, "db_id")
    _zero_signature_field(normalized, header_size, "hash58")
    _zero_signature_field(normalized, header_size, "hash72")
    _set_scheme(output, normalized, header_size, hashing_scheme)
    digest = hashlib.sha1(normalized).digest()
    signature = compute_hash72_signature(digest, iv, random_part)
    schema = _FIELDS["hash72"]
    output[schema.offset : schema.offset + schema.size] = signature
    return bytes(output)


def verify_hash72(
    data: bytes,
    iv: bytes,
    random_part: bytes,
    *,
    hashing_scheme: int = 2,
) -> bool:
    return hmac.compare_digest(
        data, sign_hash72(data, iv, random_part, hashing_scheme=hashing_scheme)
    )


@cache
def _hashab_module() -> tuple[wasmtime.Engine, wasmtime.Module]:
    encoded = importlib.resources.files("iPodDB.iTunesDB.writer").joinpath(
        "calcHashAB.wasm.b64"
    )
    engine = wasmtime.Engine()
    module = wasmtime.Module(engine, b64decode(encoded.read_bytes()))
    return engine, module


_HASHAB_DEFAULT_RANDOM = b"ABCDEFGHIJKLMNOPQRSTUVW"
# Inverse of the exposed random-byte positions in upstream calcHashAB.c's
# permutation_56 (commit f80d46432204c6238cad7d8ca3b3dd52ea66836b).
_HASHAB_RANDOM_OFFSETS = (
    23,
    13,
    29,
    12,
    37,
    8,
    4,
    6,
    10,
    41,
    53,
    27,
    5,
    43,
    28,
    45,
    16,
    46,
    34,
    9,
    19,
    2,
    56,
)


def compute_hashab(
    digest: bytes,
    guid: bytes,
    *,
    random_part: bytes = _HASHAB_DEFAULT_RANDOM,
) -> bytes:
    """Return a HASHAB envelope, retaining deterministic authoring by default.

    Verification supplies the random bytes recovered from the stored envelope.
    The pinned upstream wrapper has no random-input export, so replace its unique
    fixed input in this fresh instance's memory. Never modify the bundled asset
    or share writable memory between calls.
    """

    if len(digest) != 20:
        raise ValueError("HASHAB requires a 20-byte SHA1 digest.")
    if len(guid) != 8:
        raise ValueError("HASHAB requires exactly eight FireWire GUID bytes.")
    if len(random_part) != len(_HASHAB_DEFAULT_RANDOM):
        raise ValueError("HASHAB requires exactly 23 random bytes.")
    engine, module = _hashab_module()
    store = wasmtime.Store(engine)
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)
    memory = cast("wasmtime.Memory", exports["memory"])
    get_sha1 = cast("wasmtime.Func", exports["getInputSha1"])
    get_guid = cast("wasmtime.Func", exports["getInputUuid"])
    get_output = cast("wasmtime.Func", exports["getOutput"])
    calculate = cast("wasmtime.Func", exports["calculateHash"])
    sha1_pointer = int(get_sha1(store))
    guid_pointer = int(get_guid(store))
    output_pointer = int(get_output(store))
    initial_memory = bytes(memory.read(store, 0, memory.data_len(store)))
    if initial_memory.count(_HASHAB_DEFAULT_RANDOM) != 1:
        raise RuntimeError("The pinned HASHAB module has an unexpected random input.")
    memory.write(store, random_part, initial_memory.index(_HASHAB_DEFAULT_RANDOM))
    memory.write(store, digest, sha1_pointer)
    memory.write(store, guid, guid_pointer)
    calculate(store)
    return bytes(memory.read(store, output_pointer, output_pointer + 57))


def _hashab_buffers(data: bytes) -> tuple[bytearray, bytearray, int]:
    output, normalized, header_size = _signature_buffers(data)
    for name in ("db_id", "unk0x32", "hash58", "hash72", "hashab"):
        _zero_signature_field(normalized, header_size, name)
    return output, normalized, header_size


def sign_hashab(data: bytes, guid: bytes) -> bytes:
    """Sign the final physical bytes with the published HASHAB scheme (3)."""

    output, normalized, header_size = _hashab_buffers(data)
    _set_scheme(output, normalized, header_size, 3)
    schema = _FIELDS["hashab"]
    output[schema.offset : schema.offset + schema.size] = compute_hashab(
        hashlib.sha1(normalized).digest(), guid
    )
    return bytes(output)


def verify_hashab_signature(digest: bytes, guid: bytes, signature: bytes) -> bool:
    """Verify a stored HASHAB envelope using its own exposed random bytes."""

    if (
        len(digest) != 20
        or len(guid) != 8
        or len(signature) != 57
        or signature[:2] != b"\x03\x00"
    ):
        return False
    random_part = bytes(signature[offset] for offset in _HASHAB_RANDOM_OFFSETS)
    expected = compute_hashab(digest, guid, random_part=random_part)
    return hmac.compare_digest(signature, expected)


def verify_hashab(data: bytes, guid: bytes) -> bool:
    """Verify HASHAB over the stored scheme, without re-signing the database."""

    try:
        _output, normalized, _header_size = _hashab_buffers(data)
    except ValueError:
        return False
    scheme = _FIELDS["hashing_scheme"]
    if int.from_bytes(data[scheme.offset : scheme.offset + scheme.size], "little") != 3:
        return False
    schema = _FIELDS["hashab"]
    signature = data[schema.offset : schema.offset + schema.size]
    return verify_hashab_signature(hashlib.sha1(normalized).digest(), guid, signature)


def has_hash72_signature(data: bytes) -> bool:
    """Identify a retained HASH72 envelope using the shared root field layout."""

    schema = _FIELDS["hash72"]
    return (
        len(data) >= schema.offset + schema.size
        and data[schema.offset : schema.offset + 2] == b"\x01\x00"
    )


def extract_hash72_material(data: bytes) -> tuple[bytes, bytes]:
    """Recover the IV and random bytes from one internally valid HASH72 record.

    Apple designed HASH72 so the device-specific IV can be recovered from a
    previously signed database. The complete encrypted envelope is checked against
    the retained database digest and clear random bytes before returning. This
    establishes material integrity, not device identity; callers still bind the
    artifact to the selected device.
    """

    _output, normalized, header_size = _signature_buffers(data)
    for name in ("db_id", "hash58", "hash72"):
        _zero_signature_field(normalized, header_size, name)
    schema = _FIELDS["hash72"]
    signature = data[schema.offset : schema.offset + schema.size]
    if len(signature) != schema.size:
        raise ValueError("The retained database has no recoverable HASH72 signature.")
    return recover_hash72_signature(hashlib.sha1(normalized).digest(), signature)


def recover_hash72_signature(digest: bytes, signature: bytes) -> tuple[bytes, bytes]:
    """Recover and verify the material in one database or checksum-book envelope."""

    if len(digest) != 20:
        raise ValueError("HASH72 recovery requires a 20-byte SHA1 digest.")
    if len(signature) != 46 or signature[:2] != b"\x01\x00":
        raise ValueError("The retained artifact has no recoverable HASH72 signature.")
    random_part = signature[2:14]
    first_plain_xor_iv = _AES_NEW(_HASH72_KEY, AES.MODE_ECB).decrypt(signature[14:30])
    iv = bytes(
        left ^ right
        for left, right in zip(first_plain_xor_iv, digest[:16], strict=True)
    )
    plaintext = _AES_NEW(_HASH72_KEY, AES.MODE_CBC, iv).decrypt(signature[14:])
    if not hmac.compare_digest(plaintext, digest + random_part):
        raise ValueError("The retained artifact has an invalid HASH72 signature.")
    return iv, random_part


def _signature_buffers(data: bytes) -> tuple[bytearray, bytearray, int]:
    if data[:4] != b"mhbd" or len(data) < 12:
        raise ValueError("A database signature requires an iTunesDB root.")
    header_size = int.from_bytes(data[4:8], "little")
    if not 12 <= header_size <= len(data):
        raise ValueError("The iTunesDB root header is truncated.")
    return bytearray(data), bytearray(data), header_size


def _zero_signature_field(data: bytearray, header_size: int, name: str) -> None:
    schema = _FIELDS[name]
    if schema.offset + schema.size > header_size:
        raise ValueError(f"The retained root header cannot hold {name}.")
    data[schema.offset : schema.offset + schema.size] = bytes(schema.size)


def _set_scheme(
    output: bytearray,
    normalized: bytearray,
    header_size: int,
    value: int,
) -> None:
    scheme = _FIELDS["hashing_scheme"]
    if scheme.offset + scheme.size > header_size:
        raise ValueError("The retained root header cannot hold hashing_scheme.")
    encoded = value.to_bytes(scheme.size, "little")
    output[scheme.offset : scheme.offset + scheme.size] = encoded
    normalized[scheme.offset : scheme.offset + scheme.size] = encoded
