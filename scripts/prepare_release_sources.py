"""Fetch and verify pinned release source archives without installing or running them.

The manifest records source evidence; it is not a claim that every release gate
has passed. Native build provenance and unresolved items live beside the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging" / "third-party" / "sources.json"


@dataclass(frozen=True)
class Source:
    name: str
    version: str
    url: str
    filename: str
    sha256: str
    size: int


def read_manifest(path: Path) -> tuple[Source, ...]:
    """Reject unsafe filenames and incomplete records before touching output."""
    data = cast("list[dict[str, object]]", json.loads(path.read_text(encoding="utf-8")))
    result: list[Source] = []
    names: set[str] = set()
    for entry in data:
        values = {
            key: entry.get(key)
            for key in ("name", "version", "url", "filename", "sha256")
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError("Incomplete source manifest entry")
        name, version, url, filename, digest = (
            str(values[key]) for key in ("name", "version", "url", "filename", "sha256")
        )
        if (
            Path(filename).name != filename
            or any(character in filename for character in "/\\:")
            or filename in {".", ".."}
            or filename in names
        ):
            raise ValueError(f"Unsafe or duplicate archive filename: {filename}")
        if not url.startswith("https://"):
            raise ValueError(f"Source requires HTTPS: {name}")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(f"Invalid SHA-256: {name}")
        size = entry.get("size")
        if not isinstance(size, int) or size <= 0:
            raise ValueError(f"Invalid source size: {name}")
        names.add(filename)
        result.append(Source(name, version, url, filename, digest, size))
    return tuple(result)


def verify(source: Source, directory: Path) -> Path:
    path = directory / source.filename
    if path.stat().st_size != source.size:
        raise ValueError(f"Source size mismatch: {source.filename}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != source.sha256:
        raise ValueError(f"Source SHA-256 mismatch: {source.filename}")
    return path


def fetch(source: Source, directory: Path) -> Path:
    """Download atomically, never accepting a corrupt cached archive."""
    destination = directory / source.filename
    if destination.exists():
        return verify(source, directory)
    temporary = destination.with_name(destination.name + ".partial")
    request = urllib.request.Request(
        source.url, headers={"User-Agent": "iOpenPod-release-sources/1"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=90) as response,
            temporary.open("wb") as output,
        ):
            while block := response.read(1024 * 1024):
                output.write(block)
        if temporary.stat().st_size != source.size:
            raise ValueError(f"Downloaded size mismatch: {source.filename}")
        with temporary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != source.sha256:
            raise ValueError(f"Downloaded SHA-256 mismatch: {source.filename}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def is_notice(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    return (
        name.startswith(("license", "licence", "copying", "copyright", "notice"))
        or name
        in {"authors", "authors.txt", "qt_attribution.json", "qt_attribution_test.json"}
        or "dependency_licenses" in parts
        or ("LICENSES" in parts and name.endswith(".txt"))
    )


def write_notices(source: Source, archive: Path, output: Path) -> dict[str, object]:
    """Read regular notice members only; never unpack paths or links from archives."""
    sections: list[str] = []
    provenance: list[dict[str, str]] = []
    with tarfile.open(archive, "r:*") as source_tar:
        for member in sorted(source_tar.getmembers(), key=lambda value: value.name):
            if not member.isfile() or not is_notice(member.name):
                continue
            if member.size > 2 * 1024 * 1024:
                raise ValueError(f"Unexpected notice size: {member.name}")
            stream = source_tar.extractfile(member)
            if stream is None:
                raise ValueError(f"Cannot read notice: {member.name}")
            content = stream.read()
            text = content.decode("utf-8", errors="replace")
            # Some source trees have executable tools named license.py. Keep
            # legal text and attribution metadata, not arbitrary build scripts.
            if "\x00" in text or member.name.endswith(
                (".py", ".c", ".h", ".cpp", ".cmake", ".sh")
            ):
                continue
            sections.append(
                f"\n{'=' * 72}\nSource file: {member.name}\n{'=' * 72}\n\n{text.rstrip()}\n"
            )
            provenance.append(
                {"member": member.name, "sha256": hashlib.sha256(content).hexdigest()}
            )
    filename = f"{source.name}-{source.version}-NOTICES.txt"
    header = (
        f"{source.name} {source.version}\n"
        f"Source: {source.url}\nArchive SHA-256: {source.sha256}\n\n"
        "These notices are preserved from the upstream source distribution.\n"
        "This may include notices for upstream components not used in iOpenPod.\n"
        "Each component retains its own license; inclusion is not relicensing.\n"
    )
    result = (header + "".join(sections)).encode("utf-8")
    (output / filename).write_bytes(result)
    return {
        "component": source.name,
        "version": source.version,
        "file": filename,
        "sha256": hashlib.sha256(result).hexdigest(),
        "members": provenance,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build" / "release-sources"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Fetch missing archives; otherwise verify offline",
    )
    parser.add_argument(
        "--notices", type=Path, help="Also assemble complete upstream notice text sets"
    )
    args = parser.parse_args()
    sources = read_manifest(args.manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    operation = fetch if args.download else verify

    def prepare_source(source: Source) -> Path:
        return operation(source, args.output)

    with ThreadPoolExecutor(max_workers=6) as executor:
        archives = tuple(executor.map(prepare_source, sources))
    if args.notices is not None:
        args.notices.mkdir(parents=True, exist_ok=True)
        records = [
            write_notices(source, archive, args.notices)
            for source, archive in zip(sources, archives, strict=True)
        ]
        (args.notices / "provenance.json").write_text(
            json.dumps(records, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"Verified {len(sources)} source archives ({sum(source.size for source in sources):,} bytes)."
    )


if __name__ == "__main__":
    main()
