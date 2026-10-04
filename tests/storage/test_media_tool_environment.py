"""External media processes must not load the frozen application's libraries."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from storage import HostPath, host_tools
from storage.media_probe import probe
from storage.media_processing import run_media_tool


@pytest.mark.parametrize("runner", ["processing", "probe"])
@pytest.mark.parametrize(
    ("platform", "frozen", "original", "expected"),
    [
        ("linux", True, None, None),
        ("linux", True, "", ""),
        ("linux", True, "/host/lib:/other/lib", "/host/lib:/other/lib"),
        ("linux", False, "/host/lib", "/bundle/lib"),
        ("darwin", True, "/host/lib", "/bundle/lib"),
        ("win32", True, "/host/lib", "/bundle/lib"),
    ],
)
def test_media_children_use_host_libraries_without_changing_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: str,
    platform: str,
    frozen: bool,
    original: str | None,
    expected: str | None,
) -> None:
    monkeypatch.setattr(
        host_tools, "sys", SimpleNamespace(platform=platform, frozen=frozen)
    )
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/lib")
    if original is None:
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    else:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    parent = dict(os.environ)
    launch_process = subprocess.Popen

    def launch(
        args: list[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        creationflags: int,
        pass_fds: tuple[int, ...] = (),
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        # Exercise the real process runners and inspect what their child inherits.
        return launch_process(
            [
                sys.executable,
                "-c",
                "import json, os; print(json.dumps({key: os.environ.get(key) "
                "for key in ('LD_LIBRARY_PATH', 'PATH')}))",
            ],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            pass_fds=pass_fds,
            env=env,
        )

    monkeypatch.setattr(subprocess, "Popen", launch)
    executable = HostPath(sys.executable)
    if runner == "processing":
        output = run_media_tool(
            executable, ("-version",), checkpoint=lambda: None
        ).stdout
    else:
        output = probe(
            executable,
            HostPath(tmp_path / "captured.wav"),
            lambda: None,
            timeout_seconds=5,
            max_output_bytes=65536,
        )
    assert json.loads(output) == {
        "LD_LIBRARY_PATH": expected,
        "PATH": parent.get("PATH"),
    }
    assert dict(os.environ) == parent
