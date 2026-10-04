"""Authenticated release descriptions; no networking or filesystem mutation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from Crypto.Signature import eddsa

REPOSITORY = "TheRealSavi/iOpenPod"
FEED_URL = (
    "https://raw.githubusercontent.com/TheRealSavi/iOpenPod/update-feed/stable.json"
)
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
MAX_METADATA = 256 * 1024
MAX_ARCHIVE = 2 * 1024**3
MAX_LIFETIME = timedelta(days=90)
SIGNING_CONTEXT = b"iOpenPod application release metadata v1\x00"
TARGET_LAYOUTS = {
    "windows-x86_64": "windows-onefile-v1",
    "macos-arm64": "macos-app-v1",
    "macos-x86_64": "macos-app-v1",
    "linux-x86_64": "linux-managed-v1",
}
TARGET_SUFFIXES = {
    "windows-x86_64": "Windows-x86_64.zip",
    "macos-arm64": "sparkle-update-macOS-arm64.zip",
    "macos-x86_64": "sparkle-update-macOS-x86_64.zip",
    "linux-x86_64": "Linux-x86_64.tar.gz",
}
CURRENT_UPDATER_PROTOCOL = 2
# Protocol 1 is immutable: released clients derive these exact archive names.
_LEGACY_TARGET_SUFFIXES = {
    "windows-x86_64": "Windows-AMD64.zip",
    "macos-arm64": "macOS-arm64.zip",
    "macos-x86_64": "macOS-x86_64.zip",
    "linux-x86_64": "Linux-x86_64.tar.gz",
}


def version_tuple(value: str) -> tuple[int, int, int]:
    if re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value) is None:
        raise ValueError(f"Unsupported release version: {value}")
    parts = tuple(int(part) for part in value.split("."))
    if any(part > 65535 for part in parts):
        raise ValueError("Release version component exceeds 65535")
    return parts[0], parts[1], parts[2]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a metadata object")
    return cast("dict[str, object]", value)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate metadata field: {key}")
        result[key] = value
    return result


def read_json(data: bytes) -> dict[str, object]:
    if len(data) > MAX_METADATA:
        raise ValueError("Update metadata exceeds its size limit")
    return _object(json.loads(data, object_pairs_hook=_pairs))


def text_field(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result or len(result) > 2048:
        raise ValueError(f"Invalid update field: {key}")
    return result


def integer_field(value: dict[str, object], key: str, maximum: int) -> int:
    result = value.get(key)
    if type(result) is not int or not 0 < result <= maximum:
        raise ValueError(f"Invalid update field: {key}")
    return result


def _timestamp(value: dict[str, object], key: str) -> datetime:
    result = datetime.fromisoformat(text_field(value, key))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("Update timestamps must be UTC")
    return result


def decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid Ed25519 public key") from error
    if len(raw) != 32:
        raise ValueError("Ed25519 public keys must contain 32 bytes")
    eddsa.import_public_key(raw)
    return raw


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    target: str
    layout: str
    version: str
    size: int
    sha256: str
    executable_sha256: str
    minimum_os: str
    sparkle_signature: str = ""
    updater_protocol: int = 1

    @property
    def filename(self) -> str:
        suffixes = {1: _LEGACY_TARGET_SUFFIXES, 2: TARGET_SUFFIXES}[
            self.updater_protocol
        ]
        return f"iOpenPod-{self.version}-{suffixes[self.target]}"

    @property
    def url(self) -> str:
        return f"{RELEASES_URL}/download/v{self.version}/{self.filename}"


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    sequence: int
    issued: datetime
    expires: datetime
    digest: str
    assets: tuple[ReleaseAsset, ...]

    def asset(self, target: str) -> ReleaseAsset:
        for asset in self.assets:
            if asset.target == target:
                return asset
        raise ValueError(f"This release has no supported download for {target}")


@dataclass(frozen=True, slots=True)
class ReleaseFloor:
    """Retained authenticated evidence prevents ordinary rollback and equivocation."""

    sequence: int = 0
    version: str = "0.0.0"
    digest: str = ""


_INITIAL_FLOOR = ReleaseFloor()


def _digest(value: dict[str, object], field: str) -> str:
    result = text_field(value, field)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        raise ValueError(f"Invalid SHA-256 field: {field}")
    return result


def verify_release(
    data: bytes,
    public_keys: tuple[str, ...],
    *,
    now: datetime | None = None,
    floor: ReleaseFloor = _INITIAL_FLOOR,
) -> Release:
    """Authenticate exact payload bytes before interpreting installation metadata."""
    envelope = read_json(data)
    encoded = envelope.get("payload")
    if not isinstance(encoded, str):
        raise ValueError("Missing signed release payload")
    payload = base64.b64decode(encoded, validate=True)
    raw_signatures = envelope.get("signatures")
    if not isinstance(raw_signatures, list):
        raise ValueError("Missing release signatures")
    signatures = cast("list[object]", raw_signatures)
    if not 1 <= len(signatures) <= 8:
        raise ValueError("Missing release signatures")
    trusted = {hashlib.sha256(decode_key(key)).hexdigest(): key for key in public_keys}
    authenticated = False
    for item in signatures:
        signature_entry = _object(item)
        key = trusted.get(text_field(signature_entry, "key_id"))
        if key is None:
            continue
        try:
            eddsa.new(eddsa.import_public_key(decode_key(key)), "rfc8032").verify(
                SIGNING_CONTEXT + payload,
                base64.b64decode(
                    text_field(signature_entry, "signature"), validate=True
                ),
            )
        except (ValueError, binascii.Error):
            continue
        authenticated = True
        break
    if not authenticated:
        raise ValueError("The release is not signed by a trusted update key")
    value = read_json(payload)
    if (
        type(value.get("schema")) is not int
        or value.get("schema") != 1
        or value.get("product") != "iOpenPod"
        or value.get("track") != "stable"
    ):
        raise ValueError("Unsupported update metadata identity or format")
    version = text_field(value, "version")
    version_tuple(version)
    if value.get("tag") != f"v{version}" or value.get("repository") != REPOSITORY:
        raise ValueError("Release tag or repository does not match its version")
    sequence = integer_field(value, "sequence", 2**53 - 1)
    issued, expires = _timestamp(value, "issued"), _timestamp(value, "expires")
    clock = now or datetime.now(UTC)
    if issued > clock + timedelta(minutes=5) or expires <= clock:
        raise ValueError("Update metadata is expired or not yet valid")
    if not timedelta(0) < expires - issued <= MAX_LIFETIME:
        raise ValueError("Update metadata has an invalid validity interval")
    digest = hashlib.sha256(payload).hexdigest()
    if sequence < floor.sequence or version_tuple(version) < version_tuple(
        floor.version
    ):
        raise ValueError("Update metadata would roll back the trusted release history")
    if sequence == floor.sequence and digest != floor.digest:
        raise ValueError("Conflicting update metadata uses the same sequence")
    raw_entries = value.get("assets")
    if not isinstance(raw_entries, list):
        raise ValueError("Invalid update asset collection")
    entries = cast("list[object]", raw_entries)
    if not 1 <= len(entries) <= len(TARGET_LAYOUTS):
        raise ValueError("Invalid update asset collection")
    assets: list[ReleaseAsset] = []
    for entry in entries:
        item = _object(entry)
        target = text_field(item, "target")
        if target not in TARGET_LAYOUTS or any(
            asset.target == target for asset in assets
        ):
            raise ValueError("Unknown or duplicate update target")
        if (
            item.get("layout") != TARGET_LAYOUTS[target]
            or type(item.get("updater_protocol")) is not int
            or item.get("updater_protocol") not in (1, CURRENT_UPDATER_PROTOCOL)
        ):
            raise ValueError(
                "This release requires a different installer; update manually"
            )
        signature = item.get("sparkle_signature", "")
        if not isinstance(signature, str):
            raise ValueError("Invalid Sparkle signature")
        if (
            target.startswith("macos")
            and len(base64.b64decode(signature, validate=True)) != 64
        ):
            raise ValueError("Missing Sparkle archive signature")
        assets.append(
            ReleaseAsset(
                target,
                TARGET_LAYOUTS[target],
                version,
                integer_field(item, "size", MAX_ARCHIVE),
                _digest(item, "sha256"),
                _digest(item, "executable_sha256"),
                text_field(item, "minimum_os"),
                signature,
                integer_field(item, "updater_protocol", CURRENT_UPDATER_PROTOCOL),
            )
        )
    return Release(version, sequence, issued, expires, digest, tuple(assets))
