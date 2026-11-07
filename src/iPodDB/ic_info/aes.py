"""Typed boundary for the AES-ECB byte interface used by account sessions."""

from typing import Literal, Protocol, cast

from Crypto.Cipher import AES


class BlockCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _EcbFactory(Protocol):
    def __call__(self, key: bytes, mode: Literal[1]) -> BlockCipher: ...


# The upstream AES.new overload has an untyped CTR counter parameter. Isolate
# that stub defect here; this adapter exposes only fully typed ECB operations.
_NEW_ECB = cast("_EcbFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]


def ecb_cipher(key: bytes) -> BlockCipher:
    """Create the standard AES cipher used for the native session layer."""
    return _NEW_ECB(key, AES.MODE_ECB)
