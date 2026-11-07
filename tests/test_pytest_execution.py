"""Exercise the repository's test policy through real, isolated pytest commands."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    policy = (ROOT / "conftest.py").read_text(encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        policy
        + """
import json

def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: selection probe")

def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not hasattr(config, "workerinput"):
        (config.rootpath / "result.json").write_text(json.dumps({
            "workers": config.option.numprocesses,
            "distribution": config.option.dist,
            "exitstatus": int(exitstatus),
        }))
""",
        encoding="utf-8",
    )
    tests = tmp_path / "tests" / "nested"
    tests.mkdir(parents=True)
    (tmp_path / "observations").mkdir()
    for index in range(8):
        (tests / f"test_{index}.py").write_text(
            """import json
import os
from pathlib import Path
import pytest

@pytest.mark.smoke
@pytest.mark.parametrize("case", ["a", "b"])
def test_probe(case, request, worker_id):
    output = request.config.rootpath / "observations"
    with (output / (Path(__file__).stem + case + ".json")).open("x") as stream:
        json.dump({
            "node": request.node.nodeid,
            "worker": worker_id,
            "pid": os.getpid(),
        }, stream)
""",
            encoding="utf-8",
        )
    return tmp_path


def _run(suite: Path, args: tuple[str, ...], *, cwd: Path | None = None) -> str:
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    # A machine's CPU count or environment override must not change our policy.
    environment["PYTEST_XDIST_AUTO_NUM_WORKERS"] = "2"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=cwd or suite,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    return output


@pytest.mark.parametrize("selection", ["default", "tests", ".", "absolute", "cwd"])
def test_full_suite_uses_eight_workers_and_runs_each_test_once(
    suite: Path, selection: str
) -> None:
    args = () if selection in {"default", "cwd"} else (selection,)
    if selection == "absolute":
        args = (str(suite / "tests"),)
    _run(suite, args, cwd=suite / "tests" if selection == "cwd" else None)
    result = json.loads((suite / "result.json").read_text())
    assert result == {"workers": 8, "distribution": "loadfile", "exitstatus": 0}
    observations = [
        json.loads(path.read_text()) for path in (suite / "observations").glob("*.json")
    ]
    assert len(observations) == 16
    assert len({row["node"] for row in observations}) == 16
    assert len({row["worker"] for row in observations}) == 8
    for index in range(8):
        rows = [row for row in observations if f"test_{index}.py::" in row["node"]]
        assert len({(row["worker"], row["pid"]) for row in rows}) == 1


@pytest.mark.parametrize(
    "args",
    [
        ("tests/nested",),
        ("tests/nested/test_0.py",),
        ("tests/nested/test_0.py::test_probe[a]",),
        ("-k", "probe"),
        ("-m", "smoke"),
        ("--lf",),
        ("--sw",),
        ("--sw-skip",),
        ("--sw-reset",),
        ("--collect-only",),
        ("--ignore", "tests/nested/test_0.py"),
        ("--deselect", "tests/nested/test_0.py::test_probe[a]"),
        ("-n", "0"),
    ],
)
def test_focused_or_diagnostic_runs_stay_serial(
    suite: Path, args: tuple[str, ...]
) -> None:
    _run(suite, args)
    result = json.loads((suite / "result.json").read_text())
    assert result == {"workers": 0, "distribution": "no", "exitstatus": 0}


def test_explicit_worker_count_and_failed_worker_result(suite: Path) -> None:
    path = suite / "tests" / "nested" / "test_0.py"
    path.write_text(path.read_text() + "\ndef test_failure():\n    assert False\n")
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "tests/nested"],
        cwd=suite,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "1 failed, 16 passed" in output
    result = json.loads((suite / "result.json").read_text())
    assert result == {"workers": 2, "distribution": "loadfile", "exitstatus": 1}
