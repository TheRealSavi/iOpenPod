"""Project dev commands — the only supported way to lint, typecheck, and test.

Usage:
    uv sync
    uv run python scripts/dev.py check
    uv run python scripts/dev.py lint
    uv run python scripts/dev.py fmt
    uv run python scripts/dev.py types
    uv run python scripts/dev.py test [pytest args...]
    uv run python scripts/dev.py arch
    uv run python scripts/dev.py doctor
    uv run iopenpod
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT_PATHS = ("src/iopenpod", "scripts", "tests")


def _run(argv: list[str]) -> int:
    completed = subprocess.run(argv, cwd=REPO_ROOT)
    return int(completed.returncode)


def lint() -> int:
    return _run([sys.executable, "-m", "ruff", "check", *LINT_PATHS])


def fmt(*, check: bool = False) -> int:
    argv = [sys.executable, "-m", "ruff", "format"]
    if check:
        argv.append("--check")
    argv.extend(LINT_PATHS)
    return _run(argv)


def types() -> int:
    return _run([sys.executable, "-m", "mypy"])


def test(pytest_argv: list[str]) -> int:
    return _run([sys.executable, "-m", "pytest", *pytest_argv])


def arch() -> int:
    return _run([sys.executable, "scripts/check_architecture.py"])


def _tool_version(module: str, *, version_flag: str = "--version") -> str:
    completed = subprocess.run(
        [sys.executable, "-m", module, version_flag],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0] if output else "unknown"


def doctor() -> int:
    venv_python = Path(sys.executable).resolve()
    in_venv = venv_python.is_relative_to((REPO_ROOT / ".venv").resolve())
    pre_commit_hook = (REPO_ROOT / ".git" / "hooks" / "pre-commit").is_file()
    python_version_file = (REPO_ROOT / ".python-version").read_text().strip()

    print("iOpenPod dev environment", flush=True)
    print(f"  repo:            {REPO_ROOT}", flush=True)
    print(f"  python:          {sys.version.split()[0]} ({venv_python})", flush=True)
    print(f"  in project venv: {'yes' if in_venv else 'NO — run via uv run'}", flush=True)
    print(f"  .python-version: {python_version_file}", flush=True)
    print(f"  pre-commit hook: {'installed' if pre_commit_hook else 'NOT installed — run: uv run pre-commit install'}", flush=True)
    print("", flush=True)
    print("Dev tools (from .venv via uv sync):", flush=True)

    tools_ok = True
    for module, label in (
        ("ruff", "ruff"),
        ("mypy", "mypy"),
        ("pytest", "pytest"),
        ("pre_commit", "pre-commit"),
    ):
        try:
            print(f"  {label:12} {_tool_version(module)}", flush=True)
        except Exception as exc:
            tools_ok = False
            print(f"  {label:12} MISSING ({exc})", flush=True)

    print("", flush=True)
    print("Canonical commands:", flush=True)
    print("  uv sync", flush=True)
    print("  uv run python scripts/dev.py lint", flush=True)
    print("  uv run python scripts/dev.py test", flush=True)
    print("  uv run python scripts/dev.py check", flush=True)
    print("  uv run iopenpod", flush=True)

    if not in_venv:
        print("\nWARNING: re-run through uv (e.g. uv run python scripts/dev.py doctor)", flush=True)
        return 1
    if not pre_commit_hook:
        print("\nNOTE: install git hooks with: uv run pre-commit install", flush=True)
    if not tools_ok:
        print("\nWARNING: run uv sync to install missing dev tools", flush=True)
        return 1
    return 0


def check() -> int:
    steps = (
        ("lint", lint),
        ("types", types),
        ("test", lambda: test([])),
        ("arch", arch),
    )
    for name, step in steps:
        print(f"==> {name}", flush=True)
        if step() != 0:
            print(f"dev {name} failed", file=sys.stderr, flush=True)
            return 1
    print("dev check passed", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run iOpenPod dev checks (always invoke via uv run).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("lint", help="Run ruff check")
    subparsers.add_parser("fmt", help="Run ruff format")
    subparsers.add_parser("fmt-check", help="Verify ruff formatting")
    subparsers.add_parser("types", help="Run mypy")
    subparsers.add_parser("arch", help="Run architecture guardrails")
    subparsers.add_parser("doctor", help="Report dev environment health")

    test_parser = subparsers.add_parser("test", help="Run pytest")
    test_parser.add_argument("pytest_argv", nargs=argparse.REMAINDER)

    subparsers.add_parser("check", help="Run lint, types, test, and arch")

    args = parser.parse_args(argv)

    match args.command:
        case "lint":
            return lint()
        case "fmt":
            return fmt()
        case "fmt-check":
            return fmt(check=True)
        case "types":
            return types()
        case "test":
            return test(args.pytest_argv)
        case "arch":
            return arch()
        case "doctor":
            return doctor()
        case "check":
            return check()
        case _:
            parser.error(f"unknown command: {args.command}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
