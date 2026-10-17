"""Chapter authoring matches fixed Original bytes, including the terminal atom."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_media_lifecycle import prepared_media

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, MediaContent, MediaType, Track, TrackChapter
from iPodDB.library.writing import WriteResources


@pytest.mark.parametrize("case_index", range(3))
@pytest.mark.parametrize("new_track", [False, True], ids=["existing", "import"])
@pytest.mark.parametrize("video", [False, True], ids=["audio", "video"])
def test_authored_chapters_match_original_bytes(
    case_index: int, new_track: bool, video: bool
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[2] / "fixtures/writing/chapters-original.json"
        ).read_text(encoding="utf-8")
    )["cases"][case_index]
    chapters = tuple(
        TrackChapter(c["title"], c["startpos"]) for c in fixture["chapters"]
    )
    document = parse_iTunesDB(browse_source().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(
                selection.chunk.header,
                length=chapters[-1].start_ms + 1000,
                media_type=2 if video else 1,
                video_flag=int(video),
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize().itunes
    track = Track(-1, "Concert", "", "", 0) if new_track else source.snapshot.tracks[0]
    content = b"captured media"
    if new_track:
        track = replace(
            track,
            length_ms=chapters[-1].start_ms + 1000,
            size_bytes=len(content),
            bitrate_kbps=128,
            media_types=(MediaType.VIDEO if video else MediaType.AUDIO,),
            metadata=replace(
                track.metadata,
                file_format="MPEG-4 video file" if video else "AAC audio file",
                sample_rate_hz=44100,
                location=f"iPod_Control/Music/F00/concert.{'mp4' if video else 'm4a'}",
            ),
        )
    track = replace(track, metadata=replace(track.metadata, chapters=chapters))
    desired = replace(
        source.snapshot,
        tracks=(*source.snapshot.tracks, track)
        if new_track
        else (track, source.snapshot.tracks[1]),
    )
    resources = WriteResources(
        media=(
            replace(
                prepared_media(
                    track,
                    content,
                    content=MediaContent.AUDIO_VIDEO if video else MediaContent.AUDIO,
                ),
                filetype=int.from_bytes(b"MP4 " if video else b"M4A ", "big"),
            ),
        )
        if new_track
        else (),
        pending_playback_sidecars=False,
    )

    result = source.prepare(source.analyze(source.begin_draft(desired)), resources)

    assert result.prepared is not None, result.issues
    output_id = (
        next(
            identity.output_id
            for identity in result.prepared.identities
            if identity.subject == "track" and identity.draft_id == -1
        )
        if new_track
        else track.track_id
    )
    document = parse_iTunesDB(result.prepared.itunes)
    saved = next(
        selection.chunk
        for selection in document.find_chunks(MhitHeader)
        if selection.chunk.header.track_id == output_id
    )
    chapter_chunks = tuple(
        child
        for child in saved.children
        if isinstance(child.payload, MhodChapterDataPayload)
    )
    assert len(chapter_chunks) == 1
    chapter_chunk = chapter_chunks[0]
    payload = chapter_chunk.payload_as(MhodChapterDataPayload)
    assert payload.sean.child_count == len(chapters) + 1
    assert payload.hedr is not None
    assert payload.hedr_atom_index == len(chapters)
    assert chapter_chunk.raw_body == bytes.fromhex(fixture["payload_hex"])
    reloaded = IPodLibrary(result.prepared.itunes)
    assert (
        next(
            t for t in reloaded.snapshot.tracks if t.track_id == output_id
        ).metadata.chapters
        == chapters
    )
    assert source.serialize().itunes == original
