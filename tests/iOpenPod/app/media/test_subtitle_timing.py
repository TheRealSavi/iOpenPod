"""Plain subtitle timing preserves overlapping dialogue and UTF-8 content."""

from iOpenPod.app.media.subtitles.timing import (
    SubtitleCue,
    normalize_cues,
    to_webvtt,
)


def test_overlapping_sign_keeps_dialogue_and_resumes_it_afterward() -> None:
    result = normalize_cues(
        (
            SubtitleCue(1_000, 5_000, "A longer line of dialogue."),
            SubtitleCue(2_000, 3_000, "Station sign"),
        )
    )
    assert result.cues == (
        SubtitleCue(1_000, 2_000, "A longer line of dialogue."),
        SubtitleCue(2_000, 3_000, "A longer line of dialogue.\nStation sign"),
        SubtitleCue(3_000, 5_000, "A longer line of dialogue."),
    )
    assert not result.warnings


def test_same_start_uses_input_order_and_merges_simultaneous_duplicate_text() -> None:
    result = normalize_cues(
        (
            SubtitleCue(0, 3_000, "Second speaker"),
            SubtitleCue(0, 2_000, "First speaker"),
            SubtitleCue(0, 2_000, "First speaker"),
        )
    )
    assert result.cues == (
        SubtitleCue(0, 2_000, "Second speaker\nFirst speaker"),
        SubtitleCue(2_000, 3_000, "Second speaker"),
    )


def test_unsorted_cues_keep_input_order_during_overlap() -> None:
    result = normalize_cues(
        (
            SubtitleCue(2_000, 4_000, "First input"),
            SubtitleCue(0, 3_000, "Second input"),
        )
    )
    assert result.cues == (
        SubtitleCue(0, 2_000, "Second input"),
        SubtitleCue(2_000, 3_000, "First input\nSecond input"),
        SubtitleCue(3_000, 4_000, "First input"),
    )


def test_identical_consecutive_text_merges_without_closing_gaps() -> None:
    result = normalize_cues(
        (
            SubtitleCue(0, 1_000, "Hello"),
            SubtitleCue(1_000, 2_000, "Hello"),
            SubtitleCue(2_500, 3_000, "Hello"),
        )
    )
    assert result.cues == (
        SubtitleCue(0, 2_000, "Hello"),
        SubtitleCue(2_500, 3_000, "Hello"),
    )


def test_blank_and_invalid_intervals_do_not_hide_useful_dialogue() -> None:
    result = normalize_cues(
        (
            SubtitleCue(0, 1_000, "\n  \t"),
            SubtitleCue(0, 0, "No duration"),
            SubtitleCue(2_000, 1_000, "Backwards"),
            SubtitleCue(-500, 1_000, "Visible at the beginning"),
            SubtitleCue(-1_000, -500, "Already over"),
        )
    )
    assert result.cues == (SubtitleCue(0, 1_000, "Visible at the beginning"),)
    assert any("positive duration" in warning for warning in result.warnings)
    assert any("clipped" in warning for warning in result.warnings)


def test_long_unicode_cues_split_without_losing_text_or_splitting_characters() -> None:
    text = "A" + "字幕🙂" * 20_000
    result = normalize_cues((SubtitleCue(1_000, 10_000, text),))
    assert len(result.cues) > 1
    assert "".join(cue.text for cue in result.cues) == text
    assert all(len(cue.text.encode("utf-8")) <= 60_000 for cue in result.cues)
    assert all(cue.start_ms < cue.end_ms for cue in result.cues)
    assert result.cues[0].start_ms == 1_000
    assert result.cues[-1].end_ms == 10_000
    assert all(
        left.end_ms == right.start_ms
        for left, right in zip(result.cues, result.cues[1:], strict=False)
    )
    assert any("split" in warning for warning in result.warnings)


def test_overlapping_text_is_split_after_combining_to_respect_sample_limit() -> None:
    first = "a" * 40_000
    second = "b" * 40_000
    result = normalize_cues(
        (SubtitleCue(0, 2_000, first), SubtitleCue(0, 2_000, second))
    )
    assert len(result.cues) == 2
    assert "".join(cue.text for cue in result.cues) == first + "\n" + second
    assert all(len(cue.text.encode("utf-8")) <= 60_000 for cue in result.cues)


def test_impossibly_short_long_cue_extends_without_overlap_or_lost_text() -> None:
    text = "x" * 120_001
    result = normalize_cues(
        (
            SubtitleCue(0, 1, text),
            SubtitleCue(1, 2, "Following dialogue"),
            SubtitleCue(10, 100, "Later dialogue"),
        )
    )
    assert "".join(cue.text for cue in result.cues[:3]) == text
    assert result.cues[3] == SubtitleCue(3, 4, "Following dialogue")
    assert result.cues[4] == SubtitleCue(10, 100, "Later dialogue")
    assert all(cue.end_ms > cue.start_ms for cue in result.cues)
    assert all(
        left.end_ms <= right.start_ms
        for left, right in zip(result.cues, result.cues[1:], strict=False)
    )
    assert any("extended" in warning for warning in result.warnings)


def test_webvtt_serialization_preserves_unicode_and_literal_markup_characters() -> None:
    source = SubtitleCue(3_661_007, 3_662_019, "字幕 <b>literal</b> & < >\n&copy;")
    assert to_webvtt((source,)).decode("utf-8") == (
        "WEBVTT\n\n1\n01:01:01.007 --> 01:01:02.019\n"
        "{\\r}字幕 <b>literal</b> & < >\n{\\r}&copy;\n\n"
    )


def test_webvtt_blank_lines_do_not_terminate_the_remaining_dialogue() -> None:
    cues = (
        SubtitleCue(0, 1_000, "First\r\n\r\nSecond\n \nThird"),
        SubtitleCue(1_000, 2_000, "\n\t"),
        SubtitleCue(2_000, 3_000, "Last"),
    )
    assert to_webvtt(cues) == (
        b"WEBVTT\n\n"
        b"1\n00:00:00.000 --> 00:00:01.000\n{\\r}First\n{\\r}Second\n{\\r}Third\n\n"
        b"2\n00:00:02.000 --> 00:00:03.000\n{\\r}Last\n\n"
    )


def test_split_sample_boundaries_use_same_whitespace_as_decoded_text() -> None:
    text = "a" * 59_999 + " " + " " + "Second part"
    result = normalize_cues((SubtitleCue(0, 2_000, text),))
    assert result.cues == (
        SubtitleCue(0, 1_000, "a" * 59_999),
        SubtitleCue(1_000, 2_000, "Second part"),
    )
    assert any("split" in warning for warning in result.warnings)


def test_whitespace_only_split_samples_are_not_emitted() -> None:
    text = " " * 60_000 + "Dialogue" + " " * 60_000
    result = normalize_cues((SubtitleCue(0, 2_000, text),))
    assert result.cues == (SubtitleCue(0, 2_000, "Dialogue"),)


def test_webvtt_staging_retains_long_lines_without_inserted_breaks() -> None:
    text = "字幕{\\literal}" * 3_000
    result = normalize_cues((SubtitleCue(0, 2_000, text),))
    assert result.cues == (SubtitleCue(0, 2_000, text),)
    payload = to_webvtt(result.cues)
    assert payload.startswith(b"WEBVTT\n\n")
    assert len(payload.splitlines()[4]) > 4_095
    assert len(payload.splitlines()) == 6


def test_empty_input_stays_empty_without_warnings() -> None:
    result = normalize_cues(())
    assert not result.cues
    assert not result.warnings
    assert to_webvtt(result.cues) == b"WEBVTT\n\n"
