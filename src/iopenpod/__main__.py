"""Command-line entry point for the installed iOpenPod application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from iopenpod import __version__


def run_pyqt_app() -> None:
    """Start the GUI without importing PyQt until it is needed."""

    from iopenpod.application.bootstrap import run_pyqt_app as run

    run()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the installed CLI, launching the GUI unless an option exits first."""

    parser = argparse.ArgumentParser(prog="iopenpod")
    parser.add_argument("--version", action="version", version=__version__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--print-linux-udev-rule",
        action="store_true",
        help="print the bundled least-privilege Linux identity rule and exit",
    )
    actions.add_argument(
        "--check-linux-udev-rule",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    actions.add_argument(
        "--linux-identity-status",
        metavar="MOUNT",
        help="inspect Linux product-serial integration for an iPod mount",
    )
    args = parser.parse_args(argv)
    if args.print_linux_udev_rule:
        from iopenpod.device.linux_integration import udev_rule_text

        print(udev_rule_text(), end="")
        return
    if args.check_linux_udev_rule:
        from iopenpod.device.linux_integration import udev_rule_text

        rule = udev_rule_text()
        if (
            "ID_IOPENPOD_PRODUCT_SERIAL" not in rule
            or 'TAG+="uaccess"' in rule
            or "MODE=" in rule
        ):
            raise SystemExit(1)
        return
    if args.linux_identity_status:
        from iopenpod.device.linux_integration import (
            LinuxIntegrationState,
            describe_linux_identity_integration,
        )

        identity: dict = {}
        if sys.platform.startswith("linux"):
            from iopenpod.device.linux_identity import (
                find_block_device,
                probe_linux_identity,
            )

            if find_block_device(args.linux_identity_status) is None:
                print("state=invalid_mount")
                print(
                    "The supplied path is not backed by a visible Linux "
                    "block device.",
                )
                raise SystemExit(2)
            identity = probe_linux_identity(args.linux_identity_status)
        integration = describe_linux_identity_integration(
            args.linux_identity_status,
            product_serial=str(identity.get("serial", "") or ""),
        )
        print(f"state={integration.state.value}")
        if identity.get("serial"):
            print(f"serial={identity['serial']}")
        print(integration.explanation)
        if integration.setup_instructions:
            print()
            print(integration.setup_instructions, end="")
        if integration.state is LinuxIntegrationState.NOT_APPLICABLE:
            raise SystemExit(2)
        if integration.needs_setup:
            raise SystemExit(1)
        return
    run_pyqt_app()


__all__ = ["main", "run_pyqt_app"]


if __name__ == "__main__":
    main()
