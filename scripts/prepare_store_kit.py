"""Assemble an offline, evidence-bearing Windows Store release candidate.

Run with ``uv run python -m scripts.prepare_store_kit --msix ... --output ...``.
No account access, network requests, signing, or publication is performed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import quote, unquote
from xml.etree import ElementTree

from scripts.prepare_release_sources import read_manifest, verify

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = frozenset(
    {"src", "scripts", "packaging", "tests", "docs", "LICENSES"}
)
ROOT_SOURCE_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        "main.py",
        "README.md",
        "CONTEXT.md",
        "GLOSSARY.md",
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
    }
)
PRIVATE_FIXTURES = {
    "tests/fixtures/iTunesDB/captured-album-index-36.b64": "Device-derived fixture, excluded from distribution as a precaution.",
    "tests/fixtures/iTunesDB/captured-album-index-36.json": "Companion manifest for an excluded device-derived fixture.",
    "tests/fixtures/iTunesDB/captured-album-index-36-overrides.b64": "Device-derived fixture, excluded from distribution as a precaution.",
    "tests/fixtures/iTunesDB/captured-album-index-36-overrides.json": "Companion manifest for an excluded device-derived fixture.",
    "tests/fixtures/SQLiteDB/observed-postprocess-commands.plist": "External excerpt with unresolved redistribution provenance.",
}
BLOCKED_PARTS = frozenset(
    {
        ".git",
        ".scratch",
        ".venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".rumdl_cache",
        ".uv-cache",
    }
)
BLOCKED_SUFFIXES = frozenset(
    {".pyc", ".pyo", ".log", ".pfx", ".p12", ".pem", ".key", ".cer"}
)
# Reviewed runtime code, not stored credentials. Keep exceptions path-specific so
# similarly named secret files and private directories remain excluded.
REVIEWED_SOURCE_FILES = frozenset({"src/iOpenPod/app/scrobbling/credentials.py"})
PACKAGE_LICENSE_PREFIX = "app/_internal/licenses/"


class ByteReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def stream_sha256(stream: ByteReader) -> str:
    digest = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    """Reject paths unsafe in either POSIX archives or Windows destinations."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or character in '<>"|?*' for character in value)
        or any(part.endswith((".", " ")) for part in path.parts)
        or any(
            part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            for part in path.parts
        )
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return path


def source_path_allowed(value: str) -> bool:
    path = safe_relative_path(value)
    if value in PRIVATE_FIXTURES:
        return False
    if value in REVIEWED_SOURCE_FILES:
        return True
    if any(
        part.casefold() in BLOCKED_PARTS
        or part.casefold().startswith(
            (".env", ".secret", "private", "credential", "secret")
        )
        for part in path.parts
    ):
        return False
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return False
    return (
        value in ROOT_SOURCE_FILES
        or path.parts[0] in SOURCE_DIRECTORIES
        or value.startswith(".github/workflows/")
    )


def regular_file(root: Path, relative: str) -> Path:
    path = safe_relative_path(relative)
    current = root.resolve()
    for part in path.parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"Links are not release inputs: {relative}")
    if not current.resolve().is_relative_to(root.resolve()) or not current.is_file():
        raise ValueError(f"Missing or escaping release input: {relative}")
    return current


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git_output(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], encoding="utf-8"
    )


def working_tree_sources(root: Path) -> tuple[tuple[str, Path], ...]:
    names = git_output(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    )
    return tuple(
        (name, regular_file(root, name))
        for name in sorted(set(names.split("\x00")) - {""})
        if source_path_allowed(name) and (root / name).exists()
    )


def deterministic_archive(
    output: Path, members: Iterable[tuple[str, Path]]
) -> list[dict[str, object]]:
    """Use stable order, owner, modes, and timestamps, then verify every member."""
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with (
        output.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(
            fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
        ) as archive,
    ):
        for name, source in sorted(members):
            safe_relative_path(name)
            if name.casefold() in seen or source.is_symlink() or source.is_junction():
                raise ValueError(f"Duplicate or linked archive member: {name}")
            seen.add(name.casefold())
            digest = sha256(source)
            info = tarfile.TarInfo(name)
            info.size = source.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            with source.open("rb") as stream:
                archive.addfile(info, stream)
            rows.append({"path": name, "size": info.size, "sha256": digest})
    # A file changed while assembling must never silently produce mismatched evidence.
    with tarfile.open(output, "r:gz") as archive:
        for row, member in zip(rows, archive, strict=True):
            archived_stream = archive.extractfile(member)
            if (
                archived_stream is None
                or stream_sha256(archived_stream) != row["sha256"]
            ):
                raise ValueError(
                    f"Archive content changed during capture: {member.name}"
                )
    return rows


def inspect_msix(
    path: Path, identity: dict[str, object], version: str
) -> tuple[list[dict[str, object]], list[tuple[str, bytes]]]:
    """Inspect ZIP members without extracting paths or executing packaged binaries."""
    binaries: list[dict[str, object]] = []
    notices: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        seen: set[str] = set()
        for member in archive.infolist():
            # MakeAppx encodes OPC part names (for example '+' becomes '%2B').
            # Decode exactly once; '+' is a literal filename character, not a space.
            name = unquote(member.filename, errors="strict").rstrip("/")
            safe_relative_path(name)
            if name.casefold() in seen:
                raise ValueError(f"Duplicate MSIX member: {name}")
            seen.add(name.casefold())
            if member.is_dir():
                continue
            if PurePosixPath(name).suffix.lower() in {".exe", ".dll", ".pyd"}:
                with archive.open(member) as stream:
                    digest = stream_sha256(stream)
                binaries.append(
                    {
                        "path": name,
                        "archive_path": member.filename,
                        "size": member.file_size,
                        "sha256": digest,
                    }
                )
            if name.startswith(PACKAGE_LICENSE_PREFIX):
                notices.append(
                    (name.removeprefix(PACKAGE_LICENSE_PREFIX), archive.read(member))
                )
        manifest = ElementTree.fromstring(archive.read("AppxManifest.xml"))
        namespace = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"
        package_identity = manifest.find(namespace + "Identity")
        if package_identity is None:
            raise ValueError("MSIX has no package identity")
        expected = {
            "Name": identity["name"],
            "Publisher": identity["publisher"],
            "Version": version + ".0",
            "ProcessorArchitecture": "x64",
        }
        if any(package_identity.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "MSIX identity/version/architecture differs from this release"
            )
        required = {"LICENSE", "COPYING.md", "ACKNOWLEDGEMENTS.md", "calcHashAB.NOTICE"}
        if not required.issubset({name for name, _ in notices}):
            raise ValueError(
                "MSIX is missing required application license/credit files"
            )
        if not any(row["path"] == "app/iOpenPod.exe" for row in binaries):
            raise ValueError("MSIX is missing app/iOpenPod.exe")
    return sorted(binaries, key=lambda row: str(row["path"])), notices


def verify_packaged_notices(root: Path, notices: Sequence[tuple[str, bytes]]) -> None:
    """A current source bundle cannot make an old MSIX's missing notices pass."""
    packaged = dict(notices)
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    patterns = cast("list[str]", project["license-files"])
    expected: list[tuple[str, Path]] = []
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if not matches:
            raise ValueError(f"Missing project license files: {pattern}")
        expected.extend(
            (
                path.relative_to(root).as_posix(),
                regular_file(root, path.relative_to(root).as_posix()),
            )
            for path in matches
        )
    expected.append(
        (
            "calcHashAB.NOTICE",
            regular_file(root, "src/iPodDB/iTunesDB/writer/calcHashAB.NOTICE"),
        )
    )
    upstream = root / "packaging/third-party"
    expected.extend(
        ("upstream/" + path.relative_to(upstream).as_posix(), path)
        for path in upstream.rglob("*")
        if path.is_file()
    )
    for name, path in expected:
        content = packaged.get(name)
        if content is None or hashlib.sha256(content).hexdigest() != sha256(path):
            raise ValueError(f"MSIX is missing current license material: {name}")
    if not packaged.get("libsndfile-build-record.json"):
        raise ValueError("MSIX is missing the native libsndfile build record")


def verified_notice_files(root: Path) -> tuple[Path, list[str]]:
    directory = root / "packaging/third-party/notices"
    provenance = regular_file(directory, "provenance.json")
    records = cast(
        "list[dict[str, object]]", json.loads(provenance.read_text(encoding="utf-8"))
    )
    if not records:
        raise ValueError("Third-party notice provenance is empty")
    uncovered: list[str] = []
    for row in records:
        filename = row.get("file")
        if not isinstance(filename, str):
            raise ValueError("Missing notice filename")
        file = regular_file(directory, filename)
        if not file.stat().st_size or sha256(file) != row.get("sha256"):
            raise ValueError(f"Missing or changed third-party notice: {filename}")
        if not row.get("members"):
            uncovered.append(str(row.get("component")) + " " + str(row.get("version")))
    return directory, uncovered


def copy_files(root: Path, destination: Path, names: Sequence[str]) -> None:
    for name in names:
        source = regular_file(root, name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def json_file(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def assemble(
    msix: Path, output: Path, sources_directory: Path, *, root: Path = ROOT
) -> Path:
    """Prepare a fresh candidate; pending policy gates never become implicit passes."""
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Output must be a new directory: {output}")
    if not msix.is_file() or msix.suffix.lower() != ".msix":
        raise ValueError("An existing final MSIX is required")
    input_package_hash = sha256(msix)
    with (root / "pyproject.toml").open("rb") as stream:
        version = str(tomllib.load(stream)["project"]["version"])
    with (root / "packaging/windows/store-identity.toml").open("rb") as stream:
        identity = tomllib.load(stream)
    binaries, notices = inspect_msix(msix, identity, version)
    verify_packaged_notices(root, notices)
    sources = read_manifest(root / "packaging/third-party/sources.json")
    if not sources:
        raise ValueError("Source manifest is empty")
    upstream = [
        (source.filename, verify(source, sources_directory)) for source in sources
    ]
    notice_directory, uncovered_notices = verified_notice_files(root)
    source_members = working_tree_sources(root)
    source_names = {name for name, _ in source_members}
    for required in (
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
        "pyproject.toml",
        "uv.lock",
        "main.py",
    ):
        if required not in source_names:
            raise ValueError(f"Source snapshot is missing {required}")
    store = root / "packaging/windows/store"
    for required in (
        "listing.md",
        "submission-fields.json",
        "privacy.html",
        "support.html",
        "license.html",
        "certification-notes.md",
        "screenshots/manifest.json",
        "assets/store-logo-300.png",
    ):
        regular_file(store, required)
    output.mkdir(parents=True)
    package = output / msix.name
    shutil.copyfile(msix, package)
    if sha256(package) != input_package_hash:
        raise ValueError("MSIX changed during kit assembly")
    source_readme = output / "SOURCE-README.txt"
    source_readme.write_text(
        "iOpenPod " + version + " source snapshot\n\n"
        "The source archive captures allowlisted working-tree files, including uncommitted changes.\n"
        "Use Python 3.12 and UV: uv sync --locked --group packaging; uv run python -m scripts.package_app --help.\n"
        "See docs/packaging.md and docs/licensing.md for native build and dependency-source instructions.\n"
        "The upstream-source archive contains the manifest-pinned sources and full upstream notices.\n"
        "Source availability is not proof that an unidentified native binary was rebuilt from those sources.\n\n"
        "Intentional source-distribution exclusions (not needed to build the app):\n"
        + "".join(
            name + ": " + reason + "\n" for name, reason in PRIVATE_FIXTURES.items()
        )
        + "\nTests using those excerpts require private fixtures and are not runnable as supplied:\n"
        "tests/iPodDB/library/test_album_index.py (captured cases);\n"
        "tests/iOpenPod/app/services/test_device_coordinator.py and tests/iOpenPod/app/test_music_import.py (SQLite excerpt cases).\n"
        "Synthetic generated media and writer golden fixtures remain included. No runtime or native build needs the excluded captures.\n",
        encoding="utf-8",
    )
    source_archive = output / "source.tar.gz"
    source_rows = deterministic_archive(
        source_archive, (*source_members, ("SOURCE-README.txt", source_readme))
    )
    upstream_members = [("archives/" + name, path) for name, path in upstream]
    upstream_members.append(
        ("sources.json", root / "packaging/third-party/sources.json")
    )
    upstream_members.extend(
        ("notices/" + path.relative_to(notice_directory).as_posix(), path)
        for path in notice_directory.rglob("*")
        if path.is_file()
    )
    third_party_rows = deterministic_archive(
        output / "thirdparty.tar.gz", upstream_members
    )
    listing_names = [
        name.removeprefix("packaging/windows/store/")
        for name, _ in source_members
        if name.startswith("packaging/windows/store/")
    ]
    copy_files(store, output / "listing", listing_names)
    site = output / "site/iopenpod-2"
    site.mkdir(parents=True)
    copy_files(store, site, ("privacy.html", "support.html", "license.html"))
    (site / "LICENSE.txt").write_bytes(regular_file(root, "LICENSE").read_bytes())
    (site / "ACKNOWLEDGEMENTS.md").write_bytes(
        regular_file(root, "ACKNOWLEDGEMENTS.md").read_bytes()
    )
    for name, content in notices:
        destination = site / "notices" / safe_relative_path(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    notice_links = "\n".join(
        f'<li><a href="notices/{quote(name, safe="/")}">{html.escape(name)}</a></li>'
        for name, _ in sorted(notices)
    )
    (site / "notices.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>iOpenPod packaged license notices</title></head><body><main><h1>Packaged license notices</h1><p>These exact files are included in the prepared Windows package. Components retain their own licenses and copyright notices.</p><p><a href="license.html">License, credits, and source</a></p><ul>'
        + notice_links
        + "</ul></main></body></html>\n",
        encoding="utf-8",
    )
    release_url = (
        f"https://github.com/TheRealSavi/iOpenPod/releases/download/iopenpod-{version}/"
    )
    license_page = site / "license.html"
    links = (
        "<section><h2>Prepared release downloads</h2><p>These URLs become available when the release assets are published. This staged page is not evidence of publication.</p><ul>"
        f'<li><a href="{html.escape(release_url)}source.tar.gz">iOpenPod {html.escape(version)} source and build files</a></li>'
        f'<li><a href="{html.escape(release_url)}thirdparty.tar.gz">Pinned upstream source archives and full notices</a></li>'
        '<li><a href="LICENSE.txt">Full GPL license</a></li><li><a href="notices.html">Complete packaged license notices</a></li><li><a href="ACKNOWLEDGEMENTS.md">Acknowledgements</a></li></ul></section>'
    )
    license_page.write_text(
        license_page.read_text(encoding="utf-8").replace(
            "<footer>", links + "<footer>"
        ),
        encoding="utf-8",
    )
    listing_file = output / "listing/submission-fields.json"
    listing = cast(
        "dict[str, object]", json.loads(listing_file.read_text(encoding="utf-8"))
    )
    certification = cast("dict[str, object]", listing["certification"])
    certification.update({"packageFile": msix.name, "packageSha256": sha256(package)})
    support = cast("dict[str, object]", listing["supportAndPrivacy"])
    support["sourceReleaseUrl"] = release_url + "source.tar.gz"
    store_listing = cast("dict[str, object]", listing["listing"])
    store_listing["appTileIcon"] = {
        "file": "assets/store-logo-300.png",
        "dimensions": "300x300",
    }
    json_file(listing_file, listing)
    json_file(output / "binary-inventory.json", binaries)
    json_file(output / "source-inventory.json", source_rows)
    json_file(output / "thirdparty-inventory.json", third_party_rows)
    gates: dict[str, object] = {
        "upstream_archive_integrity": {"status": "verified", "count": len(sources)},
        "archive_contents": {
            "status": "verified",
            "method": "Re-read every archive member and compare SHA-256.",
        },
        "fixture_distribution": {
            "status": "reviewed_with_exclusions",
            "excluded": PRIVATE_FIXTURES,
        },
        "public_source_snapshot_review": {
            "status": "pending",
            "reason": "Review source-inventory.json before publication. Path filtering and named fixture exclusions do not establish that every source file is suitable for public disclosure.",
        },
        "native_binary_source_provenance": {
            "status": "pending",
            "reason": "Requires per-binary build/source/license audit; an upstream archive alone does not prove correspondence.",
        },
        "third_party_license_coverage": {
            "status": "pending",
            "notice_records_without_embedded_legal_text": uncovered_notices,
        },
        "original_app_icon_permission": {
            "status": "documented",
            "creator": "DJShott",
            "scope": "Permission for future iOpenPod app updates; no standalone reuse or blanket GPL grant asserted.",
            "evidence": "LICENSES/DJShott-icon.txt",
            "evidence_sha256": sha256(root / "LICENSES/DJShott-icon.txt"),
        },
        "exact_package_wack": {"status": "pending"},
        "installed_device_and_uninstall_tests": {"status": "pending"},
        "public_pages_and_source_downloads": {"status": "pending"},
        "partner_center_account_and_iarc": {"status": "pending"},
        "microsoft_certification": {"status": "pending"},
    }
    artifact_rows = [
        {
            "path": path.relative_to(output).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    ]
    record = {
        "schema_version": 1,
        "status": "candidate_pending_verification",
        "version": version,
        "root_commit": git_output(root, "rev-parse", "HEAD").strip(),
        "working_tree_dirty": bool(
            git_output(
                root, "status", "--porcelain", "--untracked-files=normal"
            ).strip()
        ),
        "snapshot_kind": "allowlisted current working tree, not git HEAD",
        "package": {"file": package.name, "sha256": sha256(package)},
        "release_url_candidate": release_url,
        "gates": gates,
        "artifacts": artifact_rows,
        "integrity_convention": "Artifact hashes are in this record. SHA256SUMS.txt also hashes this record; the checksum file does not hash itself.",
        "note": "No network, signing, account access, publication, or legal clearance is performed by this assembler.",
    }
    record_path = output / "release-record.json"
    json_file(record_path, record)
    hashes = [f"{row['sha256']}  {row['path']}" for row in artifact_rows]
    hashes.append(f"{sha256(record_path)}  release-record.json")
    (output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    return record_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msix", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="A new candidate directory; never overwritten.",
    )
    parser.add_argument("--sources", type=Path, default=ROOT / "build/release-sources")
    args = parser.parse_args()
    record = assemble(args.msix.resolve(), args.output, args.sources.resolve())
    print(f"Prepared local candidate: {record}")
    print("Review release-record.json: unresolved gates remain pending.")


if __name__ == "__main__":
    main()
