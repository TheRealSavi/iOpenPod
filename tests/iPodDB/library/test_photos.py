"""Photo Library projection, lazy reads, drafts, and verified writing."""

import base64
from dataclasses import replace
from pathlib import Path

from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.ithmb import IthmbPixelFormat
from iPodDB.iTunesDB.builder.build_iTunesDB import new_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    IPodPhotoAlbumDetails,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoRepresentation,
    PhotoRepresentationKind,
    PhotoThumbnailFormat,
    select_photo_thumbnail,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "PhotosDB" / "original-photo-library.b64"
)


def _photos_bytes() -> bytes:
    return base64.b64decode(
        FIXTURE.read_text(encoding="ascii").strip(),
        validate=True,
    )


def _source() -> IPodLibrary:
    itunes = write_iTunesDB(new_iTunesDB(MhbdHeader()))
    return IPodLibrary.parse(itunes).with_photos(_photos_bytes())


def test_ipod_library_projects_photos_without_exposing_database_chunks() -> None:
    source = _source()
    photos = source.snapshot.photos

    assert photos is not None
    assert source.serialize().photos == _photos_bytes()
    assert len(photos.photos) == 1
    photo = photos.photos[0]
    assert (
        photo.photo_id,
        photo.original_date,
        photo.taken_date,
        photo.source_size_bytes,
    ) == (100, 1_700_000_000 - 2_082_844_800, 1_699_999_000 - 2_082_844_800, 34_567)
    assert tuple(item.kind for item in photo.representations) == (
        PhotoRepresentationKind.FULL_RESOLUTION,
        PhotoRepresentationKind.THUMBNAIL,
        PhotoRepresentationKind.THUMBNAIL,
    )
    assert photo.representations[0].format_id == 1
    assert tuple(item.relative_path for item in photo.representations) == (
        "Photos/Full Resolution/iOpenPod/Sunrise.jpg",
        "Photos/Thumbs/F1017_1.ithmb",
        "Photos/Thumbs/F1023_1.ithmb",
    )
    assert tuple(
        (album.name, album.kind, album.photo_ids) for album in photos.albums
    ) == (
        ("Photo Library", PhotoAlbumKind.MASTER, (100,)),
        ("Favorites", PhotoAlbumKind.ALBUM, (100,)),
    )
    assert photos.albums[1].ipod is not None
    assert photos.albums[1].ipod.transition_direction == 0
    assert tuple(item.format_id for item in photos.formats) == (1017, 1023)


def test_attaching_photos_creates_a_new_source_revision() -> None:
    itunes = write_iTunesDB(new_iTunesDB(MhbdHeader()))
    source = IPodLibrary.parse(itunes)
    old_draft = source.begin_draft()

    with_photos = source.with_photos(_photos_bytes())

    assert source.snapshot.photos is None
    assert source.serialize().photos is None
    assert with_photos.snapshot.photos is not None
    plan = with_photos.analyze(old_draft)
    assert any(issue.code == "draft.wrong_source" for issue in plan.issues)


def test_photo_read_selects_a_typed_lazy_thumbnail_range() -> None:
    source = _source()
    formats = (
        PhotoThumbnailFormat(1017, 220, 176, 440, IthmbPixelFormat.RGB565_LE),
        PhotoThumbnailFormat(1023, 320, 240, 640, IthmbPixelFormat.RGB565_LE),
    )

    read = source.photo_read(100, formats, 200)

    assert read is not None
    assert (
        read.photo_id,
        read.format_id,
        read.relative_path,
        read.offset,
        read.length,
    ) == (100, 1017, "Photos/Thumbs/F1017_1.ithmb", 0, 4096)
    assert source.photo_read(999, formats, 200) is None

    exact = source.photo_read(100, formats, 80, format_id=1023)
    assert exact is not None
    assert (
        exact.format_id,
        exact.relative_path,
        exact.offset,
        exact.length,
    ) == (1023, "Photos/Thumbs/F1023_1.ithmb", 8192, 8192)
    assert source.photo_read(100, formats, 80, format_id=9999) is None


def test_photo_read_crops_symmetric_mhni_padding_from_visible_pixels() -> None:
    photo = Photo(
        photo_id=107,
        representations=(
            PhotoRepresentation(
                kind=PhotoRepresentationKind.THUMBNAIL,
                format_id=1024,
                relative_path="Photos/Thumbs/F1024_1.ithmb",
                offset=0,
                size_bytes=8,
                # Photo MHNI dimensions include one leading padding margin;
                # the other margin is described separately by the same value.
                width=3,
                height=1,
                horizontal_padding=1,
            ),
        ),
    )
    read = select_photo_thumbnail(
        photo,
        (
            PhotoThumbnailFormat(
                1024,
                4,
                1,
                8,
                IthmbPixelFormat.RGB565_LE,
            ),
        ),
        4,
        format_id=1024,
    )

    assert read is not None
    decoded = read.decode(
        # black padding, red, green, black padding
        b"\x00\x00\x00\xf8\xe0\x07\x00\x00"
    )

    assert (decoded.width, decoded.height) == (2, 1)
    assert decoded.rgb888 == bytes((255, 0, 0, 0, 255, 0))


def test_photo_read_uses_physical_format_geometry_for_i420_planes() -> None:
    photo = Photo(
        photo_id=108,
        representations=(
            PhotoRepresentation(
                kind=PhotoRepresentationKind.THUMBNAIL,
                format_id=1067,
                relative_path="Photos/Thumbs/F1067_1.ithmb",
                offset=0,
                size_bytes=16,
                width=2,
                height=2,
                horizontal_padding=1,
            ),
        ),
    )
    read = select_photo_thumbnail(
        photo,
        (PhotoThumbnailFormat(1067, 4, 2, 6, IthmbPixelFormat.I420_LE),),
        4,
        format_id=1067,
    )

    assert read is not None
    decoded = read.decode(
        # A 4x2 I420 raster with black side padding, a white 2x2 center,
        # neutral chroma, and the device format's additional record tail.
        bytes((16, 235, 235, 16)) * 2 + bytes((128,)) * 4 + bytes(4)
    )

    assert (decoded.width, decoded.height) == (2, 2)
    assert min(decoded.rgb888) >= 250


def test_photo_metadata_and_album_edits_use_the_library_draft_contract() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    desired_photos = replace(
        photos,
        photos=(replace(photos.photos[0], rating=80),),
        albums=(
            photos.albums[0],
            replace(
                photos.albums[1],
                name="Sunsets",
                photo_ids=(),
                repeat=False,
                show_titles=False,
            ),
        ),
    )
    desired = replace(source.snapshot, photos=desired_photos)

    plan = source.analyze(source.begin_draft(desired))

    assert not plan.blocked
    assert plan.changes_photos and not plan.changes_itunes
    assert tuple(change.subject for change in plan.changes) == (
        "photo",
        "photo_album",
    )
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes
    assert result.prepared.photos is not None
    reparsed = IPodLibrary.parse(result.prepared.itunes).with_photos(
        result.prepared.photos
    )
    assert reparsed.snapshot == result.prepared.snapshot
    assert reparsed.snapshot.photos == desired_photos


def test_new_photo_album_is_appended_with_explicit_creation_policy() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    created = PhotoAlbum(
        album_id=103,
        name="Road trip",
        ipod=IPodPhotoAlbumDetails(
            album_type=2,
            previous_album_id=103,
        ),
    )
    desired_photos = replace(photos, albums=(*photos.albums, created))
    desired = replace(source.snapshot, photos=desired_photos)

    plan = source.analyze(source.begin_draft(desired))

    assert not plan.blocked
    assert plan.changes[-1].action == "add"
    result = source.prepare(plan)
    assert result.prepared is not None and result.prepared.photos is not None, (
        result.issues
    )
    assert result.prepared.snapshot.photos == desired_photos
    albums = parse_PhotosDB(result.prepared.photos).find_chunks(MhbaHeader)
    assert tuple(album.chunk.header.album_id for album in albums) == (101, 102, 103)
    assert albums[-1].chunk.header.album_type == 2
    assert albums[-1].chunk.header.previous_album_id == 103


def test_new_photo_album_without_creation_policy_fails_closed() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    desired = replace(
        source.snapshot,
        photos=replace(
            photos,
            albums=(*photos.albums, PhotoAlbum(103, "Unsafe")),
        ),
    )

    plan = source.analyze(source.begin_draft(desired))

    assert plan.blocked
    assert any(
        issue.code == "photo_album.invalid_creation_policy" for issue in plan.issues
    )


def test_photo_album_music_uses_common_track_identity_and_blocks_dangling_tracks() -> (
    None
):
    source = library().with_photos(_photos_bytes())
    photos = source.snapshot.photos
    assert photos is not None
    desired = replace(
        source.snapshot,
        photos=replace(
            photos,
            albums=(
                photos.albums[0],
                replace(photos.albums[1], play_music=True, music_track_id=1),
            ),
        ),
    )

    result = source.prepare(source.analyze(source.begin_draft(desired)))

    assert result.prepared is not None and result.prepared.photos is not None, (
        result.issues
    )
    written_photos = result.prepared.snapshot.photos
    assert written_photos is not None
    written_album = written_photos.albums[1]
    assert written_album.music_track_id == 1
    assert written_album.ipod is not None
    assert written_album.ipod.music_db_track_id == 101

    retained_reference = replace(
        result.prepared.snapshot, tracks=(source.snapshot.tracks[1],)
    )
    blocked = source.analyze(
        source.begin_draft(retained_reference, delete_omissions=True)
    )
    assert any(
        issue.code == "photo_album.missing_music_track" for issue in blocked.issues
    )

    cleared_photos = replace(
        written_photos,
        albums=(
            written_photos.albums[0],
            replace(written_album, play_music=False, music_track_id=None),
        ),
    )
    cleared = source.analyze(
        source.begin_draft(
            replace(retained_reference, photos=cleared_photos),
            delete_omissions=True,
        )
    )
    assert not any(
        issue.code == "photo_album.missing_music_track" for issue in cleared.issues
    )


def test_photo_album_deletion_requires_explicit_omission_intent() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    desired = replace(
        source.snapshot,
        photos=replace(photos, albums=photos.albums[:1]),
    )

    blocked = source.analyze(source.begin_draft(desired))
    assert blocked.blocked
    assert any(issue.code == "draft.deletion_not_enabled" for issue in blocked.issues)

    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True))
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.photos is not None
    assert tuple(album.name for album in result.prepared.snapshot.photos.albums) == (
        "Photo Library",
    )


def test_photo_deletion_requires_intent_and_prunes_every_album() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    desired_photos = replace(
        photos,
        photos=(),
        albums=tuple(replace(album, photo_ids=()) for album in photos.albums),
    )
    desired = replace(source.snapshot, photos=desired_photos)

    blocked = source.analyze(source.begin_draft(desired))
    assert blocked.blocked
    assert any(
        issue.code == "draft.deletion_not_enabled" and issue.subject == "photo"
        for issue in blocked.issues
    )

    plan = source.analyze(source.begin_draft(desired, delete_omissions=True))
    assert not plan.blocked
    assert tuple((change.subject, change.action) for change in plan.changes) == (
        ("photo", "delete"),
        ("photo_album", "edit"),
        ("photo_album", "edit"),
    )
    result = source.prepare(plan)
    assert result.prepared is not None and result.prepared.photos is not None, (
        result.issues
    )
    assert result.prepared.snapshot.photos == desired_photos
    document = parse_PhotosDB(result.prepared.photos)
    assert document.find_chunks(MhiiHeader) == ()
    assert document.find_chunks(MhiaHeader) == ()


def test_photo_deletion_cannot_leave_dangling_album_membership() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    desired = replace(
        source.snapshot,
        photos=replace(photos, photos=()),
    )

    plan = source.analyze(source.begin_draft(desired, delete_omissions=True))

    assert plan.blocked
    assert any(issue.code == "photo_album.missing_photo" for issue in plan.issues)
    result = source.prepare(replace(plan, issues=()))
    assert result.prepared is None
    assert any(issue.code == "photo_album.missing_photo" for issue in result.issues)


def test_master_photo_album_edits_fail_closed_during_analysis_and_preparation() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    master = photos.albums[0]

    for edited in (
        replace(master, name="Renamed master"),
        replace(master, photo_ids=()),
        replace(master, repeat=not master.repeat),
    ):
        desired_photos = replace(photos, albums=(edited, *photos.albums[1:]))
        plan = source.analyze(
            source.begin_draft(replace(source.snapshot, photos=desired_photos))
        )

        assert plan.blocked
        assert any(
            issue.code == "photo_album.master_read_only"
            and issue.record_id == master.album_id
            for issue in plan.issues
        )

        result = source.prepare(replace(plan, issues=()))
        assert result.prepared is None
        assert any(
            issue.code == "photo_album.master_read_only"
            and issue.record_id == master.album_id
            for issue in result.issues
        )


def test_photo_assets_and_native_representations_fail_closed_in_a_draft() -> None:
    source = _source()
    photos = source.snapshot.photos
    assert photos is not None
    changed_photo = replace(
        photos.photos[0],
        representations=photos.photos[0].representations[:1],
    )
    desired = replace(
        source.snapshot,
        photos=replace(photos, photos=(changed_photo,)),
    )

    plan = source.analyze(source.begin_draft(desired))

    assert plan.blocked
    assert any(issue.code == "photo.unsupported_edit" for issue in plan.issues)
    forged = replace(plan, issues=())
    result = source.prepare(forged)
    assert result.prepared is None
    assert any(issue.code == "photo.unsupported_edit" for issue in result.issues)


def test_unresolved_native_slideshow_music_survives_an_unrelated_photo_edit() -> None:
    document = parse_PhotosDB(_photos_bytes())
    album = document.find_chunks(MhbaHeader)[1]
    retained_native_id = 0x0102030405060708
    photos_bytes = write_PhotosDB(
        document.replace_chunk(
            album,
            replace(
                album.chunk,
                header=replace(
                    album.chunk.header,
                    db_track_id_ref=retained_native_id,
                ),
            ),
        )
    )
    source = IPodLibrary.parse(write_iTunesDB(new_iTunesDB(MhbdHeader()))).with_photos(
        photos_bytes
    )
    photos = source.snapshot.photos
    assert photos is not None
    unresolved = photos.albums[1]
    assert unresolved.music_track_id is None
    assert unresolved.ipod is not None
    assert unresolved.ipod.music_db_track_id == retained_native_id
    desired = replace(
        source.snapshot,
        photos=replace(
            photos,
            albums=(photos.albums[0], replace(unresolved, name="Preserved")),
        ),
    )

    result = source.prepare(source.analyze(source.begin_draft(desired)))

    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.photos is not None
    preserved = result.prepared.snapshot.photos.albums[1]
    assert preserved.ipod is not None
    assert preserved.ipod.music_db_track_id == retained_native_id
