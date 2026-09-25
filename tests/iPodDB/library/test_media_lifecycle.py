"""Import, edit, replace and remove media through the same public Library API."""

import hashlib
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_lyrics_writing import lyrics_resource

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import (
    IPodLibrary,
    MediaContent,
    MediaType,
    PlaylistEntry,
    Track,
    TrackChapter,
    TrackMetadata,
)
from iPodDB.library.writing import FileDependency, PreparedMedia, WriteResources


def prepared_media(
    track: Track, data: bytes, *, content: MediaContent = MediaContent.AUDIO
) -> PreparedMedia:
    return PreparedMedia(
        track.track_id,
        FileDependency(
            track.metadata.location, len(data), hashlib.sha256(data).hexdigest()
        ),
        filetype=0
        if content is MediaContent.DOCUMENT
        else int.from_bytes(b"M4A ", "big"),
        mp3_flag=0,
        audio_format_flag=0 if content is MediaContent.DOCUMENT else 0xFFFF,
        mpeg_audio_type=0,
        gapless_audio_payload_size=0,
        content=content,
    )


@pytest.mark.parametrize("media_type", list(MediaType))
def test_import_edit_replace_remove_preserves_other_media(
    media_type: MediaType,
) -> None:
    source = browse_source()
    original = source.serialize()
    document = media_type in (MediaType.PDF_BOOK, MediaType.EPUB_BOOK)
    content = MediaContent.DOCUMENT if document else MediaContent.AUDIO
    payload = b"captured media content"
    track = Track(
        -1,
        "Imported",
        "New artist",
        "New album",
        0 if document else 120000,
        size_bytes=len(payload),
        bitrate_kbps=0 if document else 128,
        media_types=(media_type,),
        show="Series"
        if media_type in (MediaType.TV_SHOW, MediaType.VIDEO_PODCAST)
        else "",
        metadata=TrackMetadata(
            file_format="Document" if document else "AAC audio file",
            sample_rate_hz=0 if document else 44100,
            location=f"iPod_Control/Music/F00/new.{'bin' if document else 'm4a'}",
            composer="New composer",
            chapters=()
            if document
            else (TrackChapter("Opening", 0), TrackChapter("Closing", 60000)),
        ),
    )
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        tracks=(*source.snapshot.tracks, track),
        playlists=(
            replace(
                playlist, entries=(*playlist.entries, PlaylistEntry("imported", -1))
            ),
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=(prepared_media(track, payload, content=content),),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is not None, result.issues
    assert source.serialize() == original
    output = result.prepared
    identity = next(
        m.output_id
        for m in output.identities
        if m.subject == "track" and m.draft_id == -1
    )
    imported = next(t for t in output.snapshot.tracks if t.track_id == identity)
    assert imported.media_types == (media_type,)
    assert imported.metadata.chapters == track.metadata.chapters
    assert imported.ipod is not None and imported.ipod.db_track_id
    assert imported.ipod.secondary_db_track_id == imported.ipod.db_track_id
    assert len({t.ipod.db_track_id for t in output.snapshot.tracks if t.ipod}) == len(
        output.snapshot.tracks
    )

    source = IPodLibrary(output.itunes)
    edited = replace(
        imported,
        title="Edited",
        album="Renamed album",
        metadata=replace(
            imported.metadata,
            lyrics="Words",
            chapters=()
            if document
            else (
                TrackChapter("Renamed opening", 0),
                TrackChapter("Closing", 60000),
            ),
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(
            edited if t.track_id == identity else t for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(lyrics=(lyrics_resource(edited, payload),)),
    )
    assert result.prepared is not None, result.issues
    edited = next(t for t in result.prepared.snapshot.tracks if t.track_id == identity)
    assert edited.metadata.has_lyrics and edited.title == "Edited"
    assert (
        edited.ipod is not None and edited.ipod.db_track_id == imported.ipod.db_track_id
    )

    source = IPodLibrary(result.prepared.itunes)
    replacement_data = payload + b" replacement"
    replacement = replace(
        edited,
        size_bytes=len(replacement_data),
        length_ms=0 if document else 180000,
        metadata=replace(
            edited.metadata,
            location=f"iPod_Control/Music/F00/replaced.{'bin' if document else 'm4a'}",
            sample_rate_hz=0 if document else 48000,
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replacement if t.track_id == identity else t for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=(prepared_media(replacement, replacement_data, content=content),),
            lyrics=(lyrics_resource(replacement, replacement_data),),
        ),
    )
    assert result.prepared is not None, result.issues
    header = next(
        s.chunk.header
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
        if s.chunk.header.track_id == identity
    )
    assert header.size == header.size_2 == len(replacement_data)
    assert header.sample_rate_2 == (0 if document else 48000)
    assert header.length == replacement.length_ms
    assert header.db_track_id == imported.ipod.db_track_id

    source = IPodLibrary(result.prepared.itunes)
    desired = replace(
        source.snapshot,
        tracks=tuple(t for t in source.snapshot.tracks if t.track_id != identity),
        playlists=tuple(
            replace(p, entries=tuple(e for e in p.entries if e.track_id != identity))
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert (
        result.prepared.snapshot.tracks == IPodLibrary(original.itunes).snapshot.tracks
    )
    assert all(identity not in p.track_ids for p in result.prepared.snapshot.playlists)
