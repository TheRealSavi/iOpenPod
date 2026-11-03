"""A persistent worker cannot outlive its owner's pipe, including during work."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("busy", [False, True])
def test_owner_pipe_eof_stops_idle_and_busy_worker(busy: bool) -> None:
    program = """
import sys, time
from threading import Thread
from iOpenPod.assets.phase_runtime.worker import _watch_owner
Thread(target=_watch_owner, daemon=True).start()
import numpy
print('ready', flush=True)
if sys.argv[1] == 'busy':
    time.sleep(30)
else:
    while True:
        time.sleep(0.05)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, "busy" if busy else "idle"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stdout.readline().strip() == b"ready"
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=3) == 70
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def test_owner_watcher_allows_native_imports_and_normal_interpreter_exit() -> None:
    program = """
from threading import Thread
from iOpenPod.assets.phase_runtime.worker import _watch_owner
Thread(target=_watch_owner, daemon=True).start()
import numpy
print('imported', flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        # Do not communicate() yet: it closes stdin, hiding the import deadlock.
        assert process.wait(timeout=5) == 0
        output, errors = process.communicate(timeout=2)
        assert output.strip() == b"imported" and not errors
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=2)


def test_owner_watcher_setup_failure_terminates_the_worker() -> None:
    program = """
import os, time
from threading import Thread
from iOpenPod.assets.phase_runtime.worker import _watch_owner
def fail(*args):
    raise OSError('pipe unavailable')
os.set_blocking = fail
Thread(target=_watch_owner, daemon=True).start()
time.sleep(30)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=3,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    assert result.returncode == 70
