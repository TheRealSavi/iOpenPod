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

RULE_VERSION = "2"
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
RULE_DEST={RULE_DESTINATION}
RULE_EXPECTED_VERSION={RULE_VERSION}

# Prefer normal host locations without discarding distro-specific PATH entries
# (for example, NixOS wrappers).
PATH="/usr/sbin:/usr/bin:/sbin:/bin${{PATH:+:$PATH}}"
export PATH

log() {{
  printf '%s\\n' "iOpenPod: $*" >&2
}}

die() {{
  printf '%s\\n' "iOpenPod Linux identity setup failed: $*" >&2
  exit 1
}}

need_cmd() {{
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}}

run_as_root() {{
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  elif command -v doas >/dev/null 2>&1; then
    doas "$@"
  else
    die "administrator access requires sudo, doas, or a root shell"
  fi
}}

# A container has its own /etc and cannot update the host udev daemon/rules.
# This catches the common Distrobox/Toolbox/Podman/Flatpak cases, including
# Bazzite users who opened a development container before running the command.
if [ -f /.dockerenv ] || [ -f /run/.containerenv ] || \\
   [ -n "${{container:-}}" ] || [ -n "${{DISTROBOX_ENTER_PATH:-}}" ] || \\
   [ -n "${{FLATPAK_ID:-}}" ]; then
  die "run this command in a terminal on the Linux host, not inside Distrobox, Toolbox, Flatpak, or another container"
fi

for cmd in findmnt sed readlink lsblk id mkdir mktemp cp chmod rm mv \\
           udevadm grep; do
  need_cmd "$cmd"
done

[ -d "$MOUNT" ] || die "iPod mount path does not exist: $MOUNT"

PART="$(findmnt -n -o SOURCE --target "$MOUNT" 2>/dev/null || true)"
PART="$(printf '%s\\n' "$PART" | sed 's/\\[.*$//')"
[ -n "$PART" ] || die "could not resolve a block device for mount path: $MOUNT"

RESOLVED_PART="$(readlink -f "$PART" 2>/dev/null || true)"
[ -n "$RESOLVED_PART" ] || die "could not resolve mount source: $PART"
PART="$RESOLVED_PART"
case "$PART" in
  /dev/*) ;;
  *) die "mount source is not a /dev block device: $PART" ;;
esac
[ -b "$PART" ] || die "mount source is not a block device: $PART"

PARENT="$(lsblk -ndo PKNAME "$PART" 2>/dev/null | sed -n '1p')"
if [ -n "$PARENT" ]; then
  DISK="/dev/$PARENT"
else
  DISK="$PART"
fi

SYSNAME="${{DISK##*/}}"
case "$SYSNAME" in
  ""|*[!a-zA-Z0-9._-]*) die "unsafe block-device name: $SYSNAME" ;;
esac
[ -b "$DISK" ] || die "resolved whole disk is not a block device: $DISK"

SYSPATH="/sys/class/block/$SYSNAME"
[ -e "$SYSPATH" ] || die "resolved block device has no sysfs entry: $DISK"

VENDOR="$(sed 's/[[:space:]]*$//' "$SYSPATH/device/vendor" 2>/dev/null || true)"
MODEL="$(sed 's/[[:space:]]*$//' "$SYSPATH/device/model" 2>/dev/null || true)"
case "$VENDOR" in
  Apple*) ;;
  *) die "resolved disk is not an Apple SCSI device: $DISK (vendor=${{VENDOR:-unknown}})" ;;
esac
case "$MODEL" in
  iPod*) ;;
  *) die "resolved Apple disk is not an iPod: $DISK (model=${{MODEL:-unknown}})" ;;
esac

log "resolved $MOUNT -> $DISK ($VENDOR $MODEL)"

[ ! -d "$RULE_DEST" ] || die "udev rule destination is a directory: $RULE_DEST"
run_as_root mkdir -p -m 0755 /etc/udev/rules.d || \\
  die "could not create /etc/udev/rules.d on this host"

RULE_TMP="$(mktemp "${{TMPDIR:-/tmp}}/iopenpod-udev.XXXXXX")" || \\
  die "could not create temporary rule file"
RULE_STAGE="/etc/udev/rules.d/.{RULE_FILENAME}.new.$$"

cleanup() {{
  rm -f "$RULE_TMP" 2>/dev/null || true
  if [ -n "${{RULE_STAGE:-}}" ]; then
    run_as_root rm -f "$RULE_STAGE" >/dev/null 2>&1 || true
  fi
}}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

cat >"$RULE_TMP" <<'IOPENPOD_UDEV_RULE'
{rule}
IOPENPOD_UDEV_RULE

# Stage inside /etc/udev/rules.d so the final rename is atomic and the file
# receives the host directory's normal security context (important on SELinux).
run_as_root rm -f "$RULE_STAGE" || die "could not clear the udev rule staging path"
run_as_root cp "$RULE_TMP" "$RULE_STAGE" || die "could not stage the udev rule"
run_as_root chmod 0644 "$RULE_STAGE" || die "could not set udev rule permissions"
[ ! -d "$RULE_DEST" ] || die "udev rule destination became a directory: $RULE_DEST"
run_as_root mv -f "$RULE_STAGE" "$RULE_DEST" || die "could not install $RULE_DEST"
RULE_STAGE=""
rm -f "$RULE_TMP"
trap - EXIT HUP INT TERM

log "installed $RULE_DEST"
log "reloading udev rules and retriggering only $DISK"
run_as_root udevadm control --reload-rules || die "udev is not running or refused to reload rules"

# systemd-udev >= 238 can wait only for the event this command triggers.
# Older udev/eudev versions use the long-standing global settle command; keep
# that fallback bounded so unrelated device activity cannot hang setup.
if udevadm trigger --help 2>&1 | grep -q 'settle'; then
  run_as_root udevadm trigger --action=change --subsystem-match=block \\
    --sysname-match="$SYSNAME" --settle || \\
    die "failed to trigger udev for $DISK"
else
  run_as_root udevadm trigger --action=change --subsystem-match=block \\
    --sysname-match="$SYSNAME" || die "failed to trigger udev for $DISK"
  run_as_root udevadm settle -t 15 || true
fi

PROPERTIES="$(udevadm info --query=property --name="$DISK" 2>/dev/null || true)"
SERIAL="$(printf '%s\\n' "$PROPERTIES" | sed -n 's/^ID_IOPENPOD_PRODUCT_SERIAL=//p')"
RULE_SEEN="$(printf '%s\\n' "$PROPERTIES" | sed -n 's/^ID_IOPENPOD_RULE_VERSION=//p')"

if [ -n "$SERIAL" ]; then
  printf 'ID_IOPENPOD_PRODUCT_SERIAL=%s\\n' "$SERIAL"
  log "Apple product serial published successfully"
  exit 0
fi

log "serial property was not published; collecting diagnostics"
printf '%s\\n' "  disk: $DISK" >&2
printf '%s\\n' "  sysfs: $SYSPATH" >&2
printf '%s\\n' "  SCSI vendor/model: $VENDOR / $MODEL" >&2
printf '%s\\n' "  udevadm version: $(udevadm --version 2>/dev/null || printf unknown)" >&2
printf '%s\\n' "  expected rule version: $RULE_EXPECTED_VERSION" >&2
printf '%s\\n' "  observed rule version: ${{RULE_SEEN:-<missing>}}" >&2

if [ "$RULE_SEEN" = "$RULE_EXPECTED_VERSION" ]; then
  log "the iOpenPod rule matched; scsi_id did not produce a usable page 0x80 serial"
elif [ -n "$RULE_SEEN" ]; then
  log "udev reported a different iOpenPod rule version; another rule copy may be taking precedence"
else
  log "the iOpenPod rule marker is missing; the rule did not match or was not processed"
fi

SCSI_ID=""
if command -v scsi_id >/dev/null 2>&1; then
  SCSI_ID="$(command -v scsi_id)"
elif [ -x /usr/lib/udev/scsi_id ]; then
  SCSI_ID=/usr/lib/udev/scsi_id
elif [ -x /lib/udev/scsi_id ]; then
  SCSI_ID=/lib/udev/scsi_id
fi

if [ -n "$SCSI_ID" ]; then
  log "direct scsi_id page 0x80 probe ($SCSI_ID):"
  if SCSI_PROBE="$(
    run_as_root "$SCSI_ID" --page=0x80 --whitelisted --device="$DISK" 2>&1
  )"; then
    if [ -n "$SCSI_PROBE" ]; then
      printf '%s\\n' "$SCSI_PROBE" >&2
    else
      printf '%s\\n' "  <no output>" >&2
    fi
  else
    SCSI_STATUS=$?
    printf '%s\\n' "  exit status: $SCSI_STATUS" >&2
    [ -z "$SCSI_PROBE" ] || printf '%s\\n' "$SCSI_PROBE" >&2
  fi
else
  log "scsi_id was not visible in PATH or the common /usr/lib/udev and /lib/udev helper paths"
fi

log "relevant udev test output:"
run_as_root udevadm test --action=change "$SYSPATH" 2>&1 \\
  | grep -Ei '61-iopenpod|iopenpod|scsi_id|apple|ipod|error|failed|invalid|unknown' \\
  >&2 || true

die "rule installed, but the Apple product serial was not published; diagnostics are above"
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
            "The highest-priority iOpenPod Linux identity rule is disabled or outdated.",
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
    firewire_guid = str(getattr(device, "firewire_guid", "") or "").strip()
    mount_path = str(getattr(device, "path", "") or "").strip()
    return (
        bool(mount_path)
        or usb_pid in IPOD_USB_PIDS
        or bool(
            re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{16}", firewire_guid),
        )
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
