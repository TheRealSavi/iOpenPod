"""Actionable, least-privilege Linux product-serial integration.

The application stays unprivileged.  Native packages may install the bundled
udev rule, while source, wheel, AppImage, and Flatpak runs can show the same
transparent host-side setup instructions.
"""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

from .models import IPOD_USB_PIDS

RULE_VERSION = "1"
RULE_FILENAME = "61-iopenpod.rules"
RULE_DESTINATION = f"/etc/udev/rules.d/{RULE_FILENAME}"
_RULE_PARTS = ("assets", "linux", RULE_FILENAME)
_HOST_RULE_PATHS = (
    Path(RULE_DESTINATION),
    Path("/run/udev/rules.d") / RULE_FILENAME,
    Path("/usr/local/lib/udev/rules.d") / RULE_FILENAME,
    Path("/usr/lib/udev/rules.d") / RULE_FILENAME,
    Path("/lib/udev/rules.d") / RULE_FILENAME,
)


class LinuxIntegrationState(StrEnum):
    """Host-integration state relevant to an unresolved Linux iPod."""

    NOT_APPLICABLE = "not_applicable"
    READY = "ready"
    SETUP_REQUIRED = "setup_required"
    REFRESH_REQUIRED = "refresh_required"
    RULE_OUTDATED = "rule_outdated"


@dataclass(frozen=True)
class LinuxIdentityIntegration:
    """Everything a caller needs to explain the Linux setup requirement."""

    state: LinuxIntegrationState
    explanation: str
    setup_instructions: str = ""

    @property
    def needs_setup(self) -> bool:
        return self.state not in {
            LinuxIntegrationState.NOT_APPLICABLE,
            LinuxIntegrationState.READY,
        }


def udev_rule_text() -> str:
    """Return the canonical rule shipped inside every application artifact."""

    resource = files("iopenpod").joinpath(*_RULE_PARTS)
    return resource.read_text(encoding="utf-8")


def _installed_rule_state() -> tuple[bool, bool]:
    canonical = udev_rule_text()
    for path in _HOST_RULE_PATHS:
        try:
            candidate = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # udev uses the first copy at the highest-priority rules directory.
        # A stale /etc override or /dev/null link must not be hidden by a
        # matching vendor copy under /usr.
        return True, candidate == canonical
    return False, False


def _setup_instructions(mount_path: str) -> str:
    mount = shlex.quote(str(mount_path))
    rule = udev_rule_text().rstrip()
    return f"""\
set -eu
MOUNT={mount}
PART="$(findmnt -n -o SOURCE --target "$MOUNT" | sed 's/\\[.*$//')"
PART="$(readlink -f "$PART")"
case "$PART" in
  /dev/*) ;;
  *) echo "Could not safely resolve the iPod block device" >&2; exit 1 ;;
esac
PARENT="$(lsblk -ndo PKNAME "$PART" | sed -n '1p')"
if [ -n "$PARENT" ]; then DISK="/dev/$PARENT"; else DISK="$PART"; fi
SYSNAME="${{DISK##*/}}"
case "$SYSNAME" in
  ""|*[!a-zA-Z0-9._-]*) echo "Unsafe block-device name" >&2; exit 1 ;;
esac

run_as_root() {{
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  elif command -v doas >/dev/null 2>&1; then
    doas "$@"
  else
    echo "Administrator access requires sudo, doas, or a root shell" >&2
    return 1
  fi
}}

run_as_root install -d -m 0755 /etc/udev/rules.d
RULE_TMP="$(mktemp "${{TMPDIR:-/tmp}}/iopenpod-udev.XXXXXX")"
RULE_STAGE="/etc/udev/rules.d/.{RULE_FILENAME}.new.$$"
trap 'rm -f "$RULE_TMP"' EXIT
trap 'exit 1' HUP INT TERM
cat >"$RULE_TMP" <<'IOPENPOD_UDEV_RULE'
{rule}
IOPENPOD_UDEV_RULE
run_as_root install -o root -g root -m 0644 "$RULE_TMP" "$RULE_STAGE"
run_as_root mv -fT "$RULE_STAGE" {RULE_DESTINATION}
rm -f "$RULE_TMP"
trap - EXIT HUP INT TERM
run_as_root udevadm control --reload-rules
run_as_root udevadm trigger --action=change --subsystem-match=block \
  --sysname-match="$SYSNAME"
sudo udevadm settle
udevadm info --query=property --name="$DISK" \
  | grep '^ID_IOPENPOD_PRODUCT_SERIAL='
"""


def describe_linux_identity_integration(
    mount_path: str,
    *,
    product_serial: str = "",
    platform: str | None = None,
) -> LinuxIdentityIntegration:
    """Describe the host action needed to expose one iPod's product serial."""

    active_platform = sys.platform if platform is None else platform
    if not active_platform.startswith("linux"):
        return LinuxIdentityIntegration(
            LinuxIntegrationState.NOT_APPLICABLE,
            "Linux host integration is not applicable on this platform.",
        )
    if product_serial.strip():
        return LinuxIdentityIntegration(
            LinuxIntegrationState.READY,
            "The Apple product serial is already available.",
        )

    installed, current = _installed_rule_state()
    instructions = _setup_instructions(mount_path)
    if not installed:
        return LinuxIdentityIntegration(
            LinuxIntegrationState.SETUP_REQUIRED,
            "The iOpenPod Linux identity rule is not installed on this host.",
            instructions,
        )
    if not current:
        return LinuxIdentityIntegration(
            LinuxIntegrationState.RULE_OUTDATED,
            "The highest-priority iOpenPod Linux identity rule is disabled "
            "or outdated.",
            instructions,
        )
    return LinuxIdentityIntegration(
        LinuxIntegrationState.REFRESH_REQUIRED,
        "The identity rule is installed, but this iPod has not published its "
        "Apple product serial. Reinstalling and triggering only this block "
        "device will retry without disconnecting it.",
        instructions,
    )


def linux_identity_setup_needed(
    device: object | None,
    *,
    platform: str | None = None,
) -> bool:
    """Return whether a verified iPod still needs its Apple product serial."""

    active_platform = sys.platform if platform is None else platform
    if not active_platform.startswith("linux") or device is None:
        return False
    if str(getattr(device, "serial", "") or "").strip():
        return False

    try:
        usb_pid = int(getattr(device, "usb_pid", 0) or 0)
    except (TypeError, ValueError):
        usb_pid = 0
    firewire_guid = str(
        getattr(device, "firewire_guid", "") or ""
    ).strip()
    mount_path = str(getattr(device, "path", "") or "").strip()
    return bool(mount_path) or usb_pid in IPOD_USB_PIDS or bool(
        re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{16}", firewire_guid),
    )


__all__ = [
    "LinuxIdentityIntegration",
    "LinuxIntegrationState",
    "RULE_DESTINATION",
    "RULE_FILENAME",
    "RULE_VERSION",
    "describe_linux_identity_integration",
    "linux_identity_setup_needed",
    "udev_rule_text",
]
