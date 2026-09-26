import base64
import hashlib
import struct
from pathlib import Path

import pytest
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
    embedded_artwork_from_bytes,
)
from iOpenPod.app.media.sync_artwork import capture_sync_artwork
from storage import HostPath
from storage.host_input import LocalHostFile


def test_embedded_cover_uses_the_scanned_image_identity_and_storage_capture(
    tmp_path: Path,
) -> None:
    data = base64.decodebytes((FIXTURES / "chapters-cover.m4a.b64").read_bytes())
    cover = embedded_artwork_from_bytes(data)
    assert cover is not None
    path = tmp_path / "chapters.m4a"
    path.write_bytes(data)
    observed = LocalHostFile.observe(HostPath(path))
    source = HostMediaArtworkSource(
        1,
        HostArtworkKind.EMBEDDED,
        observed.path,
        observed.size_bytes,
        observed.modified_ns,
        hashlib.sha256(cover).hexdigest(),
    )
    pixels = capture_sync_artwork(source, 128, checkpoint=lambda: None)
    assert 0 < pixels.width <= 128 and 0 < pixels.height <= 128
    assert pixels.rgb888
    path.write_bytes(data + b"changed")
    with pytest.raises(ValueError, match="changed after scanning"):
        capture_sync_artwork(source, 128, checkpoint=lambda: None)


def test_large_audiobook_cover_is_read_without_loading_the_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = base64.decodebytes((FIXTURES / "chapters-cover.m4a.b64").read_bytes())
    cover = embedded_artwork_from_bytes(data)
    assert cover is not None
    path = tmp_path / "large-book.m4b"
    # A sparse MP4 free atom makes a large valid container without a large fixture.
    with path.open("wb") as output:
        output.write(data)
        output.write(struct.pack(">I4s", 65 * 1024 * 1024, b"free"))
        output.truncate(len(data) + 65 * 1024 * 1024)
    observed = LocalHostFile.observe(HostPath(path))
    source = HostMediaArtworkSource(
        1,
        HostArtworkKind.EMBEDDED,
        observed.path,
        observed.size_bytes,
        observed.modified_ns,
        hashlib.sha256(cover).hexdigest(),
    )

    def no_whole_file_read(*args: object, **kwargs: object) -> None:
        pytest.fail("Embedded artwork must use a seekable stream")

    monkeypatch.setattr(LocalHostFile, "read_bytes", no_whole_file_read)
    assert capture_sync_artwork(source, 128, checkpoint=lambda: None).rgb888
