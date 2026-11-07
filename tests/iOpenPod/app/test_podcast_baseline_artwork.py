"""Sync recovers retained embedded covers without feed refresh or media writes."""

import base64
import io
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event
from typing import Any

import mutagen.id3 as frames
import pytest
from PIL import Image
from tests.iOpenPod.app.podcast_sync_test_support import podcast_request
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES
from tests.iPodDB.library.test_podcast_normalization import observed_source

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import MediaKind
from iPodDB.library.writing import FileDependency

_FRAMES: Any = frames


def test_sync_recovers_retained_embedded_covers_and_repeat_is_stable(
    tmp_path: Path,
) -> None:
    media = tmp_path / "episode.mp3"
    media.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    image = io.BytesIO()
    Image.new("RGB", (64, 32), "blue").save(image, format="PNG")
    tags = _FRAMES.ID3(media)
    tags.add(_FRAMES.APIC(mime="image/png", type=3, data=image.getvalue()))
    tags.save(media)
    device = build_device(tmp_path, media_payload=media.read_bytes())
    try:
        path = device.root / "iPod_Control/iTunes/iTunesDB"
        document = parse_iTunesDB(observed_source(False).serialize().itunes)
        for row in document.find_chunks(MhitHeader):
            location = (
                f"iPod_Control/Music/F00/retained-{row.chunk.header.track_id}.mp3"
            )
            (device.root / location).write_bytes(media.read_bytes())
            document = document.replace_chunk(
                row,
                replace(
                    row.chunk,
                    children=(
                        *row.chunk.children,
                        new_string_mhod(
                            MhodType.LOCATION, ":" + location.replace("/", ":")
                        ),
                    ),
                ),
            )
        path.write_bytes(write_iTunesDB(document))
        (device.root / "iPod_Control/Artwork/ArtworkDB").unlink()
        active = device.coordinator.select_device(device.active.candidate.id)
        retained = {
            t.track_id: (
                t.ipod,
                t.metadata.location,
                (device.root / t.metadata.location).read_bytes(),
            )
            for t in active.library.tracks
        }
        assert all(t.artwork_id == 0 for t in active.library.tracks)
        result = SyncExecutor(device.coordinator).execute(
            replace(podcast_request(active), podcasts=None), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert not result.completed  # Native repairs are not Host media transfers.
        active = device.coordinator.select_device(active.candidate.id)
        for track in active.library.tracks:
            identity, location, original = retained[track.track_id]
            assert track.ipod is not None and identity is not None
            assert track.ipod.db_track_id == identity.db_track_id
            assert track.metadata.location == location
            assert (device.root / location).read_bytes() == original
            if track.media_kind is not MediaKind.PODCAST:
                assert not track.artwork_id
                continue
            assert track.artwork_id > 0
            decoded = device.coordinator.load_artwork(
                ArtworkRequest(track.artwork_id, 128)
            )
            assert decoded is not None
            center = ((decoded.height // 2) * decoded.width + decoded.width // 2) * 3
            red, green, blue = decoded.rgb888[center : center + 3]
            assert blue >= 240 and red <= 12 and green <= 12
        artworks = {t.track_id: t.artwork_id for t in active.library.tracks}
        repeated = SyncExecutor(device.coordinator).execute(
            replace(podcast_request(active), podcasts=None), lambda _: None, Event()
        )
        assert repeated.status is SyncExecutionStatus.SUCCESS, repeated.issues
        assert repeated.active is not None
        assert {
            t.track_id: t.artwork_id for t in repeated.active.library.tracks
        } == artworks
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("change_after_prepare", [False, True])
def test_retained_cover_dependency_blocks_stale_media(
    tmp_path: Path, change_after_prepare: bool
) -> None:
    device = build_device(tmp_path)
    try:
        track = device.active.library.tracks[0]
        path = device.root / track.metadata.location
        original = path.read_bytes()
        request = LibraryPreparationRequest(
            replace(
                device.active.library,
                tracks=(
                    replace(track, title="Changed"),
                    *device.active.library.tracks[1:],
                ),
            ),
            device.active,
            1,
            1,
            artwork_dependencies=(
                FileDependency(
                    track.metadata.location, len(original), sha256(original).hexdigest()
                ),
            ),
        )
        if not change_after_prepare:
            path.write_bytes(b"changed")
        review = device.coordinator.prepare_library(request, lambda _: None, Event())
        if change_after_prepare:
            assert review.result.prepared is not None, review.result.issues
            path.write_bytes(b"changed")
            result = device.coordinator.save_library(
                review, device.active, lambda _: None, Event()
            )
            assert result.active is None
            assert result.issues
        else:
            assert review.result.prepared is None
        assert (
            device.root / "iPod_Control/iTunes/iTunesDB"
        ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]
    finally:
        device.coordinator.close()
