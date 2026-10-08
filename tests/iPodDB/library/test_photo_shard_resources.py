"""Shared Photo files require distinct bounded ranges and unchanged old prefixes."""

from dataclasses import replace

import pytest
from tests.iOpenPod.app.media.test_photo_sync import (
    FORMATS,
    _asset,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.media.photo_shards import pack_photo_shards
from iOpenPod.app.media.photo_sync import photo_library_with_asset
from iPodDB.library import (
    FileDependency,
    PreparedPhoto,
    SourceFile,
    WriteResources,
    WriteTarget,
    content_sha256,
)


def _shared_assets() -> tuple[PreparedPhoto, PreparedPhoto]:
    first, second = _asset(), _asset(photo_id=102, shard=2)
    shards = tuple(
        SourceFile(
            replace(a.dependency, size=len(data), sha256=content_sha256(data)), data
        )
        for a, b in zip(first.files[1:], second.files[1:], strict=True)
        if isinstance(a.data, bytes) and isinstance(b.data, bytes)
        for data in (a.data + b.data,)
    )
    return (
        replace(first, files=(first.files[0], *shards)),
        replace(
            second,
            photo=replace(
                second.photo,
                representations=(
                    second.photo.representations[0],
                    *(
                        replace(
                            rep,
                            relative_path=shard.dependency.relative_path,
                            offset=rep.size_bytes,
                        )
                        for rep, shard in zip(
                            second.photo.representations[1:], shards, strict=True
                        )
                    ),
                ),
            ),
            files=(second.files[0], *shards),
        ),
    )


def test_shared_files_verify_and_preserve_nonzero_offsets() -> None:
    source = library()
    assets = _shared_assets()
    photos = None
    for asset in assets:
        photos = photo_library_with_asset(photos, asset)
    result = source.prepare(
        source.analyze(
            source.begin_draft(replace(source.snapshot, photos=photos)),
            WriteTarget(photo_formats=FORMATS, photos_root_value=6),
        ),
        WriteResources(photos=assets),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.photos == photos


def test_case_variant_retained_shard_accepts_verified_append() -> None:
    source = library()
    old = _asset().files[1]
    path = "Photos/Thumbs/f1024_7.ITHMB"
    prefix = replace(old, dependency=replace(old.dependency, relative_path=path))
    asset = pack_photo_shards(
        (_asset(photo_id=102),), prefixes=(prefix,), max_file_bytes=256
    )[0]
    photos = photo_library_with_asset(None, asset)
    result = source.prepare(
        source.analyze(
            source.begin_draft(replace(source.snapshot, photos=photos)),
            WriteTarget(photo_formats=FORMATS, photos_root_value=6),
        ),
        WriteResources(photos=(asset,)),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.photos == photos
    assert asset.photo.representations[1].relative_path == path
    assert asset.photo.representations[1].offset == len(prefix.data)
    assert asset.file_prefixes == (prefix.dependency,)


@pytest.mark.parametrize("fault", ["overlap", "overrun", "prefix", "limit", "conflict"])
def test_invalid_shared_file_evidence_is_rejected(fault: str) -> None:
    source = library()
    first, second = _shared_assets()
    target = WriteTarget(photo_formats=FORMATS, photos_root_value=6)
    rep = second.photo.representations[1]
    if fault in {"overlap", "overrun"}:
        rep = replace(rep, offset=0 if fault == "overlap" else 0xFFFFFFFF)
        second = replace(
            second,
            photo=replace(
                second.photo,
                representations=(
                    second.photo.representations[0],
                    rep,
                    *second.photo.representations[2:],
                ),
            ),
        )
    elif fault == "prefix":
        second = replace(
            second,
            file_prefixes=(
                FileDependency(rep.relative_path, rep.size_bytes, "0" * 64),
            ),
        )
    elif fault == "limit":
        target = replace(target, max_photo_file_bytes=127)
    else:
        shard = second.files[1]
        second = replace(
            second,
            files=(
                second.files[0],
                replace(shard, dependency=replace(shard.dependency, sha256="0" * 64)),
                *second.files[2:],
            ),
        )
    photos = photo_library_with_asset(photo_library_with_asset(None, first), second)
    result = source.prepare(
        source.analyze(
            source.begin_draft(replace(source.snapshot, photos=photos)), target
        ),
        WriteResources(photos=(first, second)),
    )
    assert result.prepared is None
    assert any(issue.code == "resources.invalid_photo" for issue in result.issues)
