"""Pin updater build evidence and the native Sparkle framework."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from iOpenPod.app.updates.releases import FEED_URL, TARGET_LAYOUTS, decode_key

SPARKLE_VERSION = "2.10.0"
SPARKLE_SHA256 = "c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c"
SPARKLE_SIZE = 16_319_840
SPARKLE_URL = f"https://github.com/sparkle-project/Sparkle/releases/download/{SPARKLE_VERSION}/Sparkle-{SPARKLE_VERSION}.tar.xz"


def public_keys(root: Path) -> tuple[str, ...]:
    decoded: object = json.loads((root / "packaging/update-keys.json").read_bytes())
    if not isinstance(decoded, dict):
        raise ValueError("Invalid release public-key configuration")
    value = cast("dict[str, object]", decoded)
    raw_keys = value.get("public_keys")
    if not isinstance(raw_keys, list):
        raise ValueError("Invalid release public-key configuration")
    keys = cast("list[object]", raw_keys)
    if len(keys) > 8 or not all(isinstance(key, str) for key in keys):
        raise ValueError("Invalid release public-key configuration")
    result = tuple(cast("list[str]", keys))
    for key in result:
        decode_key(key)
    return result


def write_build_identity(root: Path, generated: Path, version: str) -> None:
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    target = (
        {"win32": "windows", "darwin": "macos", "linux": "linux"}[sys.platform]
        + "-"
        + arch
    )
    directory = generated / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "installation.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "product": "iOpenPod",
                "version": version,
                "target": target,
                "layout": TARGET_LAYOUTS[target],
                "public_keys": public_keys(root),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def sparkle_sdk(root: Path) -> Path:
    destination = root / "build" / f"Sparkle-{SPARKLE_VERSION}"
    archive = root / "build" / f"Sparkle-{SPARKLE_VERSION}.tar.xz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with (
            urllib.request.urlopen(SPARKLE_URL, timeout=60) as response,
            archive.open("xb") as stream,
        ):
            received = 0
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > SPARKLE_SIZE:
                    raise ValueError("Sparkle download exceeds its pinned size")
                stream.write(chunk)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if archive.stat().st_size != SPARKLE_SIZE or digest != SPARKLE_SHA256:
        raise ValueError("Sparkle archive does not match the pinned release")
    if not destination.exists():
        destination.mkdir()
        with tarfile.open(archive, "r:xz") as package:
            package.extractall(destination, filter="data")
    if (
        not (destination / "Sparkle.framework").is_dir()
        or not (destination / "bin/sign_update").is_file()
    ):
        raise ValueError("Incomplete Sparkle SDK extraction")
    return destination


def embed_sparkle(root: Path, generated: Path, minimum: str) -> None:
    sdk = sparkle_sdk(root)
    contents = root / "dist/iOpenPod.app/Contents"
    frameworks = contents / "Frameworks"
    framework = frameworks / "Sparkle.framework"
    shutil.copytree(sdk / "Sparkle.framework", framework, symlinks=True)
    bridge = frameworks / "iOpenPodSparkle.dylib"
    subprocess.run(
        [
            "clang",
            "-dynamiclib",
            "-fobjc-arc",
            "-Werror",
            "-Wall",
            f"-mmacosx-version-min={minimum}",
            "-F",
            str(sdk),
            "-framework",
            "Cocoa",
            "-framework",
            "Sparkle",
            "-Wl,-rpath,@loader_path",
            "-install_name",
            "@rpath/iOpenPodSparkle.dylib",
            str(root / "packaging/macos/update_bridge.m"),
            "-o",
            str(bridge),
        ],
        check=True,
    )
    notices = contents / "Resources/licenses/sparkle"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sdk / "LICENSE", notices / "LICENSE")
    generated_notices = generated / "licenses/sparkle"
    generated_notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sdk / "LICENSE", generated_notices / "LICENSE")
    with (contents / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    keys = public_keys(root)
    if keys:
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        info.update(
            {
                "SUFeedURL": FEED_URL.rsplit("/", 1)[0] + f"/macos-{arch}.xml",
                "SUPublicEDKey": keys[0],
                "SUEnableAutomaticChecks": False,
                "SUAllowsAutomaticUpdates": False,
                "SUAutomaticallyUpdate": False,
                "SUEnableSystemProfiling": False,
                "SUVerifyUpdateBeforeExtraction": True,
                "SURequireSignedFeed": True,
                "SUSignedFeedFailureExpirationInterval": 0,
            }
        )
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    identity = os.environ.get("IOPENPOD_CODESIGN_IDENTITY", "-")
    flags = [] if identity == "-" else ["--options", "runtime", "--timestamp"]
    nested = framework / "Versions/B"
    for target in (
        nested / "XPCServices/Installer.xpc",
        nested / "XPCServices/Downloader.xpc",
        nested / "Autoupdate",
        nested / "Updater.app",
        framework,
        bridge,
        contents.parent,
    ):
        subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                identity,
                "--preserve-metadata=entitlements",
                *flags,
                str(target),
            ],
            check=True,
        )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(contents.parent)], check=True
    )


def managed_linux_archive(root: Path, output: Path, version: str) -> None:
    """The stable launcher and immutable initial version are one distribution."""
    import io

    with tarfile.open(output, "w:gz", dereference=True) as archive:
        archive.add(root / "dist/iOpenPod-update", "iOpenPod/iOpenPod")
        for name, value in (
            ("current.json", {"version": version}),
            (
                "installation.json",
                {"product": "iOpenPod", "layout": "linux-managed-v1"},
            ),
        ):
            data = (json.dumps(value) + "\n").encode()
            entry = tarfile.TarInfo("iOpenPod/" + name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
        archive.add(root / "dist/iOpenPod", "iOpenPod/versions/" + version)
