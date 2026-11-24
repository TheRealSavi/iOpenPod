"""Notarize a Developer ID build, staple its ticket, and verify Gatekeeper."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def notarize(root: Path, profile: str) -> Path:
    """Use credentials already stored in the Mac builder's keychain."""
    if sys.platform != "darwin":
        raise ValueError("Notarize the macOS build on macOS")
    if not profile.strip():
        raise ValueError("A notarytool keychain profile is required")
    app = root / "dist/iOpenPod.app"
    if not app.is_dir():
        raise ValueError("Build the signed macOS app before notarizing")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    signature = subprocess.run(
        ["codesign", "--display", "--verbose=4", str(app)],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    if (
        "Authority=Developer ID Application:" not in signature
        or "(runtime)" not in signature
    ):
        raise ValueError(
            "Build with a Developer ID Application identity and hardened runtime first"
        )
    output = root / "build/packaging/notarization"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="submission-", dir=output) as temporary:
        archive = Path(temporary) / "iOpenPod.zip"
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True
        )
        submitted = subprocess.run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(archive),
                "--keychain-profile",
                profile,
                "--output-format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        submission: object = json.loads(submitted.stdout)
        if not isinstance(submission, dict) or not isinstance(
            submission.get("id"), str
        ):
            raise ValueError(
                "The notary service did not return a submission identifier"
            )
        identifier = str(uuid.UUID(submission["id"]))
        # Retain the ID before waiting, so a timeout can be investigated without
        # submitting the same build again. Keep credentials out of build reports.
        (output / f"{identifier}-submission.json").write_text(
            submitted.stdout, encoding="utf-8"
        )
        completed = subprocess.run(
            [
                "xcrun",
                "notarytool",
                "wait",
                identifier,
                "--keychain-profile",
                profile,
                "--output-format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        (output / f"{identifier}-result.json").write_text(
            completed.stdout, encoding="utf-8"
        )
        log = output / f"{identifier}-log.json"
        subprocess.run(
            [
                "xcrun",
                "notarytool",
                "log",
                identifier,
                "--keychain-profile",
                profile,
                str(log),
            ],
            check=True,
            timeout=60,
        )
        result: object = json.loads(completed.stdout)
        if (
            completed.returncode
            or not isinstance(result, dict)
            or result.get("status") != "Accepted"
        ):
            raise ValueError(f"Apple did not accept this build; inspect {log}")
    subprocess.run(["xcrun", "stapler", "staple", str(app)], check=True, timeout=120)
    subprocess.run(["xcrun", "stapler", "validate", str(app)], check=True, timeout=60)
    subprocess.run(
        ["spctl", "--assess", "--type", "execute", "--verbose=2", str(app)],
        check=True,
        timeout=60,
    )
    return app
