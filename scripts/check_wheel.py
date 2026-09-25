"""Verify distributable wheel resources against the current source tree."""

import tomllib
from pathlib import Path
from zipfile import ZipFile


def check_wheel(path: Path, root: Path) -> None:
    with ZipFile(path) as wheel:
        names = set(wheel.namelist())
        with (root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        metadata_path = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        headers = wheel.read(metadata_path).decode().split("\n\n", 1)[0].splitlines()
        if f"License-Expression: {project['license']}" not in headers:
            raise ValueError("Wheel license expression does not match the project")
        license_directory = metadata_path.removesuffix("METADATA") + "licenses/"
        for pattern in project["license-files"]:
            for source in root.glob(pattern):
                relative = source.relative_to(root).as_posix()
                if f"License-File: {relative}" not in headers:
                    raise ValueError(f"Wheel license metadata is missing {relative}")
                if wheel.read(license_directory + relative) != source.read_bytes():
                    raise ValueError(
                        f"Wheel has stale license or credit text: {relative}"
                    )
        for package in ("iOpenPod", "device_registry", "iPodDB", "storage"):
            for source in (root / "src" / package).rglob("*"):
                if not source.is_file() or "__pycache__" in source.parts:
                    continue
                relative = source.relative_to(root / "src").as_posix()
                if relative not in names:
                    raise ValueError(f"Wheel is missing {relative}")
                if source.read_bytes() != wheel.read(relative):
                    raise ValueError(f"Wheel has stale resource {relative}")
        entrypoints = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        if (
            "iopenpod_launcher:run_with_crash_logging"
            not in wheel.read(entrypoints).decode()
        ):
            raise ValueError("Installed GUI launcher missing")
        if (
            wheel.read("iopenpod_launcher.py")
            != (root / "src/iopenpod_launcher.py").read_bytes()
        ):
            raise ValueError("Installed launcher is stale")
        forbidden = ("tests/", ".scratch/", "website/", "scripts/")
        if any(name.startswith(forbidden) for name in names):
            raise ValueError("Non-runtime files leaked into the wheel")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(
            "Expected exactly one wheel in dist/; remove stale build artifacts"
        )
    check_wheel(wheels[0], root)
    print(f"Verified {wheels[0].name}")
