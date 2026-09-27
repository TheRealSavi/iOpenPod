"""Select the locked macOS build environment for the declared deployment target."""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_macos_build(*, with_checks: bool = False) -> None:
    """Use managed Python and target wheel tags, keeping dev tools out of freeze."""
    if sys.platform != "darwin":
        raise ValueError("Build macOS candidates on macOS")
    machine = platform.machine()
    targets = {
        "arm64": "aarch64-apple-darwin",
        "x86_64": "x86_64-apple-darwin",
    }
    if machine not in targets:
        raise ValueError(f"Unsupported macOS build architecture: {machine}")
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("Install UV before preparing the macOS build")
    with (ROOT / "pyproject.toml").open("rb") as stream:
        config = tomllib.load(stream)["tool"]["iopenpod"]["packaging"]
    environment = dict(os.environ)
    environment["MACOSX_DEPLOYMENT_TARGET"] = config["macos-minimum-version"]
    command = [
        uv,
        "sync",
        "--locked",
        "--managed-python",
        "--python",
        config["macos-python-version"],
        "--python-platform",
        targets[machine],
        "--no-dev",
        "--no-build",
        "--group",
        "packaging",
    ]
    if with_checks:
        command.extend(("--group", "packaging-checks"))
    # --no-build still permits the first-party editable project. Third-party
    # dependencies must use wheels; a missing Intel wheel cannot trigger an
    # LLVM/Numba build with unreviewed compiler or deployment settings.
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-checks", action="store_true")
    arguments = parser.parse_args()
    sync_macos_build(with_checks=arguments.with_checks)
