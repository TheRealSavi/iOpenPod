"""Per-format subtitle recovery retains words without exposing control syntax."""

import pytest

from iOpenPod.app.media.subtitles import convert_packet, supports
from iOpenPod.app.media.subtitles.text import encode_literal


@pytest.mark.parametrize(
    ("codec", "payload", "expected"),
    [
        ("subrip", b"<i>Hello</i><br>World &amp; friends", "Hello\nWorld & friends"),
        ("srt", b"Unfinished <b>sentence", "Unfinished sentence"),
        ("subrip", b"Call <John> when 2 < 3.", "Call <John> when 2 < 3."),
        ("subrip", rb"{\an8}Still readable", "Still readable"),
        ("webvtt", b"<v Ann><c.green>Hello</c> <00:01.200>world</v>", "Hello world"),
        ("webvtt", b"Line one\nLine two", "Line one\nLine two"),
        (
            "ass",
            rb"0,0,Default,,0,0,0,,{\k10}Sing {\k20}along\NSecond line",
            "Sing along\nSecond line",
        ),
        (
            "ssa",
            rb"Dialogue: Marked=0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello, world",
            "Hello, world",
        ),
        (
            "ass",
            rb"0,0,Default,,0,0,0,,{\p1}m 0 0 l 10 10{\p0}A visible sign",
            "A visible sign",
        ),
        ("ass", rb"Before{\p2}m 0 0 l 10 10{\p0} after\hthis", "Before after this"),
        ("ass", rb"{\pos(40,60)\move(1,2,3,4)\t(\fs80)}Moving words", "Moving words"),
        (
            "sami",
            b"<SYNC Start=1000><P Class=ENCC>Hello<br>World &amp; friends",
            "Hello\nWorld & friends",
        ),
        (
            "sami",
            b"<SAMI><HEAD><STYLE>p {color: red}</STYLE></HEAD><BODY><P>Words</BODY></SAMI>",
            "Words",
        ),
        ("subviewer", b"First[br]Second[BR]Third", "First\nSecond\nThird"),
        ("subviewer1", b"First\nSecond", "First\nSecond"),
        ("subviewer1", b"First|Second\x00", "First\nSecond"),
        ("microdvd", b"{y:i}{c:$00ffff}First|{F:Arial}{s:20}Second", "First\nSecond"),
        (
            "microdvd",
            b"{unknown}Keep literal braces|second",
            "{unknown}Keep literal braces\nsecond",
        ),
        ("mpl2", b"/First|Second / third", "First\nSecond / third"),
        (
            "text",
            b"Plain <words>\r\nKeep &amp; as written",
            "Plain <words>\nKeep &amp; as written",
        ),
    ],
)
def test_recoverable_packet_text(codec: str, payload: bytes, expected: str) -> None:
    assert supports(codec)
    assert convert_packet(codec, payload).text == expected


@pytest.mark.parametrize("codec", ["subrip", "webvtt", "text", "ass", "sami"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_unicode_encodings_retain_actual_words(codec: str, encoding: str) -> None:
    text = "Café 日本語"
    converted = convert_packet(codec, text.encode(encoding))
    assert converted.text == text
    assert not any("encoding" in warning for warning in converted.warnings)


def test_legacy_encoding_is_recovered_with_visible_warning() -> None:
    converted = convert_packet("subrip", "Café — déjà vu".encode("cp1252"))
    assert converted.text == "Café — déjà vu"
    assert any("Windows-1252" in warning for warning in converted.warnings)


def test_unknown_legacy_byte_does_not_discard_remaining_dialogue() -> None:
    converted = convert_packet("text", b"Keep \x81 rest")
    assert converted.text == "Keep \ufffd rest"
    assert converted.warnings


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_mov_text_uses_counted_text_and_never_binary_style_atoms(encoding: str) -> None:
    text = "Café 日本語"
    body = text.encode(encoding)
    payload = len(body).to_bytes(2, "big") + body + b"\x00\x00\x00\x08styl"
    assert convert_packet("mov_text", payload).text == text
    assert convert_packet("tx3g", payload).text == text


def test_truncated_mov_text_recovers_available_words() -> None:
    converted = convert_packet("mov_text", b"\x00\x20Remaining words")
    assert converted.text == "Remaining words"
    assert any("truncated" in warning for warning in converted.warnings)


def test_mov_text_reports_styles_that_cannot_survive_plain_text_conversion() -> None:
    style = bytes.fromhex("000000167374796c00010000000500010110ffffffff")
    converted = convert_packet("mov_text", b"\x00\x05Words" + style)
    assert converted.text == "Words"
    assert any("styling" in warning for warning in converted.warnings)


@pytest.mark.parametrize(
    "suffix",
    [b"", b"\x00\x00\x00\x0astyl\x00\x00", b"\x00\x00\x00\x08free"],
)
def test_mov_text_without_display_modifiers_has_no_style_warning(suffix: bytes) -> None:
    assert not convert_packet("mov_text", b"\x00\x05Words" + suffix).warnings


def test_literal_staging_preserves_entities_and_neutralizes_ass_syntax() -> None:
    assert encode_literal("<b> & café\n" + r"{\an8}\N") == (
        r"{\r}<b> & café" + "\n" + r"{\r}{{\r}\{\r}an8}\{\r}N"
    )


def test_literal_staging_guards_timestamp_like_words_from_the_demuxer() -> None:
    assert encode_literal("1\n00:00:01,000 --> 00:00:02,000") == (
        r"{\r}1" + "\n" + r"{\r}00:00:01,000 --> 00:00:02,000"
    )


@pytest.mark.parametrize(
    ("codec", "payload"),
    [
        ("mov_text", b"\x00\x00"),
        ("mov_text", b"\x00"),
        ("ass", rb"{\p1}m 0 0 l 10 0 10 10"),
        ("ass", b"Comment: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Not visible"),
        ("sami", b"<P>&nbsp;"),
        ("text", b"\x00\x01\x02"),
    ],
)
def test_no_words_means_no_invented_dialogue(codec: str, payload: bytes) -> None:
    assert convert_packet(codec, payload).text == ""


def test_plain_text_cleanup_cannot_split_a_single_srt_cue() -> None:
    converted = convert_packet(
        "text", b"first\n\n2\n00:01:00,000 --> 00:02:00,000\nlast"
    )
    assert "\n\n" not in converted.text
    assert converted.text.endswith("last")


def test_bitmap_is_not_misrepresented_as_text() -> None:
    assert not supports("hdmv_pgs_subtitle")
    with pytest.raises(ValueError, match="Unsupported"):
        convert_packet("hdmv_pgs_subtitle", b"not a text subtitle")
