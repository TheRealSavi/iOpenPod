import base64
import hashlib
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
