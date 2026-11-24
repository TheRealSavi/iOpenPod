"""One-time desktop USB permissions, scoped to a vendor/product pair.

The privileged entry point is standard-library-only and accepts two numeric USB
IDs, never caller-supplied rule text, paths, commands or device transfers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RULE_DIRECTORY = Path("/etc/udev/rules.d")
SYSTEM_RULE_DIRECTORY = Path("/usr/lib/udev/rules.d")


def rule_name(vendor: int, product: int) -> str:
    if any(
        type(value) is not int or not 0 <= value <= 65535 for value in (vendor, product)
    ):
        raise ValueError("USB identifiers must fit unsigned 16 bits")
    return f"70-iopenpod-usb-{vendor:04x}-{product:04x}.rules"


def rule_text(vendor: int, product: int) -> str:
    rule_name(vendor, product)
    return (
        "# Allow the active local desktop user to access this USB device.\n"
        'ACTION=="add|change", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
        f'ATTR{{idVendor}}=="{vendor:04x}", ATTR{{idProduct}}=="{product:04x}", TAG+="uaccess"\n'
    )


def installed(vendor: int, product: int) -> bool:
    name = rule_name(vendor, product)
    for directory in (RULE_DIRECTORY, SYSTEM_RULE_DIRECTORY):
        path = directory / name
        # An /etc override (including a mask) takes precedence over /usr/lib.
        if path.is_symlink() or path.exists():
            return path.read_text(encoding="utf-8") == rule_text(vendor, product)
    return False


def install_rule(vendor: int, product: int) -> None:
    """Publish fixed rule syntax atomically, then refresh only matching devices."""
    name = rule_name(vendor, product)
    udevadm = shutil.which("udevadm")
    if udevadm is None:
        raise OSError("This system has no udevadm")
    RULE_DIRECTORY.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=RULE_DIRECTORY, delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(rule_text(vendor, product))
            output.flush()
            vars(os)["fchmod"](output.fileno(), 0o644)
            os.fsync(output.fileno())
        os.replace(temporary, RULE_DIRECTORY / name)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    for arguments in (
        ["control", "--reload-rules"],
        [
            "trigger",
            "--action=change",
            "--subsystem-match=usb",
            f"--attr-match=idVendor={vendor:04x}",
            f"--attr-match=idProduct={product:04x}",
        ],
        ["settle", "--timeout=10"],
    ):
        subprocess.run(
            [udevadm, *arguments],
            check=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def authorize(vendor: int, product: int) -> None:
    """Run only the permission helper as administrator; caller reopens as user."""
    # This import is intentionally outside the isolated elevated helper path.
    from storage.usb_control import UsbControlAuthorizationError

    if installed(vendor, product):
        raise UsbControlAuthorizationError(
            "USB permissions are installed, but access is still denied. Reconnect "
            "the device from an active local desktop session and reopen setup."
        )
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise UsbControlAuthorizationError(
            "USB permission setup requires the desktop's polkit service (pkexec). "
            "Install the packaged udev rule or use a desktop with polkit, then reopen setup."
        )
    command = (
        [sys.executable, "--storage-usb-permissions"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-I", "-S", str(Path(__file__).resolve())]
    )
    try:
        result = subprocess.run(
            [
                pkexec,
                "--disable-internal-agent",
                *command,
                f"{vendor:04x}",
                f"{product:04x}",
            ],
            timeout=120,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UsbControlAuthorizationError(
            "USB permission setup did not complete; reopen setup to try again"
        ) from error
    if result.returncode != 0 or not installed(vendor, product):
        raise UsbControlAuthorizationError(
            "USB permission setup was not authorized or did not complete"
        )


def main(arguments: list[str]) -> int:
    if sys.platform != "linux" or len(arguments) != 2:
        return 2
    if os.geteuid() != 0 or any(
        re.fullmatch(r"[0-9a-f]{4}", value) is None for value in arguments
    ):
        return 2
    try:
        install_rule(*(int(value, 16) for value in arguments))
    except (OSError, subprocess.SubprocessError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
