"""Validate native candidates and assemble flat, checksummed GitHub release assets.

Run with UV's --no-project mode. This assembler uses only the standard library;
it neither downloads dependencies nor publishes a release.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scripts.prepare_release_sources import read_manifest, verify
from scripts.prepare_store_kit import (
    PRIVATE_FIXTURES,
    deterministic_archive,
    regular_file,
    sha256,
    working_tree_sources,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_ASSET_BYTES = 2 * 1024**3
TARGETS = (
    ("windows-2022", "Windows-AMD64.zip", None),
    ("macos-14", "macOS-arm64.zip", "arm64"),
    ("macos-15-intel", "macOS-x86_64.zip", "x86_64"),
    ("ubuntu-24.04", "Linux-x86_64.tar.gz", None),
)


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_sdist(path: Path) -> None:
    """The independently built Python sdist must not expose private fixtures."""
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            # Check both published names and link targets, regardless of the
            # builder's top-level directory name. Reject links to private inputs
            # even when the public member itself has an innocuous filename.
            for value in (member.name, member.linkname):
                normalized = value.replace("\\", "/")
                if any(
                    normalized == private or normalized.endswith("/" + private)
                    for private in PRIVATE_FIXTURES
                ):
                    raise ValueError(f"Python sdist exposes private fixture: {value}")


def _source_archives(output: Path, members: Sequence[tuple[str, Path]]) -> None:
    """Partition complete upstream archives with room for tar/gzip overhead."""
    budget = MAX_ASSET_BYTES - 16 * 1024**2
    groups: list[list[tuple[str, Path]]] = [[]]
    size = 0
    for name, path in sorted(members):
        required = path.stat().st_size + 10240
        if required > budget:
            raise ValueError(f"Upstream source member exceeds asset limit: {name}")
        if size + required > budget:
            groups.append([])
            size = 0
        groups[-1].append((name, path))
        size += required
    for index, group in enumerate(groups, start=1):
        suffix = "" if len(groups) == 1 else f"-{index:03d}"
        deterministic_archive(output / f"thirdparty-sources{suffix}.tar.gz", group)


def assemble(
    tag: str,
    commit: str,
    *,
    root: Path = ROOT,
    candidates: Path | None = None,
    sources: Path | None = None,
    output: Path | None = None,
) -> Path:
    """Fail closed on absent candidates, reports, source inputs, or bad hashes."""
    root = root.resolve()
    candidates = candidates or root / "build/candidates"
    sources = sources or root / "build/release-sources"
    output = output or root / "release-assets"
    if output.exists():
        raise ValueError(f"Output must be a new directory: {output}")
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    version = str(project["project"]["version"])
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None or tag != f"v{version}":
        raise ValueError(f"Tag must exactly match the project version: v{version}")
    if re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
        raise ValueError("Commit must be a full 40-character hexadecimal SHA")

    inputs: list[tuple[str, Path]] = []
    for target, suffix, architecture in TARGETS:
        candidate = candidates / f"candidate-{target}"
        name = f"iOpenPod-{version}-{suffix}"
        archive = regular_file(candidate, "dist/" + name)
        checksum = regular_file(candidate, "dist/" + name + ".sha256")
        if checksum.read_text(encoding="utf-8").strip() != f"{sha256(archive)}  {name}":
            raise ValueError(f"Native archive checksum or filename mismatch: {name}")
        inventory = regular_file(candidate, "build/packaging/licenses/inventory.json")
        entries = _json(inventory)
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Invalid dependency inventory: {target}")
        inventory_packages: list[tuple[str, str]] = []
        for entry in cast("list[object]", entries):
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid dependency inventory entry: {target}")
            fields = cast("dict[str, object]", entry)
            package_name = fields.get("name")
            package_version = fields.get("version")
            if not isinstance(package_name, str) or not isinstance(
                package_version, str
            ):
                raise ValueError(f"Invalid dependency inventory entry: {target}")
            inventory_packages.append((package_name, package_version))
        if not any(
            name.lower() == "iopenpod" and package_version == version
            for name, package_version in inventory_packages
        ):
            raise ValueError(
                f"Dependency inventory has the wrong app version: {target}"
            )
        inputs.extend(((name, archive), (name + ".sha256", checksum)))
        inputs.append((f"inventory-{target}.json", inventory))
        if architecture is not None:
            compatibility = regular_file(
                candidate, "build/packaging/macos-compatibility.json"
            )
            report = _json(compatibility)
            minimum = project["tool"]["iopenpod"]["packaging"]["macos-minimum-version"]
            if not isinstance(report, dict):
                raise ValueError(f"Invalid macOS compatibility report: {target}")
            report_fields = cast("dict[str, object]", report)
            native_files = report_fields.get("native_files")
            if (
                report_fields.get("architecture") != architecture
                or report_fields.get("minimum_macos") != minimum
                or not isinstance(native_files, list)
                or not native_files
            ):
                raise ValueError(f"Invalid macOS compatibility report: {target}")
            inputs.append((f"macos-compatibility-{architecture}.json", compatibility))

    windows = candidates / "candidate-windows-2022"
    inputs.extend(
        (name, regular_file(windows, "dist/" + name))
        for name in (
            f"iopenpod-{version}-py3-none-any.whl",
            f"iopenpod-{version}.tar.gz",
        )
    )
    _check_sdist(windows / "dist" / f"iopenpod-{version}.tar.gz")
    manifest = regular_file(root, "packaging/third-party/sources.json")
    records = read_manifest(manifest)
    if not records:
        raise ValueError("Upstream source manifest is empty")
    upstream = [
        ("archives/" + record.filename, verify(record, sources)) for record in records
    ]
    source_members = working_tree_sources(root)
    names = {name for name, _ in source_members}
    for required in (
        "pyproject.toml",
        "uv.lock",
        "main.py",
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
    ):
        if required not in names:
            raise ValueError(f"Source snapshot is missing {required}")
    upstream.extend(
        (name.removeprefix("packaging/third-party/"), path)
        for name, path in source_members
        if name.startswith("packaging/third-party/")
    )
    hashes = {name: sha256(path) for name, path in inputs}
    output.mkdir(parents=True)
    for name, path in inputs:
        shutil.copyfile(path, output / name)
        if sha256(output / name) != hashes[name]:
            raise ValueError(f"Candidate changed during assembly: {name}")
    deterministic_archive(output / "source.tar.gz", source_members)
    _source_archives(output, upstream)
    artifacts = [
        {"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(output.iterdir())
    ]
    (output / "release.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "tag": tag,
                "commit": commit.lower(),
                "artifacts": artifacts,
                "platform_acceptance": "Build and smoke checks do not establish store acceptance or macOS 12.3 execution.",
                "native_source_evidence": "Existing native evidence targets Windows; Mac- and Linux-specific source and native provenance review remain pending.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(output.iterdir())),
        encoding="utf-8",
    )
    for path in output.iterdir():
        if path.stat().st_size >= MAX_ASSET_BYTES:
            raise ValueError(f"Release asset reaches GitHub's 2 GiB limit: {path.name}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        assemble(
            args.tag,
            args.commit,
            root=args.root,
            candidates=args.candidates,
            sources=args.sources,
            output=args.output,
        )
    )


if __name__ == "__main__":
    main()
