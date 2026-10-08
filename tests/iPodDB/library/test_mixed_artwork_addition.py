"""New Tracks receive artwork while retained F1061 extents remain unchanged."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_f1061_mixed_layouts import mixed_source
from tests.iPodDB.library.test_write_artwork import BLUE

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    PreparedMedia,
    Track,
    TrackMetadata,
    content_sha256,
    read_content,
)


@pytest.mark.parametrize("visible_width, stored_rows", [(55, 56), (56, 55), (55, 55)])
def test_new_track_gets_full_cover_with_mixed_retained_f1061_extents(
    visible_width: int, stored_rows: int
) -> None:
    source, target, resources = mixed_source(6272, allocation=6272)
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[1]
    container = selection.chunk.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            children=(
                replace(
                    container,
                    payload=replace(
                        container.payload,
                        child=replace(
                            location,
                            header=replace(
                                location.header,
                                image_width=visible_width,
                                image_height=stored_rows,
                                image_size=112 * stored_rows,
                            ),
                        ),
                    ),
                ),
                *selection.chunk.children[1:],
            ),
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    original = source.serialize()
    assert original.artwork is not None
    retained_rows = tuple(
        s.chunk for s in parse_ArtworkDB(original.artwork).find_chunks(MhiiHeader)
    )
    payload = b"new captured media"
    track = Track(
        -1,
        "New Track",
        "Artist",
        "Album",
        1000,
        size_bytes=len(payload),
        artwork_id=BLUE.artwork_id,
        metadata=TrackMetadata(
            location="iPod_Control/Music/F00/new.mp3",
            sample_rate_hz=44100,
            file_format="MP3 audio file",
        ),
    )
    media = PreparedMedia(
        track.track_id,
        FileDependency(track.metadata.location, len(payload), content_sha256(payload)),
        filetype=int.from_bytes(b"MP3 ", "big"),
        mp3_flag=1,
        audio_format_flag=0,
        mpeg_audio_type=0,
        gapless_audio_payload_size=0,
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, track))

    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        replace(resources, media=(media,), pending_playback_sidecars=False),
    )

    assert result.prepared is not None, result.issues
    prepared = result.prepared
    assert prepared.artwork is not None
    output = parse_ArtworkDB(prepared.artwork)
    output_rows = tuple(s.chunk for s in output.find_chunks(MhiiHeader))
    assert output_rows[:2] == retained_rows
    assert len(output_rows) == 3
    assert output.find_chunks(MhifHeader)[0].chunk.header.image_size == 6272
    assert len(prepared.artwork_files) == 1
    file = prepared.artwork_files[0]
    prefix = resources.files[0]
    assert file.relative_path == prefix.dependency.relative_path
    assert read_content(file.data, 0, len(prefix.data)) == prefix.data
    assert len(file.data) == len(prefix.data) + 6272
    assert prepared.snapshot.tracks[:2] == source.snapshot.tracks
    imported = prepared.snapshot.tracks[-1]
    assert imported.track_id > 0 and imported.ipod is not None
    assert imported.artwork_id == output_rows[-1].header.image_id
    assert imported.artwork_id not in {t.artwork_id for t in source.snapshot.tracks}
    assert output_rows[-1].header.db_track_id_ref == imported.ipod.db_track_id
    assert media.file in prepared.retained_files
    updated = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork)
    assert updated.snapshot == prepared.snapshot
    read = updated.artwork_read(imported.artwork_id, target.cover_formats, 56)
    assert read is not None and read.length == 6272
    assert read.offset == len(prefix.data)
    pixels = read.decode(read_content(file.data, read.offset, read.length))
    assert (pixels.width, pixels.height) == (56, 56)
    assert pixels.rgb888[2] > 240
    assert source.serialize() == original
