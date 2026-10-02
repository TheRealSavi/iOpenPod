"""Explicit content replacement survives an unchanged semantic projection."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    MediaContent,
    PreparedMedia,
    WriteChecksum,
    WritePhase,
    WriteResources,
    WriteTarget,
    _write_preparation,
)
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.writing import IdentityMapping, LibraryChange, WriteIssue
from iPodDB.shared.chunk import DatabaseDocument


def replacement_source() -> IPodLibrary:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(
                selection.chunk.header,
                size=64,
                size_2=64,
                sample_rate_1=44100 << 16,
                sample_rate_2=44100.0,
            ),
            children=(
                *selection.chunk.children,
                new_string_mhod(MhodType.LOCATION, ":iPod_Control:Music:F00:track.m4a"),
                new_string_mhod(MhodType.FILETYPE, "AAC audio file"),
            ),
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


def replacement_media(source: IPodLibrary) -> PreparedMedia:
    track = source.snapshot.tracks[0]
    return PreparedMedia(
        track.track_id,
        FileDependency(track.metadata.location, track.size_bytes, "a" * 64),
        filetype=int.from_bytes(b"M4A ", "big"),
        mp3_flag=1,
        audio_format_flag=0xFFFF,
        mpeg_audio_type=1,
        gapless_audio_payload_size=32,
    )


def test_replace_media_with_identical_projected_metadata() -> None:
    source = replacement_source()
    original = source.serialize()
    media = replacement_media(source)
    draft = source.begin_draft(replace_media=(media.track_id,))
    plan = source.analyze(draft)
    assert not plan.blocked, plan.issues
    assert plan.required_media == (media.track_id,)
    assert plan.changes == (
        LibraryChange("media", media.track_id, "replace", "Track 1"),
    )
    assert not plan.requires_sidecar_inventory
    assert not plan.requires_artwork_inventory
    assert plan.resolution is not None
    assert plan.resolution.snapshot == source.snapshot
    assert plan.resolution.generated_changes == ()
    assert len(plan.resolution.effects) == 1
    effect = plan.resolution.effects[0]
    assert (effect.code, effect.subject, effect.record_id, effect.causes) == (
        "media.replacement",
        "media",
        media.track_id,
        (0,),
    )
    result = source.prepare(plan, WriteResources(media=(media,)))
    assert result.prepared is not None, result.issues
    header = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    assert header.filetype == media.filetype
    assert header.mp3_flag == media.mp3_flag
    assert header.av_flag == media.audio_format_flag
    assert header.mpeg_audio_type == media.mpeg_audio_type
    assert header.gapless_audio_payload_size == media.gapless_audio_payload_size
    assert result.prepared.retained_files == (media.file,)
    actual = result.prepared.snapshot.tracks[0]
    assert (
        replace(actual, ipod=source.snapshot.tracks[0].ipod)
        == source.snapshot.tracks[0]
    )
    assert result.prepared.snapshot.tracks[1:] == source.snapshot.tracks[1:]
    assert result.prepared.snapshot.playlists == source.snapshot.playlists
    # Restoring only the five media-owned fields must recover the complete source,
    # including duplicate text, unrelated datasets, and private Playlist entries.
    output = parse_iTunesDB(result.prepared.itunes)
    selection = output.find_chunks(MhitHeader)[0]
    prior = parse_iTunesDB(original.itunes).find_chunks(MhitHeader)[0].chunk.header
    restored = replace(
        header,
        filetype=prior.filetype,
        mp3_flag=prior.mp3_flag,
        av_flag=prior.av_flag,
        mpeg_audio_type=prior.mpeg_audio_type,
        gapless_audio_payload_size=prior.gapless_audio_payload_size,
    )
    assert (
        write_iTunesDB(
            output.replace_chunk(selection, replace(selection.chunk, header=restored))
        )
        == original.itunes
    )
    assert draft.snapshot == source.snapshot
    assert source.serialize() == original


def test_replacement_with_unchanged_codec_facts_still_returns_dependency() -> None:
    source = replacement_source()
    header = (
        parse_iTunesDB(source.serialize().itunes)
        .find_chunks(MhitHeader)[0]
        .chunk.header
    )
    media = replace(
        replacement_media(source),
        filetype=header.filetype,
        mp3_flag=header.mp3_flag,
        audio_format_flag=header.av_flag,
        mpeg_audio_type=header.mpeg_audio_type,
        gapless_audio_payload_size=header.gapless_audio_payload_size,
    )
    phases: list[WritePhase] = []
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(media.track_id,))),
        WriteResources(media=(media,)),
        progress=phases.append,
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes
    assert result.prepared.snapshot == source.snapshot
    assert result.prepared.retained_files == (media.file,)
    assert WritePhase.VERIFICATION in phases


@pytest.mark.parametrize("change_media_fields", [False, True])
def test_replacement_combines_with_metadata_edits(change_media_fields: bool) -> None:
    source = replacement_source()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                title="Edited",
                size_bytes=128 if change_media_fields else track.size_bytes,
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    media = replacement_media(source)
    media = replace(media, file=replace(media.file, size=desired.tracks[0].size_bytes))
    plan = source.analyze(source.begin_draft(desired, replace_media=(track.track_id,)))
    assert plan.required_media == (track.track_id,)
    assert [(c.subject, c.action) for c in plan.changes] == [
        ("media", "replace"),
        ("track", "edit"),
    ]
    result = source.prepare(plan, WriteResources(media=(media,)))
    assert result.prepared is not None, result.issues
    actual = result.prepared.snapshot.tracks[0]
    assert actual.title == "Edited"
    assert actual.size_bytes == media.file.size


@pytest.mark.parametrize("invalid", ["duplicate", "unknown", "omitted", "new"])
def test_invalid_replacement_intent_blocks_even_with_forged_plan(invalid: str) -> None:
    source = replacement_source()
    desired = source.snapshot
    identities: tuple[int, ...] = (1,)
    code = "draft.invalid_media_replacement"
    if invalid == "duplicate":
        identities = (1, 1)
        code = "draft.duplicate_media_replacement"
    elif invalid == "unknown":
        identities = (999,)
    elif invalid == "omitted":
        desired = replace(
            desired,
            tracks=desired.tracks[1:],
            playlists=tuple(
                replace(p, entries=tuple(e for e in p.entries if e.track_id != 1))
                for p in desired.playlists
            ),
        )
    else:
        identities = (-1,)
        desired = replace(
            desired,
            tracks=(
                *desired.tracks,
                replace(desired.tracks[0], track_id=-1, ipod=None),
            ),
        )
    draft = source.begin_draft(desired, replace_media=identities, delete_omissions=True)
    plan = source.analyze(draft)
    assert plan.blocked
    assert code in {i.code for i in plan.issues}
    forged = replace(plan, issues=(), changes=(), required_media=(), resolution=None)
    result = source.prepare(forged)
    assert result.prepared is None
    assert code in {i.code for i in result.issues}


def test_replacement_requires_resources_even_with_forged_empty_summary() -> None:
    source = replacement_source()
    plan = source.analyze(source.begin_draft(replace_media=(1,)))
    result = source.prepare(
        replace(plan, changes=(), required_media=(), issues=(), resolution=None)
    )
    assert result.prepared is None
    assert any(
        i.code == "resources.missing_media" and i.record_id == 1 for i in result.issues
    )


def test_plan_and_resources_cannot_grant_replacement_without_draft_intent() -> None:
    source = replacement_source()
    explicit = source.analyze(source.begin_draft(replace_media=(1,)))
    forged = replace(explicit, draft=source.begin_draft())
    result = source.prepare(forged, WriteResources(media=(replacement_media(source),)))
    assert result.prepared is None
    assert "resources.unrequested_media" in {i.code for i in result.issues}


def test_replacement_intent_is_scoped_to_its_draft_and_source_revision() -> None:
    source = replacement_source()
    draft = source.begin_draft(replace_media=(1,))
    plan = source.analyze(draft)
    other = IPodLibrary(source.serialize().itunes)
    result = other.prepare(plan, WriteResources(media=(replacement_media(source),)))
    assert result.prepared is None
    assert "draft.wrong_source" in {i.code for i in result.issues}
    assert source.begin_draft().replace_media == ()
    assert source.analyze(source.begin_draft()).changes == ()


@pytest.mark.parametrize(
    "invalid", ["size", "path", "hash", "content", "codec", "duplicate"]
)
def test_replacement_validates_media_resources(invalid: str) -> None:
    source = replacement_source()
    original = source.serialize()
    media = replacement_media(source)
    expected = "resources.invalid_media"
    if invalid == "size":
        media = replace(media, file=replace(media.file, size=128))
    elif invalid == "path":
        media = replace(media, file=replace(media.file, relative_path="../track.m4a"))
    elif invalid == "hash":
        media = replace(media, file=replace(media.file, sha256="invalid"))
    elif invalid == "content":
        media = replace(media, content=MediaContent.VIDEO)
    elif invalid == "codec":
        media = replace(media, mp3_flag=256)
        expected = "track.field_range"
    else:
        expected = "resources.duplicate_identity"
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(1,))),
        WriteResources(media=(media, media) if invalid == "duplicate" else (media,)),
    )
    assert result.prepared is None
    assert expected in {i.code for i in result.issues}
    assert source.serialize() == original


@pytest.mark.parametrize(
    "field",
    [
        "filetype",
        "mp3_flag",
        "av_flag",
        "mpeg_audio_type",
        "gapless_audio_payload_size",
    ],
)
def test_verification_rejects_ignored_replacement_facts(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    source = replacement_source()
    original = source.serialize()

    def stale_media(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(
            document, resolved, resources, issues, device_time
        )
        selection = candidate.find_chunks(MhitHeader)[0]
        header = selection.chunk.header
        corrupted = replace(
            header,
            filetype=0 if field == "filetype" else header.filetype,
            mp3_flag=0 if field == "mp3_flag" else header.mp3_flag,
            av_flag=0 if field == "av_flag" else header.av_flag,
            mpeg_audio_type=0 if field == "mpeg_audio_type" else header.mpeg_audio_type,
            gapless_audio_payload_size=0
            if field == "gapless_audio_payload_size"
            else header.gapless_audio_payload_size,
        )
        candidate = candidate.replace_chunk(
            selection,
            replace(selection.chunk, header=corrupted),
        )
        return candidate, mappings

    monkeypatch.setattr(_write_preparation, "reconcile", stale_media)
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(1,))),
        WriteResources(media=(replacement_media(source),)),
    )
    assert result.prepared is None
    assert any(
        i.code == "verification.track_native" and i.field == field
        for i in result.issues
    )
    assert source.serialize() == original


@pytest.mark.parametrize(
    ("checksum", "issue"),
    [
        (WriteChecksum.HASH72, "target.missing_hash72_material"),
        (WriteChecksum.HASHAB, "target.missing_guid"),
    ],
)
def test_content_only_replacement_requires_device_signing_material(
    checksum: WriteChecksum, issue: str
) -> None:
    source = replacement_source()
    plan = source.analyze(
        source.begin_draft(replace_media=(1,)), WriteTarget(checksum=checksum)
    )
    assert plan.blocked
    result = source.prepare(plan, WriteResources(media=(replacement_media(source),)))
    assert result.prepared is None
    assert issue in {i.code for i in result.issues}


def test_replacement_does_not_change_source_identity_or_float_encoding() -> None:
    source = replacement_source()
    document = parse_iTunesDB(source.serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(selection.chunk.header, sample_rate_2=44099.5, size_2=0),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(1,))),
        WriteResources(
            media=(replacement_media(source),), pending_playback_sidecars=True
        ),
    )
    assert result.prepared is not None, result.issues
    output = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    prior = document.find_chunks(MhitHeader)[0].chunk.header
    assert output.sample_rate_2 == 44099.5
    assert output.size_2 == 0
    assert (output.track_id, output.db_track_id, output.db_track_id_2) == (
        prior.track_id,
        prior.db_track_id,
        prior.db_track_id_2,
    )


@pytest.mark.parametrize("header_length", [0x148, 0x1F8])
def test_replacement_preserves_retained_header_length(header_length: int) -> None:
    document = parse_iTunesDB(replacement_source().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            generic_header=replace(
                selection.chunk.generic_header, header_length=header_length
            ),
            raw_header=selection.chunk.raw_header[:header_length],
            header=replace(
                selection.chunk.header,
                size_2=0,
                album_id=0,
                artist_id_ref=0,
                composer_id=0,
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(1,))),
        WriteResources(media=(replacement_media(source),)),
    )
    assert result.prepared is not None, result.issues
    output = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert output.generic_header.header_length == header_length
    assert (
        output.header.gapless_audio_payload_size
        == replacement_media(source).gapless_audio_payload_size
    )


def test_replacement_rejects_conflicting_captured_file_identity() -> None:
    source = replacement_source()
    media = replacement_media(source)
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(1,))),
        WriteResources(
            media=(media,), file_inventory=(replace(media.file, sha256="b" * 64),)
        ),
    )
    assert result.prepared is None
    assert "resources.conflicting_file" in {i.code for i in result.issues}
