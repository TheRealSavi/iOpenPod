"""Read embedded build evidence without guessing a frozen executable's origin."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .releases import FEED_URL, TARGET_LAYOUTS, decode_key, version_tuple


@dataclass(frozen=True, slots=True)
class Installation:
    version: str
    target: str
    layout: str
    public_keys: tuple[str, ...]
    executable: Path
    resources: Path

    @property
    def feed_url(self) -> str:
        return FEED_URL


def running_installation() -> Installation | None:
    if not getattr(sys, "frozen", False):
        return None
    resources = Path(str(getattr(sys, "_MEIPASS", "")))
    path = resources / "updates/installation.json"
    if not path.is_file():
        return None
    if path.stat().st_size > 16 * 1024:
        raise ValueError("Invalid embedded update identity")
    decoded: object = json.loads(path.read_bytes())
    if not isinstance(decoded, dict):
        raise ValueError("Invalid embedded update identity")
    value = cast("dict[str, object]", decoded)
    if value.get("schema") != 1 or value.get("product") != "iOpenPod":
        raise ValueError("Invalid embedded update identity")
    version, target = value.get("version"), value.get("target")
    if (
        not isinstance(version, str)
        or not isinstance(target, str)
        or target not in TARGET_LAYOUTS
    ):
        raise ValueError("Unsupported embedded update target")
    version_tuple(version)
    if value.get("layout") != TARGET_LAYOUTS[target]:
        raise ValueError("Unsupported embedded installation layout")
    raw_keys = value.get("public_keys")
    if not isinstance(raw_keys, list):
        raise ValueError("Invalid embedded update trust keys")
    keys = cast("list[object]", raw_keys)
    if len(keys) > 8 or not all(isinstance(key, str) for key in keys):
        raise ValueError("Invalid embedded update trust keys")
    public_keys = tuple(cast("list[str]", keys))
    for key in public_keys:
        decode_key(key)
    system = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform)
    if system is None or not target.startswith(system + "-"):
        raise ValueError("Update identity does not match this operating system")
    return Installation(
        version,
        target,
        TARGET_LAYOUTS[target],
        public_keys,
        Path(sys.executable).absolute(),
        resources,
    )


def require_supported_os(minimum: str, target: str) -> None:
    if target.startswith("macos"):
        current = platform.mac_ver()[0]
    elif target.startswith("windows"):
        current = platform.version()
    else:
        # The Linux release contract currently targets glibc 2.39 / Ubuntu 24.04.
        name, current = platform.libc_ver()
        if name != "glibc":
            raise ValueError("This Linux update requires glibc")
    try:
        required = tuple(int(part) for part in minimum.split("."))
        installed = tuple(int(part) for part in current.split("."))
    except ValueError as error:
        raise ValueError("Unable to establish update OS compatibility") from error
    if not required or not installed or installed < required:
        raise ValueError(
            f"This update requires a newer operating-system runtime ({minimum})"
        )
