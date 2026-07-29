"""Smoke-test the installed wheel without importing from the source tree."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import iopenpod


def main() -> None:
    package_file = Path(iopenpod.__file__).resolve()
    rule = (
        files("iopenpod")
        .joinpath("assets", "linux", "61-iopenpod.rules")
        .read_text(encoding="utf-8")
    )
    if "ID_IOPENPOD_PRODUCT_SERIAL" not in rule:
        raise SystemExit("installed wheel is missing the Linux identity rule")
    if 'TAG+="uaccess"' in rule or "MODE=" in rule:
        raise SystemExit("installed Linux identity rule grants raw-device access")
    print(f"installed_package={package_file}")
    print("linux_identity_rule=ok")


if __name__ == "__main__":
    main()
