"""Pure Photo shard allocation preserves frames, prefix evidence, and capacity."""

from dataclasses import replace

import pytest
from tests.iOpenPod.app.media.test_photo_sync import (
    _asset,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.media.photo_shards import pack_photo_shards, photo_shard_identity
from iPodDB.library import FileDependency, SourceFile, content_sha256, read_content


def test_formats_roll_over_independently_at_exact_capacity() -> None:
    assets = tuple(_asset(photo_id=100 + i, shard=i) for i in range(1, 6))
    packed = pack_photo_shards(assets, max_file_bytes=256)
    assert [item.photo.representations[1].offset for item in packed] == [
        0,
        64,
        128,
        192,
        0,
    ]
    assert [item.photo.representations[2].offset for item in packed] == [
        0,
        128,
        0,
        128,
        0,
    ]
    assert packed[-1].photo.representations[1].relative_path.endswith("F1024_2.ithmb")
    assert packed[-1].photo.representations[2].relative_path.endswith("F1025_3.ithmb")
    assert packed[0].files[1] is packed[3].files[1]
    for original, result in zip(assets, packed, strict=True):
        assert result.files[0] is original.files[0]
        assert not result.file_prefixes
        for representation, file, frame in zip(
            result.photo.representations[1:],
            result.files[1:],
            original.files[1:],
            strict=True,
        ):
            assert len(file.data) <= 256
            assert (
                read_content(
                    file.data, representation.offset, representation.size_bytes
                )
                == frame.data
            )


def test_retained_prefix_appends_at_exact_end_without_invented_alignment() -> None:
    asset = _asset()
    data = b"opaque retained prefix and trailing data"
    dependency = FileDependency(
        "Photos/Thumbs/F1024_7.ithmb", len(data), content_sha256(data)
    )
    prefix = SourceFile(dependency, data)
    result = pack_photo_shards((asset,), prefixes=(prefix,), max_file_bytes=256)[0]
    thumbnail = result.photo.representations[1]
    assert thumbnail.relative_path == dependency.relative_path
    assert thumbnail.offset == len(data)
    assert result.file_prefixes == (dependency,)
    assert result.files[1].data == data + read_content(
        asset.files[1].data, 0, len(asset.files[1].data)
    )


def test_reserved_missing_and_case_variant_names_are_never_reused() -> None:
    result = pack_photo_shards(
        (_asset(),),
        reserved_paths=(
            "photos/thumbs/f1024_1.ITHMB",
            "Photos/Thumbs/F1024_2.ithmb",
        ),
        max_file_bytes=256,
    )[0]
    assert result.photo.representations[1].relative_path.endswith("F1024_3.ithmb")
    assert result.photo.representations[2].relative_path.endswith("F1025_1.ithmb")


@pytest.mark.parametrize("corruption", ["size", "digest"])
def test_changed_source_frame_is_rejected_before_repacking(corruption: str) -> None:
    asset = _asset()
    file = asset.files[1]
    changed = replace(
        file,
        dependency=replace(
            file.dependency,
            size=file.dependency.size + int(corruption == "size"),
            sha256="0" * 64 if corruption == "digest" else file.dependency.sha256,
        ),
    )
    with pytest.raises(ValueError, match="captured fingerprint"):
        pack_photo_shards(
            (replace(asset, files=(asset.files[0], changed, asset.files[2])),),
            max_file_bytes=256,
        )


def test_frame_larger_than_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="shard capacity"):
        pack_photo_shards((_asset(),), max_file_bytes=127)


@pytest.mark.parametrize("part", ["9" * 5000, str(0x100000000)])
def test_oversized_stored_identity_is_unusable_metadata(part: str) -> None:
    assert photo_shard_identity(f"Photos/Thumbs/F1024_{part}.ithmb") is None
    assert photo_shard_identity(f"Photos/Thumbs/F{part}_1.ithmb") is None
