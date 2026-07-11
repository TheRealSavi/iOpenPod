"""Lightweight secret codec for on-device settings."""

from __future__ import annotations

import base64
import hashlib
import os


def normalized_device_mount_key(ipod_root: str) -> str:
    """Return a stable normalized key for a mounted iPod path."""

    if not ipod_root:
        return ""
    return os.path.normcase(os.path.abspath(ipod_root))


def normalized_device_identity_value(value: object) -> str:
    """Normalize device identity values for use in a secret key hint."""

    return str(value or "").replace(" ", "").strip().upper()


def _device_key_candidates(
    device_key: str = "",
    ipod_root: str = "",
    stored_hint: str = "",
) -> list[str]:
    mount_key = normalized_device_mount_key(ipod_root)
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        candidates.append(candidate)

    add(stored_hint)
    add(device_key)

    for candidate in tuple(candidates):
        if mount_key and candidate not in {mount_key, "unknown-device"}:
            # Earlier builds mixed stable device identity with the mount path.
            add(f"{candidate}|{mount_key}")

    add(mount_key)
    if not candidates:
        add("unknown-device")
    return candidates


def _secret_key(device_key: str, nonce: bytes = b"") -> bytes:
    seed = (
        f"iOpenPod device settings v1|{device_key or 'unknown-device'}"
    ).encode()
    return hashlib.sha256(seed + nonce).digest()


def _xor_stream(key: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_secret(value: str, device_key: str) -> str:
    """Encode a device-scoped secret for storage on the iPod."""

    if not value:
        return ""
    raw = value.encode()
    nonce = os.urandom(16)
    key = _secret_key(device_key, nonce)
    stream = _xor_stream(key, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
    return "xor1:{nonce}:{cipher}".format(
        nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
        cipher=base64.urlsafe_b64encode(cipher).decode("ascii"),
    )


def decrypt_secret(value: str, device_key: str) -> str:
    """Decode a secret for one candidate device key."""

    if not value or not isinstance(value, str):
        return ""
    if not value.startswith("xor1:"):
        return value
    try:
        _prefix, nonce_b64, cipher_b64 = value.split(":", 2)
        nonce = base64.urlsafe_b64decode(nonce_b64.encode("ascii"))
        cipher = base64.urlsafe_b64decode(cipher_b64.encode("ascii"))
        key = _secret_key(device_key, nonce)
        stream = _xor_stream(key, len(cipher))
        raw = bytes(a ^ b for a, b in zip(cipher, stream, strict=True))
        return raw.decode()
    except Exception:
        return ""


def decrypt_secret_for_device(
    value: str,
    *,
    device_key: str,
    ipod_root: str = "",
    stored_hint: str = "",
) -> str:
    """Decode a secret, trying current and historical device key candidates."""

    if not value or not isinstance(value, str):
        return ""
    if not value.startswith("xor1:"):
        return value

    for candidate in _device_key_candidates(
        device_key=device_key,
        ipod_root=ipod_root,
        stored_hint=stored_hint,
    ):
        decrypted = decrypt_secret(value, candidate)
        if decrypted:
            return decrypted
    return ""
