"""Normalize text subtitle timing for one non-overlapping iPod text stream."""

from dataclasses import dataclass

from iOpenPod.app.media.subtitles.text import clean_text, encode_literal

_MAX_SAMPLE_BYTES = 60_000


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """A plain-text subtitle displayed over a half-open millisecond interval."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleTimingResult:
    """Displayable cues and any necessary timing simplifications."""

    cues: tuple[SubtitleCue, ...]
    warnings: tuple[str, ...]


def normalize_cues(cues: tuple[SubtitleCue, ...]) -> SubtitleTimingResult:
    """Preserve overlapping dialogue in sequential, size-bounded text samples.

    Every timing boundary starts a new sample containing all active distinct cue
    texts, in their original input order. A long dialogue therefore resumes after
    a shorter overlapping sign ends. Oversized samples are shown in successive
    pieces instead of overflowing the timed-text format's 16-bit byte length.
    """
    events: dict[int, list[tuple[int, str | None]]] = {}
    discarded_timing = False
    clipped_start = False
    for order, cue in enumerate(cues):
        text = cue.text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            continue
        start = max(0, cue.start_ms)
        if cue.end_ms <= start:
            discarded_timing = True
            continue
        clipped_start |= start != cue.start_ms
        events.setdefault(start, []).append((order, text))
        events.setdefault(cue.end_ms, []).append((order, None))

    times = sorted(events)
    active: dict[int, str] = {}
    segments: list[SubtitleCue] = []
    for position, start in enumerate(times[:-1]):
        for order, event_text in events[start]:
            if event_text is None:
                active.pop(order, None)
            else:
                active[order] = event_text
        if not active:
            continue
        text = "\n".join(dict.fromkeys(active[order] for order in sorted(active)))
        end = times[position + 1]
        if segments and segments[-1].end_ms == start and segments[-1].text == text:
            previous = segments[-1]
            segments[-1] = SubtitleCue(previous.start_ms, end, text)
        else:
            segments.append(SubtitleCue(start, end, text))

    output: list[SubtitleCue] = []
    split_text = False
    extended_timing = False
    previous_end = 0
    for cue in segments:
        pieces = _text_pieces(cue.text)
        split_text |= len(pieces) > 1
        start = max(cue.start_ms, previous_end)
        end = max(cue.end_ms, start + len(pieces))
        extended_timing |= start != cue.start_ms or end != cue.end_ms
        duration = end - start
        for position, piece in enumerate(pieces):
            output.append(
                SubtitleCue(
                    start + duration * position // len(pieces),
                    start + duration * (position + 1) // len(pieces),
                    piece,
                )
            )
        previous_end = end

    warnings: list[str] = []
    if discarded_timing:
        warnings.append("Subtitle cues without a positive duration were skipped.")
    if clipped_start:
        warnings.append("Subtitle cues starting before the video were clipped.")
    if split_text:
        warnings.append(
            "Very long subtitle text was split into successive cues to fit iPod text limits."
        )
    if extended_timing:
        warnings.append(
            "Subtitle timing was extended slightly to retain all text in positive-duration cues."
        )
    return SubtitleTimingResult(tuple(output), tuple(warnings))


def _text_pieces(text: str) -> tuple[str, ...]:
    """Split UTF-8 safely and apply the output decoder's whitespace normalization."""
    encoded = text.encode("utf-8")
    pieces: list[str] = []
    offset = 0
    while offset < len(encoded):
        end = min(offset + _MAX_SAMPLE_BYTES, len(encoded))
        if end < len(encoded):
            while encoded[end] & 0xC0 == 0x80:
                end -= 1
        piece = clean_text(encoded[offset:end].decode("utf-8"))
        if piece:
            pieces.append(piece)
        offset = end
    return tuple(pieces)


def to_webvtt(cues: tuple[SubtitleCue, ...]) -> bytes:
    """Serialize UTF-8 cues for the plain-text decoder, protecting ASS escapes.

    This staging input must use ``-f webvtt -c:s text -keep_ass_markup 1``.
    WebVTT avoids the SRT demuxer's line-length limit. Empty lines terminate
    records and are omitted.
    """
    records: list[str] = []
    for cue in cues:
        text = "\n".join(
            line
            for line in cue.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        )
        if not text:
            continue
        records.append(
            f"{len(records) + 1}\n"
            f"{_timestamp(cue.start_ms)} --> {_timestamp(cue.end_ms)}\n"
            f"{encode_literal(text)}\n\n"
        )
    return ("WEBVTT\n\n" + "".join(records)).encode("utf-8")


def _timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1_000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
