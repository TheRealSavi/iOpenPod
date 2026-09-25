"""Public release assembly must exclude private inputs and fail closed."""

import hashlib
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from scripts.prepare_store_kit import (
    assemble,
    deterministic_archive,
    inspect_msix,
    regular_file,
    safe_relative_path,
    source_path_allowed,
    verified_notice_files,
    verify_packaged_notices,
)


@pytest.mark.parametrize(
    "value",
    [
        "../private",
        "/absolute",
        "C:/private",
        "a\\b",
        "a/../b",
        "a//b",
        "./a",
        "a/NUL.txt",
        "CON",
        "a/last.",
        "a/new\nline",
        "a/star*name",
    ],
)
def test_archive_paths_reject_traversal_and_windows_aliases(value: str) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        safe_relative_path(value)


@pytest.mark.parametrize(
    "value",
    [
        ".scratch/plan.md",
        "build/secrets.json",
        ".venv/secret",
        "src/__pycache__/a.pyc",
        "src/.env",
        "src/.ENV",
        "packaging/windows/credentials.json",
        "docs/privatecaptures/session.png",
        "tests/fixtures/iTunesDB/private-library.b64",
        "packaging/test.pfx",
        "tests/fixtures/iTunesDB/captured-album-index-36.b64",
        "tests/fixtures/SQLiteDB/observed-postprocess-commands.plist",
    ],
)
def test_private_inputs_never_enter_public_source(value: str) -> None:
    assert not source_path_allowed(value)


@pytest.mark.parametrize(
    "value",
    [
        "uv.lock",
        "pyproject.toml",
        "src/iOpenPod/app/app.py",
        "scripts/package_app.py",
        "tests/fixtures/media/tone.wav.b64",
        "LICENSES/DJShott-icon.txt",
        ".github/workflows/release.yml",
    ],
)
def test_build_inputs_and_synthetic_fixtures_are_allowed(value: str) -> None:
    assert source_path_allowed(value)


def test_archive_is_reproducible_and_contains_exact_reviewed_bytes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_bytes(b"alpha\n")
    second.write_bytes(b"beta\n")
    archive1 = tmp_path / "one.tar.gz"
    archive2 = tmp_path / "two.tar.gz"
    rows = deterministic_archive(archive1, [("b.txt", second), ("a.txt", first)])
    deterministic_archive(archive2, [("a.txt", first), ("b.txt", second)])
    assert archive1.read_bytes() == archive2.read_bytes()
    assert rows[0]["sha256"] == hashlib.sha256(b"alpha\n").hexdigest()
    with tarfile.open(archive1) as archive:
        assert archive.getnames() == ["a.txt", "b.txt"]
        assert all(member.mtime == 0 and member.uid == 0 for member in archive)


def test_archive_rejects_case_collisions_without_extracting(tmp_path: Path) -> None:
    file = tmp_path / "input.txt"
    file.write_text("data")
    with pytest.raises(ValueError, match="Duplicate"):
        deterministic_archive(
            tmp_path / "bad.tar.gz", [("A.txt", file), ("a.txt", file)]
        )


def test_regular_file_cannot_escape_selected_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        regular_file(tmp_path, "../outside.txt")


def test_changed_notice_text_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "packaging/third-party/notices"
    directory.mkdir(parents=True)
    (directory / "license.txt").write_bytes(b"changed")
    (directory / "provenance.json").write_text(
        json.dumps(
            [
                {
                    "file": "license.txt",
                    "sha256": hashlib.sha256(b"original").hexdigest(),
                    "members": ["LICENSE"],
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="changed third-party notice"):
        verified_notice_files(tmp_path)


@pytest.mark.parametrize(
    "changed", ["LICENSE", "LICENSES/DJShott-icon.txt", "calcHashAB.NOTICE"]
)
def test_old_msix_cannot_borrow_new_license_material(
    tmp_path: Path, changed: str
) -> None:
    files = (
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
        "LICENSES/DJShott-icon.txt",
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"current")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nlicense-files=["LICENSE", "COPYING.md", "ACKNOWLEDGEMENTS.md", "LICENSES/*.txt"]\n'
    )
    hashab = tmp_path / "src/iPodDB/iTunesDB/writer/calcHashAB.NOTICE"
    hashab.parent.mkdir(parents=True)
    hashab.write_bytes(b"current HASHAB notice")
    packaged = dict.fromkeys(files, b"current")
    packaged["calcHashAB.NOTICE"] = b"current HASHAB notice"
    if changed == "LICENSES/DJShott-icon.txt":
        del packaged[changed]
    else:
        packaged[changed] = b"stale notice"
    with pytest.raises(ValueError, match="current license material"):
        verify_packaged_notices(tmp_path, list(packaged.items()))


def test_complete_candidate_binds_package_sources_and_pending_gates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    files = {
        "LICENSE": "GPL text for fixture",
        "COPYING.md": "License grant for fixture",
        "ACKNOWLEDGEMENTS.md": "Fixture credits",
        "LICENSES/DJShott-icon.txt": "Fixture permission record",
        "pyproject.toml": '[project]\nversion="2.0.0"\nlicense-files=["LICENSE", "COPYING.md", "ACKNOWLEDGEMENTS.md", "LICENSES/*.txt"]\n',
        "src/iPodDB/iTunesDB/writer/calcHashAB.NOTICE": "HASHAB notice",
        "uv.lock": "version = 1\n",
        "main.py": "print('fixture')\n",
        "packaging/windows/store-identity.toml": 'name="Example.App"\npublisher="CN=Example"\n',
        "packaging/windows/store/listing.md": "Description",
        "packaging/windows/store/privacy.html": "<p>Policy</p>",
        "packaging/windows/store/support.html": "<p>Support</p>",
        "packaging/windows/store/license.html": "<main><footer>Footer</footer></main>",
        "packaging/windows/store/certification-notes.md": "Notes",
        "packaging/windows/store/screenshots/manifest.json": "{}",
        "packaging/windows/store/assets/store-logo-300.png": "test image placeholder",
        "packaging/windows/store/submission-fields.json": json.dumps(
            {"certification": {}, "supportAndPrivacy": {}, "listing": {}}
        ),
        "tests/fixtures/iTunesDB/captured-album-index-36.b64": "private capture must be excluded",
    }
    source_bytes = b"fixture upstream bytes"
    source_directory = root / "build/release-sources"
    source_directory.mkdir(parents=True)
    (source_directory / "example.tar.gz").write_bytes(source_bytes)
    files["packaging/third-party/sources.json"] = json.dumps(
        [
            {
                "name": "example",
                "version": "1",
                "url": "https://example.com/source.tar.gz",
                "filename": "example.tar.gz",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                "size": len(source_bytes),
            }
        ]
    )
    files["packaging/third-party/notices/LICENSE.txt"] = "example notice"
    files["packaging/third-party/notices/provenance.json"] = json.dumps(
        [
            {
                "component": "example",
                "version": "1",
                "file": "LICENSE.txt",
                "sha256": hashlib.sha256(b"example notice").hexdigest(),
                "members": ["LICENSE"],
            }
        ]
    )
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    msix = tmp_path / "final.msix"
    prefix = "app/_internal/licenses/"
    with zipfile.ZipFile(msix, "w") as archive:
        archive.writestr(
            "AppxManifest.xml",
            '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Example.App" Publisher="CN=Example" Version="2.0.0.0" ProcessorArchitecture="x64" /></Package>',
        )
        archive.writestr("app/iOpenPod.exe", b"test executable bytes")
        for name in (
            "LICENSE",
            "COPYING.md",
            "ACKNOWLEDGEMENTS.md",
            "LICENSES/DJShott-icon.txt",
        ):
            archive.writestr(prefix + name, files[name])
        archive.writestr(prefix + "calcHashAB.NOTICE", "HASHAB notice")
        archive.writestr(prefix + "libsndfile-build-record.json", "{}")
        for name, content in files.items():
            if name.startswith("packaging/third-party/"):
                archive.writestr(
                    prefix + "upstream/" + name.removeprefix("packaging/third-party/"),
                    content,
                )
    output = tmp_path / "kit"
    record_path = assemble(msix, output, source_directory, root=root)
    record = json.loads(record_path.read_text())
    assert record["working_tree_dirty"] is True
    assert record["package"]["sha256"] == hashlib.sha256(msix.read_bytes()).hexdigest()
    assert record["gates"]["exact_package_wack"]["status"] == "pending"
    with tarfile.open(output / "source.tar.gz") as archive:
        assert "main.py" in archive.getnames()
        assert not any("captured-album" in name for name in archive.getnames())
        assert not any(name.startswith("build/") for name in archive.getnames())
    assert "notices.html" in (output / "site/iopenpod-2/license.html").read_text()
    assert (
        "iopenpod-2.0.0/source.tar.gz"
        in (output / "site/iopenpod-2/license.html").read_text()
    )
    with pytest.raises(ValueError, match="new directory"):
        assemble(msix, output, source_directory, root=root)


def test_msix_decodes_opc_names_once_without_treating_plus_as_space(
    tmp_path: Path,
) -> None:
    path = tmp_path / "encoded.msix"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "AppxManifest.xml",
            '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Example" Publisher="CN=Example" Version="2.0.0.0" ProcessorArchitecture="x64" /></Package>',
        )
        archive.writestr("app/iOpenPod.exe", b"fixture")
        for name in (
            "LICENSE",
            "COPYING.md",
            "ACKNOWLEDGEMENTS.md",
            "calcHashAB.NOTICE",
        ):
            archive.writestr("app/_internal/licenses/" + name, "notice")
        archive.writestr(
            "app/_internal/licenses/upstream/rust-0.1%2B1-NOTICES.txt", "encoded plus"
        )
        archive.writestr(
            "app/_internal/licenses/upstream/literal+plus.txt", "literal plus"
        )
        archive.writestr(
            "app/_internal/licenses/upstream/percent%252B.txt", "decode once"
        )
    _, notices = inspect_msix(
        path, {"name": "Example", "publisher": "CN=Example"}, "2.0.0"
    )
    names = dict(notices)
    assert names["upstream/rust-0.1+1-NOTICES.txt"] == b"encoded plus"
    assert names["upstream/literal+plus.txt"] == b"literal plus"
    assert names["upstream/percent%2B.txt"] == b"decode once"


@pytest.mark.parametrize(
    "name",
    ["app/%2e%2e/%2e%2e/private", "app/%2e%2e%2f%2e%2e%2fprivate", "C%3A/secret"],
)
def test_msix_rejects_encoded_traversal_before_extracting(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / "bad.msix"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "must never be written")
    with pytest.raises(ValueError, match="Unsafe"):
        inspect_msix(path, {"name": "Example", "publisher": "CN=Example"}, "2.0.0")
    assert not (tmp_path / "private").exists()
