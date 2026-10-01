"""Sidecar formats remain usable independently of Library projection and I/O."""

import subprocess
import sys


def test_sidecar_formats_import_without_library_or_storage() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import iPodDB.sidecars\n"
            "forbidden = ('iPodDB.library', 'iOpenPod', 'storage')\n"
            "assert not [name for name in sys.modules "
            "if any(name == prefix or name.startswith(prefix + '.') "
            "for prefix in forbidden)]\n",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
