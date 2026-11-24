"""Optional Authenticode signing using an existing Windows certificate store."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def sign(executable: Path, environment: dict[str, str] | None = None) -> None:
    values = dict(os.environ) if environment is None else environment
    identity = values.get("IOPENPOD_WINDOWS_CERTIFICATE", "").strip()
    if not identity:
        return  # Ordinary local/CI candidates remain explicitly unsigned.
    if re.fullmatch(r"[0-9a-fA-F]{40}", identity) is None:
        raise ValueError(
            "IOPENPOD_WINDOWS_CERTIFICATE must be a certificate SHA-1 thumbprint"
        )
    timestamp = values.get("IOPENPOD_WINDOWS_TIMESTAMP_URL", "")
    parsed = urlsplit(timestamp)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Configure an HTTPS IOPENPOD_WINDOWS_TIMESTAMP_URL for signed releases"
        )
    tool = values.get("IOPENPOD_SIGNTOOL") or shutil.which(
        "signtool.exe", path=values.get("PATH", "")
    )
    if not tool:
        sdk = Path(values.get("PROGRAMFILES(X86)", "")) / "Windows Kits/10/bin"
        candidates = sorted(sdk.glob("10.*/x64/signtool.exe"))
        tool = str(candidates[-1]) if candidates else None
    if not tool:
        raise ValueError(
            "Install Windows SDK SignTool on the builder or set IOPENPOD_SIGNTOOL"
        )
    subprocess.run(
        [
            tool,
            "sign",
            "/sha1",
            identity,
            "/fd",
            "SHA256",
            "/tr",
            timestamp,
            "/td",
            "SHA256",
            str(executable),
        ],
        check=True,
        env=values,
        timeout=180,
    )
    subprocess.run(
        [tool, "verify", "/pa", str(executable)], check=True, env=values, timeout=60
    )
