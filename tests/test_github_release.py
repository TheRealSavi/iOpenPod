"""Release assembly preserves all platform inputs and rejects incomplete evidence."""

import hashlib
import io
import json
import shlex
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import assemble_github_release as release
from scripts.prepare_store_kit import sha256

COMMIT = "a" * 40


@pytest.fixture
def release_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def write(relative: str, content: str = "source\n") -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    write(
        "pyproject.toml",
        '[project]\nversion="2.0.0"\n[tool.iopenpod.packaging]\nmacos-minimum-version="12.3"\n',
    )
    for name in (
        "uv.lock",
        "main.py",
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
        ".github/workflows/release.yml",
    ):
        write(name)
    upstream = write(
        "build/release-sources/dependency.tar.gz", "verified upstream source"
    )
    write(
        "packaging/third-party/sources.json",
        json.dumps(
            [
                {
                    "name": "dependency",
                    "version": "1.0",
                    "url": "https://example.com/source.tar.gz",
                    "filename": upstream.name,
                    "size": upstream.stat().st_size,
                    "sha256": hashlib.sha256(upstream.read_bytes()).hexdigest(),
                }
            ]
        ),
    )
    write("packaging/third-party/notices/dependency.txt", "Upstream license")
    for target, suffix, architecture in release.TARGETS:
        prefix = f"build/candidates/candidate-{target}"
        name = f"iOpenPod-2.0.0-{suffix}"
        archive = write(prefix + "/dist/" + name, target)
        write(prefix + "/dist/" + name + ".sha256", f"{sha256(archive)}  {name}\n")
        write(
            prefix + "/build/packaging/licenses/inventory.json",
            json.dumps([{"name": "iOpenPod", "version": "2.0.0"}]),
        )
        if architecture:
            dmg_name = f"iOpenPod-2.0.0-macOS-{architecture}.dmg"
            dmg = write(prefix + "/dist/" + dmg_name, target + " installer")
            write(
                prefix + "/dist/" + dmg_name + ".sha256",
                f"{sha256(dmg)}  {dmg_name}\n",
            )
            write(
                prefix + "/build/packaging/macos-compatibility.json",
                json.dumps(
                    {
                        "architecture": architecture,
                        "minimum_macos": "12.3",
                        "native_files": [{"path": "Contents/MacOS/iOpenPod"}],
                        "target_os_execution": "pending",
                    }
                ),
            )
    write(
        "build/candidates/candidate-windows-2022/dist/iopenpod-2.0.0-py3-none-any.whl"
    )
    sdist = (
        tmp_path / "build/candidates/candidate-windows-2022/dist/iopenpod-2.0.0.tar.gz"
    )
    with tarfile.open(sdist, "w:gz") as source_archive:
        content = b"[project]\nversion='2.0.0'\n"
        member = tarfile.TarInfo("iopenpod-2.0.0/pyproject.toml")
        member.size = len(content)
        source_archive.addfile(member, io.BytesIO(content))
    members = tuple(
        (path.relative_to(tmp_path).as_posix(), path)
        for path in tmp_path.rglob("*")
        if path.is_file() and "build" not in path.relative_to(tmp_path).parts
    )

    def source_members(_root: Path) -> tuple[tuple[str, Path], ...]:
        return members

    monkeypatch.setattr(release, "working_tree_sources", source_members)
    return tmp_path


def test_assembly_keeps_all_platforms_and_verifiable_source(release_root: Path) -> None:
    output = release.assemble("v2.0.0", COMMIT, root=release_root)
    record = json.loads((output / "release.json").read_text())
    assert record["commit"] == COMMIT
    assert record["version"] == "2.0.0"
    assert len(list(output.glob("inventory-*.json"))) == 4
    assert len(list(output.glob("macos-compatibility-*.json"))) == 2
    for target, suffix, _ in release.TARGETS:
        assert (output / f"iOpenPod-2.0.0-{suffix}").read_text() == target
    for architecture in ("arm64", "x86_64"):
        assert (output / f"iOpenPod-2.0.0-macOS-{architecture}.dmg").is_file()
    for row in record["artifacts"]:
        assert sha256(output / row["name"]) == row["sha256"]
    sums = (output / "SHA256SUMS").read_text().splitlines()
    assert len(sums) == len(list(output.iterdir())) - 1
    for line in sums:
        digest, filename = line.split("  ")
        assert sha256(output / filename) == digest
    with tarfile.open(output / "source.tar.gz") as archive:
        assert ".github/workflows/release.yml" in archive.getnames()
        assert "pyproject.toml" in archive.getnames()
    with tarfile.open(output / "thirdparty-sources.tar.gz") as archive:
        assert "archives/dependency.tar.gz" in archive.getnames()
        assert "sources.json" in archive.getnames()
        assert "notices/dependency.txt" in archive.getnames()
    with pytest.raises(ValueError, match="new directory"):
        release.assemble("v2.0.0", COMMIT, root=release_root)


def test_publication_uploads_native_archives_and_mac_install_images(
    release_root: Path,
) -> None:
    release.assemble("v2.0.0", COMMIT, root=release_root)
    workflow = (release.ROOT / ".github/workflows/release.yml").read_text()
    command = next(
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("gh release create ")
    )
    patterns = [
        argument
        for argument in shlex.split(command)
        if argument.startswith("release-assets/")
    ]
    uploaded = {
        path.name for pattern in patterns for path in release_root.glob(pattern)
    }
    assert uploaded == {
        *(f"iOpenPod-2.0.0-{suffix}" for _, suffix, _ in release.TARGETS),
        "iOpenPod-2.0.0-macOS-arm64.dmg",
        "iOpenPod-2.0.0-macOS-x86_64.dmg",
    }


@pytest.mark.parametrize(
    "tag,commit",
    [("v1.0.0", COMMIT), ("2.0.0", COMMIT), ("v2.0.0", "abc"), ("v2.0.0", "z" * 40)],
)
def test_invalid_release_identity_fails_before_output(
    release_root: Path, tag: str, commit: str
) -> None:
    with pytest.raises(ValueError):
        release.assemble(tag, commit, root=release_root)
    assert not (release_root / "release-assets").exists()


@pytest.mark.parametrize(
    "relative",
    [
        "candidate-macos-15-intel/dist/iOpenPod-2.0.0-macOS-x86_64.zip",
        "candidate-macos-14/dist/iOpenPod-2.0.0-macOS-arm64.dmg",
        "candidate-ubuntu-24.04/build/packaging/licenses/inventory.json",
        "candidate-macos-14/build/packaging/macos-compatibility.json",
        "candidate-windows-2022/dist/iopenpod-2.0.0.tar.gz",
    ],
)
def test_missing_candidate_or_report_prevents_release(
    release_root: Path, relative: str
) -> None:
    (release_root / "build/candidates" / relative).unlink()
    with pytest.raises(ValueError, match="Missing"):
        release.assemble("v2.0.0", COMMIT, root=release_root)
    assert not (release_root / "release-assets").exists()


@pytest.mark.parametrize("content", ["corrupt", "0" * 64 + "  incorrect.zip\n"])
@pytest.mark.parametrize(
    "name",
    ["iOpenPod-2.0.0-Windows-AMD64.zip", "iOpenPod-2.0.0-macOS-arm64.dmg"],
)
def test_checksum_mismatch_prevents_release(
    release_root: Path, content: str, name: str
) -> None:
    checksum = (
        release_root
        / "build/candidates"
        / ("candidate-macos-14" if name.endswith(".dmg") else "candidate-windows-2022")
        / "dist"
        / (name + ".sha256")
    )
    checksum.write_text(content)
    with pytest.raises(ValueError, match="checksum or filename"):
        release.assemble("v2.0.0", COMMIT, root=release_root)


@pytest.mark.parametrize(
    "report",
    [
        [],
        {"architecture": "x86_64", "minimum_macos": "12.3", "native_files": [1]},
        {"architecture": "arm64", "minimum_macos": "15.0", "native_files": [1]},
    ],
)
def test_wrong_compatibility_report_prevents_release(
    release_root: Path, report: object
) -> None:
    path = (
        release_root
        / "build/candidates/candidate-macos-14/build/packaging/macos-compatibility.json"
    )
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="compatibility report"):
        release.assemble("v2.0.0", COMMIT, root=release_root)


def test_corrupt_source_prevents_release(release_root: Path) -> None:
    (release_root / "build/release-sources/dependency.tar.gz").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Source size mismatch"):
        release.assemble("v2.0.0", COMMIT, root=release_root)


@pytest.mark.parametrize("link", [False, True])
@pytest.mark.parametrize("prefix", ["iopenpod-2.0.0/", "other-prefix/", ""])
def test_sdist_cannot_publish_private_fixtures(
    release_root: Path, link: bool, prefix: str
) -> None:
    sdist = (
        release_root
        / "build/candidates/candidate-windows-2022/dist/iopenpod-2.0.0.tar.gz"
    )
    private = prefix + "tests/fixtures/iTunesDB/captured-album-index-36.b64"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo("iopenpod-2.0.0/public-name" if link else private)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = private
            archive.addfile(member)
        else:
            member.size = 7
            archive.addfile(member, io.BytesIO(b"private"))
    with pytest.raises(ValueError, match="sdist exposes private fixture"):
        release.assemble("v2.0.0", COMMIT, root=release_root)
    assert not (release_root / "release-assets").exists()


def test_source_groups_split_before_asset_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "MAX_ASSET_BYTES", 16 * 1024**2 + 30000)
    members: list[tuple[str, Path]] = []
    for name in ("first", "second", "third"):
        path = tmp_path / name
        path.write_bytes(b"data")
        members.append((name, path))
    output = tmp_path / "output"
    output.mkdir()
    release._source_archives(output, members)  # pyright: ignore[reportPrivateUsage]
    archives = sorted(output.glob("thirdparty-sources-*.tar.gz"))
    assert len(archives) == 2
    archived: list[str] = []
    for path in archives:
        with tarfile.open(path) as archive:
            archived.extend(archive.getnames())
    assert sorted(archived) == ["first", "second", "third"]


def test_overlarge_asset_is_rejected(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "MAX_ASSET_BYTES", 1)

    def skip_source_archives(
        _output: Path, _members: Sequence[tuple[str, Path]]
    ) -> None:
        pass

    monkeypatch.setattr(release, "_source_archives", skip_source_archives)
    with pytest.raises(ValueError, match="2 GiB limit"):
        release.assemble("v2.0.0", COMMIT, root=release_root)
