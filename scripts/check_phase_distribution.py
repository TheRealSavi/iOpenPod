"""Explicitly download optional analysis and exercise it from a native candidate."""

import argparse
import subprocess
from pathlib import Path

from iOpenPod.app.phase_runtime_install import install_phase_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    root = args.root.resolve()

    def progress(message: str) -> None:
        print(message, flush=True)

    install_phase_runtime(root=root, checkpoint=lambda: None, progress=progress)
    report = root / "frozen-runtime-check.txt"
    process = subprocess.run(
        [
            str(executable),
            "--smoke-test",
            "--smoke-test-phase-runtime",
            str(root),
            "--smoke-test-report",
            str(report),
        ],
        cwd=root,
        check=False,
        timeout=1800,
    )
    result = report.read_text(encoding="utf-8")
    print(result, end="", flush=True)
    process.check_returncode()
    if result.strip() != "iOpenPod packaged runtime check passed.":
        raise ValueError(f"Optional Phase distribution check failed: {result}")


if __name__ == "__main__":
    main()
