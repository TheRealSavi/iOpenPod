"""Create release keys and signed feeds. Never print a private key or publish here."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import plistlib
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from Crypto.Signature import eddsa
from scripts.package_updates import public_keys, sparkle_sdk

from iOpenPod.app.updates.releases import (
    CURRENT_UPDATER_PROTOCOL,
    MAX_ARCHIVE,
    REPOSITORY,
    SIGNING_CONTEXT,
    TARGET_LAYOUTS,
    TARGET_SUFFIXES,
    ReleaseFloor,
    read_json,
    verify_release,
    version_tuple,
)
from storage.host_installation import private_directory

if TYPE_CHECKING:
    from typing import IO

ROOT = Path(__file__).resolve().parents[1]
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def generate_key(parent: Path, root: Path = ROOT) -> Path:
    parent = parent.resolve(strict=True)
    if parent.is_relative_to(root.resolve()):
        raise ValueError("Keep the private signing key outside the repository")
    directory = private_directory(parent, "iOpenPod-release-key-")
    seed = os.urandom(32)
    key = eddsa.import_private_key(seed)
    path = directory / "private-key.txt"
    with path.open("xb") as stream:
        stream.write(base64.b64encode(seed) + b"\n")
    public = base64.b64encode(key.public_key().export_key(format="raw")).decode()
    # Do not silently rotate a published trust root.
    if public_keys(root):
        (directory / "public-key.json").write_text(
            json.dumps({"public_keys": [public]}) + "\n"
        )
    else:
        (root / "packaging/update-keys.json").write_text(
            json.dumps({"public_keys": [public]}, indent=2) + "\n"
        )
    return path


def _hash(stream: IO[bytes]) -> str:
    result = hashlib.sha256()
    while chunk := stream.read(256 * 1024):
        result.update(chunk)
    return result.hexdigest()


def _identity(data: bytes, target: str, version: str, keys: tuple[str, ...]) -> None:
    identity = read_json(data)
    if (
        type(identity.get("schema")) is not int
        or identity.get("schema") != 1
        or identity.get("product") != "iOpenPod"
        or identity.get("version") != version
        or identity.get("target") != target
        or identity.get("layout") != TARGET_LAYOUTS[target]
        or identity.get("public_keys") != list(keys)
    ):
        raise ValueError(
            "The archived app does not embed the release version and trust keys"
        )


def executable_digest(
    archive: Path, target: str, version: str, keys: tuple[str, ...]
) -> str:
    if target.startswith("linux"):
        prefix = f"iOpenPod/versions/{version}"
        with tarfile.open(archive) as package:
            identity = package.extractfile(
                prefix + "/_internal/updates/installation.json"
            )
            executable = package.extractfile(prefix + "/iOpenPod")
            if identity is None or executable is None:
                raise ValueError("Linux release lacks managed update resources")
            with identity, executable:
                _identity(identity.read(16 * 1024), target, version, keys)
                return _hash(executable)
    with zipfile.ZipFile(archive) as package:
        if target.startswith("macos"):
            prefix = "iOpenPod.app/Contents/"
            _identity(
                package.read(prefix + "Resources/updates/installation.json"),
                target,
                version,
                keys,
            )
            info = plistlib.loads(package.read(prefix + "Info.plist"))
            if (
                info.get("SUPublicEDKey") != keys[0]
                or info.get("CFBundleVersion") != version
            ):
                raise ValueError(
                    "macOS release does not pin the signing key and version"
                )
            with package.open(prefix + "MacOS/iOpenPod") as executable:
                return _hash(executable)
        if package.namelist() != ["iOpenPod.exe"]:
            raise ValueError("Windows release must contain only iOpenPod.exe")
        archives = import_module("PyInstaller.archive.readers")

        with tempfile.TemporaryDirectory(prefix="iOpenPod-release-inspect-") as temp:
            executable_path = Path(temp) / "iOpenPod.exe"
            with (
                package.open("iOpenPod.exe") as source,
                executable_path.open("xb") as destination,
            ):
                import shutil

                shutil.copyfileobj(source, destination, 256 * 1024)
            reader = archives.CArchiveReader(str(executable_path))
            identity_data = reader.extract("updates\\installation.json")
            if not isinstance(identity_data, bytes):
                raise ValueError("Windows release lacks update identity")
            _identity(identity_data, target, version, keys)
            with executable_path.open("rb") as source:
                return _hash(source)


def signed_envelope(payload: dict[str, object], seed: bytes) -> bytes:
    key = eddsa.import_private_key(seed)
    public = key.public_key().export_key(format="raw")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = eddsa.new(key, "rfc8032").sign(SIGNING_CONTEXT + encoded)
    return (
        json.dumps(
            {
                "payload": base64.b64encode(encoded).decode(),
                "signatures": [
                    {
                        "key_id": hashlib.sha256(public).hexdigest(),
                        "signature": base64.b64encode(signature).decode(),
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    ).encode()


def create_feed(
    archives: Path,
    output: Path,
    version: str,
    seed: bytes,
    *,
    root: Path = ROOT,
    previous: bytes | None = None,
    now: datetime | None = None,
) -> None:
    version_tuple(version)
    keys = public_keys(root)
    key = eddsa.import_private_key(seed)
    if (
        not keys
        or base64.b64encode(key.public_key().export_key(format="raw")).decode()
        != keys[0]
    ):
        raise ValueError(
            "The signing credential does not match the primary embedded trust key"
        )
    clock = now or datetime.now(UTC)
    floor = ReleaseFloor()
    if previous is not None:
        # Expired feeds remain authenticated history; they are never installable.
        envelope = read_json(previous)
        payload = read_json(base64.b64decode(str(envelope["payload"]), validate=True))
        old = verify_release(
            previous, keys, now=datetime.fromisoformat(str(payload["issued"]))
        )
        floor = ReleaseFloor(old.sequence, old.version, old.digest)
        if version_tuple(version) < version_tuple(old.version):
            raise ValueError("Refusing to publish a feed rollback")
    output.mkdir(parents=True, exist_ok=False)
    assets: list[dict[str, object]] = []
    for target, suffix in TARGET_SUFFIXES.items():
        archive = archives / f"iOpenPod-{version}-{suffix}"
        if not 0 < archive.stat().st_size <= MAX_ARCHIVE:
            raise ValueError("Release archive exceeds the supported size")
        with archive.open("rb") as stream:
            digest = _hash(stream)
        item: dict[str, object] = {
            "target": target,
            "layout": TARGET_LAYOUTS[target],
            "updater_protocol": CURRENT_UPDATER_PROTOCOL,
            "size": archive.stat().st_size,
            "sha256": digest,
            "executable_sha256": executable_digest(archive, target, version, keys),
            "minimum_os": "12.3"
            if target.startswith("macos")
            else "2.39"
            if target.startswith("linux")
            else "10.0.17763",
        }
        if target.startswith("macos"):
            # Sparkle uses PureEdDSA over the complete ZIP, not the JSON digest.
            signature = base64.b64encode(
                eddsa.new(key, "rfc8032").sign(archive.read_bytes())
            ).decode()
            item["sparkle_signature"] = signature
            _appcast(
                output / f"{target}.xml",
                version,
                archive.name,
                archive.stat().st_size,
                signature,
            )
            signer = sparkle_sdk(root) / "bin/sign_update"
            secret_input = base64.b64encode(seed) + b"\n"
            # Validate the archive with Sparkle's own verifier as well as signing
            # and re-verifying its XML representation. No credentials in argv.
            for arguments in (
                ["--verify", str(archive), signature],
                [str(output / f"{target}.xml")],
                ["--verify", str(output / f"{target}.xml")],
            ):
                subprocess.run(
                    [str(signer), "--ed-key-file", "-", *arguments],
                    input=secret_input,
                    capture_output=True,
                    check=True,
                )
        assets.append(item)
    encoded = signed_envelope(
        {
            "schema": 1,
            "product": "iOpenPod",
            "track": "stable",
            "repository": REPOSITORY,
            "version": version,
            "tag": f"v{version}",
            "sequence": max(int(clock.timestamp()), floor.sequence + 1),
            "issued": clock.isoformat(),
            "expires": (clock + timedelta(days=45)).isoformat(),
            "assets": assets,
        },
        seed,
    )
    verify_release(encoded, keys, now=clock, floor=floor)
    (output / "stable.json").write_bytes(encoded)


def _appcast(
    path: Path, version: str, filename: str, size: int, signature: str
) -> None:
    ET.register_namespace("sparkle", SPARKLE_NS)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "iOpenPod updates"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"iOpenPod {version}"
    ET.SubElement(item, f"{{{SPARKLE_NS}}}version").text = version
    ET.SubElement(item, f"{{{SPARKLE_NS}}}minimumSystemVersion").text = "12.3"
    ET.SubElement(
        item,
        "enclosure",
        {
            "url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{filename}",
            "length": str(size),
            "type": "application/octet-stream",
            f"{{{SPARKLE_NS}}}edSignature": signature,
        },
    )
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate-key").add_argument("private_parent", type=Path)
    create = commands.add_parser("create")
    create.add_argument("version")
    create.add_argument("archives", type=Path)
    create.add_argument("output", type=Path)
    create.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.command == "generate-key":
        print(f"Private key saved to {generate_key(args.private_parent)}")
        return
    secret = os.environ.pop("IOPENPOD_UPDATE_PRIVATE_KEY", "")
    seed = base64.b64decode(secret, validate=True)
    if len(seed) != 32:
        raise ValueError(
            "IOPENPOD_UPDATE_PRIVATE_KEY must contain a base64 Ed25519 seed"
        )
    create_feed(
        args.archives,
        args.output,
        args.version,
        seed,
        previous=args.previous.read_bytes() if args.previous else None,
    )


if __name__ == "__main__":
    main()
