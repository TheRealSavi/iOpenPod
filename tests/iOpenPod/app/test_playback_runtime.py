"""Check real decoding with the DLL search rules that expose MSIX failures."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "restricted_search,configure_frozen",
    [(False, False), (True, False), (True, True)],
    ids=["native", "missing-codecs", "frozen-codecs"],
)
def test_playback_runtime_decodes_without_audio_output(
    tmp_path: Path, restricted_search: bool, configure_frozen: bool
) -> None:
    if restricted_search and sys.platform != "win32":
        pytest.skip("Windows DLL search rules")
    script = textwrap.dedent("""\
        import ctypes
        import sys
        from pathlib import Path

        # MSIX does not resolve plugin dependencies through PATH. Reproduce
        # that restriction in a fresh process without installing a package.
        if sys.argv[1] == "True":
            assert ctypes.windll.kernel32.SetDefaultDllDirectories(0x1000)
        import PySide6
        from PySide6.QtWidgets import QApplication
        from iOpenPod.app.core.runtime import configure_frozen_runtime
        from iOpenPod.app.playback.runtime_check import check_playback_runtime

        if sys.argv[2] == "True":
            sys.frozen = True
            sys._MEIPASS = str(Path(PySide6.__file__).parent.parent)
            configure_frozen_runtime()
        app = QApplication([])
        check_playback_runtime()
        """)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    environment.pop("QT_MEDIA_BACKEND", None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(restricted_search),
            str(configure_frozen),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if configure_frozen or not restricted_search:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert "RuntimeError: Qt Multimedia" in result.stderr
