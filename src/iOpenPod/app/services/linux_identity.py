"""Bundled least-privilege Linux identity integration."""

import logging
import os
import shlex
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

UDEV_RULE_FILENAME = "61-iopenpod.rules"
UDEV_RULE_VERSION = "2"
UDEV_RULE_DESTINATION = f"/etc/udev/rules.d/{UDEV_RULE_FILENAME}"
_UDEV_RULE_PATHS = (
    Path(UDEV_RULE_DESTINATION),
    Path("/run/udev/rules.d") / UDEV_RULE_FILENAME,
    Path("/usr/local/lib/udev/rules.d") / UDEV_RULE_FILENAME,
    Path("/usr/lib/udev/rules.d") / UDEV_RULE_FILENAME,
    Path("/lib/udev/rules.d") / UDEV_RULE_FILENAME,
)
_UDEV_RULE_READ_LIMIT = 256 * 1024

logger = logging.getLogger(__name__)


class UdevRuleStatusKind(StrEnum):
    """Observed state of the highest-priority iOpenPod udev rule copy."""

    CURRENT = "current"
    MISSING = "missing"
    DIFFERENT = "different"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class UdevRuleStatus:
    """Read-only status suitable for presentation without Host mutation."""

    kind: UdevRuleStatusKind
    path: Path | None = None


def udev_rule_text() -> str:
    """Return the exact udev rule shipped with this iOpenPod build."""

    rule = (
        files("iOpenPod")
        .joinpath("assets", "linux", UDEV_RULE_FILENAME)
        .read_text(encoding="utf-8")
    )
    version_marker = f'ENV{{ID_IOPENPOD_RULE_VERSION}}="{UDEV_RULE_VERSION}"'
    if version_marker not in rule:
        raise RuntimeError("The bundled udev rule version does not match the app")
    return rule


def inspect_udev_rule() -> UdevRuleStatus:
    """Inspect the effective standard-path rule without changing the Host."""

    canonical = udev_rule_text()
    for path in _UDEV_RULE_PATHS:
        if not os.path.lexists(path):
            continue
        try:
            with path.open(encoding="utf-8") as stream:
                candidate = stream.read(_UDEV_RULE_READ_LIMIT + 1)
        except (OSError, UnicodeError):
            logger.info("Linux udev identity-rule status: unreadable at %s", path)
            return UdevRuleStatus(UdevRuleStatusKind.UNREADABLE, path)
        if candidate == canonical:
            logger.info(
                "Linux udev identity-rule status: installed and current at %s "
                "(version %s)",
                path,
                UDEV_RULE_VERSION,
            )
            return UdevRuleStatus(UdevRuleStatusKind.CURRENT, path)
        logger.info(
            "Linux udev identity-rule status: different or disabled copy takes "
            "priority at %s",
            path,
        )
        return UdevRuleStatus(UdevRuleStatusKind.DIFFERENT, path)

    logger.info(
        "Linux udev identity-rule status: not installed in a standard rules directory"
    )
    return UdevRuleStatus(UdevRuleStatusKind.MISSING)


def udev_setup_script() -> str:
    """Return the reviewed POSIX shell script for least-privilege Host setup.

    iOpenPod itself remains unprivileged. The setup runs in a Host terminal,
    where ``sudo`` or ``doas`` performs only the rule install and
    udev reload. The rule is staged in udev's root-owned directory and renamed
    into place so a failed copy cannot leave a partial active rule.
    """

    rule = udev_rule_text().rstrip()
    return f"""\
(
set -eu

RULE_DEST={UDEV_RULE_DESTINATION}
RULE_STAGE="${{RULE_DEST}}.new.$$"
RULE_TEMP="$(mktemp "${{TMPDIR:-/tmp}}/iopenpod-udev.XXXXXX")"
ADMIN_NOTICE_SHOWN=0

die() {{
  printf '%s\\n' "iOpenPod Linux setup failed: $*" >&2
  exit 1
}}

show_admin_notice() {{
  if [ "$ADMIN_NOTICE_SHOWN" -ne 0 ]; then
    return
  fi
  printf '%s\\n' "iOpenPod needs administrator access to install its udev identity rule." >&2
  printf '%s\\n' "Your terminal may ask for your password; iOpenPod cannot see or store it." >&2
  printf '%s\\n' "The rule does not grant raw-disk access or change device permissions." >&2
  ADMIN_NOTICE_SHOWN=1
}}

run_as_root() {{
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    show_admin_notice
    sudo "$@"
  elif command -v doas >/dev/null 2>&1; then
    show_admin_notice
    doas "$@"
  else
    die "administrator access requires sudo, doas, or a root shell"
  fi
}}

cleanup() {{
  rm -f "$RULE_TEMP"
  if [ -n "${{RULE_STAGE:-}}" ]; then
    run_as_root rm -f "$RULE_STAGE" >/dev/null 2>&1 || true
  fi
}}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

for command in id mkdir mktemp install mv rm udevadm; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

cat >"$RULE_TEMP" <<'IOPENPOD_UDEV_RULE'
{rule}
IOPENPOD_UDEV_RULE

run_as_root mkdir -p -m 0755 /etc/udev/rules.d
run_as_root rm -f "$RULE_STAGE"
run_as_root install -o root -g root -m 0644 "$RULE_TEMP" "$RULE_STAGE"
run_as_root mv -f "$RULE_STAGE" "$RULE_DEST"
RULE_STAGE=""
run_as_root udevadm control --reload-rules

printf '%s\\n' "iOpenPod's Linux identity rule is installed."
printf '%s\\n' "Complete these steps before trying to use the iPod:"
printf '%s\\n' "  1. Safely eject the iPod completely in iOpenPod or the operating system."
printf '%s\\n' "  2. Physically disconnect and reconnect the iPod."
printf '%s\\n' "  3. Wait for the operating system to mount the iPod again."
printf '%s\\n' "  4. Choose Refresh in iOpenPod's device picker."
printf '%s\\n' "Restarting or refreshing iOpenPod before the remount is not enough."
)
"""


def udev_setup_command() -> str:
    """Return a paste-safe command that runs the setup script with POSIX sh.

    The user's interactive shell may be Bash, Zsh, Fish, or another shell. It
    must only parse this outer command; the explicitly selected POSIX shell
    parses the reviewed setup script.
    """

    logger.info(
        "Prepared Linux udev identity-rule setup command for bundled version %s; "
        "iOpenPod remains unprivileged",
        UDEV_RULE_VERSION,
    )
    return f"/bin/sh -c {shlex.quote(udev_setup_script())}"


def udev_uninstall_script() -> str:
    """Return a script that removes only iOpenPod's local udev-rule copy."""

    return f"""\
(
set -eu

RULE_DEST={UDEV_RULE_DESTINATION}
ADMIN_NOTICE_SHOWN=0

die() {{
  printf '%s\\n' "iOpenPod Linux setup removal failed: $*" >&2
  exit 1
}}

show_admin_notice() {{
  if [ "$ADMIN_NOTICE_SHOWN" -ne 0 ]; then
    return
  fi
  printf '%s\\n' "iOpenPod needs administrator access to remove its local udev identity rule." >&2
  printf '%s\\n' "Your terminal may ask for your password; iOpenPod cannot see or store it." >&2
  ADMIN_NOTICE_SHOWN=1
}}

run_as_root() {{
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    show_admin_notice
    sudo "$@"
  elif command -v doas >/dev/null 2>&1; then
    show_admin_notice
    doas "$@"
  else
    die "administrator access requires sudo, doas, or a root shell"
  fi
}}

for command in id rm udevadm; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

[ ! -d "$RULE_DEST" ] || die "refusing to remove a directory at $RULE_DEST"
if [ ! -e "$RULE_DEST" ] && [ ! -L "$RULE_DEST" ]; then
  printf '%s\\n' "No local iOpenPod udev rule is installed at $RULE_DEST."
  exit 0
fi

run_as_root rm -f -- "$RULE_DEST"
run_as_root udevadm control --reload-rules

printf '%s\\n' "Removed the local iOpenPod udev rule from $RULE_DEST."
printf '%s\\n' "Already-published identity properties remain cached for the current connection."
printf '%s\\n' "Safely eject, physically disconnect, and reconnect the iPod to clear them."
printf '%s\\n' "Restarting iOpenPod alone does not clear the udev runtime database."
printf '%s\\n' "After reconnecting, choose Check Again in iOpenPod Settings."
printf '%s\\n' "A package-managed rule may still remain under /usr or /lib."
)
"""


def udev_uninstall_command() -> str:
    """Return a paste-safe command that removes the local rule with POSIX sh."""

    logger.info(
        "Prepared Linux udev identity-rule uninstall command for %s; iOpenPod "
        "remains unprivileged",
        UDEV_RULE_DESTINATION,
    )
    return f"/bin/sh -c {shlex.quote(udev_uninstall_script())}"
