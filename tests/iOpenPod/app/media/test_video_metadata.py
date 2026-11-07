"""Final MP4 IDs, ordering, language, and caption presence remain distinct."""

import json

import pytest

from iOpenPod.app.media.video_metadata import parse_video_metadata
from iPodDB.library import SubtitleSelection, VideoPlaybackMetadata


@pytest.mark.parametrize("default_second", [False, True])
def test_selects_native_id_and_actual_language_of_default_text_track(
    default_second: bool,
) -> None:
    observed = parse_video_metadata(
        json.dumps(
            {
                "streams": [
                    {"index": 0, "id": "0x11", "codec_type": "video"},
                    {"index": 1, "id": "0x20", "codec_type": "audio"},
                    {
                        "index": 2,
                        "id": "0x40",
                        "codec_type": "subtitle",
                        "codec_name": "eia_608",
                        "codec_tag_string": "c608",
                    },
                    {
                        "index": 3,
                        "id": "0x51",
                        "codec_type": "subtitle",
                        "codec_name": "mov_text",
                        "codec_tag_string": "tx3g",
                        "tags": {"language": "eng"},
                    },
                    {
                        "index": 4,
                        "id": "0x77",
                        "codec_type": "subtitle",
                        "codec_name": "mov_text",
                        "codec_tag_string": "tx3g",
                        "tags": {"language": "fra"},
                        "disposition": {"default": int(default_second)},
                    },
                ]
            }
        ).encode()
    )
    assert observed == VideoPlaybackMetadata(
        SubtitleSelection(119, 4, 6721)
        if default_second
        else SubtitleSelection(81, 3, 5575),
        has_closed_captions=True,
    )


@pytest.mark.parametrize("language", ["", "en", "not-a-language", "und"])
def test_missing_language_is_undefined_instead_of_english(language: str) -> None:
    observed = parse_video_metadata(
        json.dumps(
            {
                "streams": [
                    {"index": 0, "codec_type": "video"},
                    {
                        "index": 1,
                        "id": "0x9",
                        "codec_name": "mov_text",
                        "codec_tag_string": "tx3g",
                        "tags": {"language": language},
                    },
                ]
            }
        ).encode()
    )
    assert observed.subtitle == SubtitleSelection(9, 1, 21956)


@pytest.mark.parametrize(
    "raw",
    [
        b"not JSON",
        b"{}",
        b'{"streams":[]}',
        b'{"streams":[{"codec_type":"audio"}]}',
        b'{"streams":[{"codec_type":"video","disposition":{"attached_pic":1}}]}',
        b'{"streams":[{"codec_type":"video"},{"codec_name":"mov_text","codec_tag_string":"tx3g","index":1}]}',
    ],
)
def test_incomplete_observations_cannot_mark_characteristics_valid(raw: bytes) -> None:
    with pytest.raises(ValueError, match="Cannot inspect"):
        parse_video_metadata(raw)
