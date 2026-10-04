"""Manually reproduce DMG packaging with a small app fixture on macOS."""

from __future__ import annotations

import hashlib
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.package_app import ROOT, detach_macos_image, macos_dmg, project_version


def check_macos_dmg() -> None:
    if sys.platform != "darwin":
        raise ValueError("Validate Finder disk-image layout on macOS")
    with tempfile.TemporaryDirectory(prefix="iopenpod-dmg-check-") as temporary:
        work = Path(temporary)
        app = work / "iOpenPod.app"
        executable = app / "Contents/MacOS/iOpenPod"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (app / "Contents/Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleName": "iOpenPod",
                    "CFBundleIdentifier": "com.iopenpod.dmg-check",
                    "CFBundlePackageType": "APPL",
                    "CFBundleExecutable": "iOpenPod",
                }
            )
        )
        output = macos_dmg(app, work / "layout-check.dmg", project_version())
        with output.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        assert output.with_suffix(".dmg.sha256").read_text().strip() == (
            f"{digest}  {output.name}"
        )
        mount = work / "verification-mount"
        mount.mkdir()
        subprocess.run(
            [
                "hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-mountpoint",
                str(mount),
                str(output),
            ],
            check=True,
            timeout=60,
        )
        try:
            assert (mount / ".DS_Store").stat().st_size > 0
            assert (mount / ".background/background.png").read_bytes() == (
                ROOT / "packaging/macos/dmg-background.png"
            ).read_bytes()
            assert (
                mount / "iOpenPod.app/Contents/MacOS/iOpenPod"
            ).read_bytes() == executable.read_bytes()
            assert (mount / "Applications").is_symlink()
            assert (mount / "Applications").readlink() == Path("/Applications")
        finally:
            detach_macos_image(mount)
    print("PASS: macOS DMG packaging, checksum, contents, and saved layout file")


if __name__ == "__main__":
    check_macos_dmg()
