"""Source archives are inputs to a release, so corruption must fail closed."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from scripts.prepare_release_sources import Source, read_manifest, verify, write_notices


def _source(content: bytes, filename: str = "sample.tar.gz") -> Source:
    return Source(
        "sample",
        "1.0",
        "https://example.com/source.tar.gz",
        filename,
        hashlib.sha256(content).hexdigest(),
        len(content),
    )


def test_corrupt_cached_source_is_rejected(tmp_path: Path) -> None:
    source = _source(b"original")
    (tmp_path / source.filename).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify(source, tmp_path)


def test_manifest_rejects_traversal_before_download(tmp_path: Path) -> None:
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "sample",
                    "version": "1.0",
                    "url": "https://example.com/source",
                    "filename": "../outside.tar.gz",
                    "sha256": "0" * 64,
                    "size": 8,
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="Unsafe"):
        read_manifest(manifest)


def test_notice_collection_reads_text_without_extracting_paths_or_links(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "sample.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        text = b"Copyright Example. Permission is granted."
        member = tarfile.TarInfo("../../LICENCE")
        member.size = len(text)
        output.addfile(member, io.BytesIO(text))
        link = tarfile.TarInfo("source/LICENSE-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../private-file"
        output.addfile(link)
    notices = tmp_path / "notices"
    notices.mkdir()
    record = write_notices(_source(archive.read_bytes()), archive, notices)
    notice_text = (notices / str(record["file"])).read_text()
    assert "Permission is granted" in notice_text
    assert "LICENSE-link" not in notice_text
    assert not (tmp_path / "LICENCE").exists()


def test_checked_in_source_manifest_is_well_formed() -> None:
    root = Path(__file__).resolve().parents[1]
    records = read_manifest(root / "packaging" / "third-party" / "sources.json")
    assert {"pyside-setup", "ffmpeg", "pywinrt", "hashab"}.issubset(
        {record.name for record in records}
    )
