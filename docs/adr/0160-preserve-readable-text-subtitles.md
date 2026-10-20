# ADR-0160: Preserve readable text subtitles

- Status: Accepted
- Date: 2026-10-20
- Amends: ADR-0083 and ADR-0157

Automatic preparation and explicit Media Stream Selection retain supported text
subtitles on iPods that support `tx3g`. Convert MOV text, SubRip, WebVTT, ASS/SSA,
SAMI, SubViewer 1/2, MicroDVD, MPL2, and plain timed text. Explicit exclusions still
exclude a stream. Compatible `tx3g` can be copied; changed video dimensions require
text preparation using the actual output video dimensions. Retain the existing
Device Profile gates and `c608` copy behavior.

Place pure packet converters in `app/media/subtitles/`, with one module for each
format family. FFprobe supplies packet timestamps; converters receive bytes and
return readable text plus warnings. Storage owns captured input, subprocesses,
private staging, and cleanup. Embedded MicroDVD uses container timestamps and
never substitutes the output video's frame rate.

Prefer readable words over exact styling. Remove styling, animation, and vector
commands while keeping any dialogue in the same packet. Combine simultaneous
cues into non-overlapping intervals so a shorter sign cannot truncate a longer
line of dialogue. Honor Unicode byte-order markers; recover non-UTF-8 legacy bytes
with a Windows-1252 fallback and a warning. Recover missing timing from neighboring
cues or a short bounded display interval, reporting estimates. A corrupt packet
does not discard other readable packets.

Stage normalized text with explicit literal-text decoding, then encode dimensioned
`mov_text` with the `tx3g` sample entry. Newly converted text uses a subtitle track
as wide as the video and 15% of its display height, translated to the bottom of the
video, with a matching nonzero default text box. A bounded, same-size MP4 header
transform runs through Storage's private workspace; it leaves media samples,
chunk offsets, copied native subtitles, and captions unchanged. Verify this
geometry after metadata editing as well as reading the encoded subtitle packets
back to verify text and timing before publication. A stream with no recoverable timed
text fails preparation with an actionable explanation rather than creating a
silently empty track. Styling loss, timing repairs, and unrepresentable forced
playback flags are reported. No text is fabricated for drawing-only cues.

This deliberately replaces direct subtitle transcoding: real FFmpeg experiments
showed overlapping ASS events losing dialogue, drawing commands becoming visible
text, and literal punctuation being reinterpreted as markup. Original iOpenPod's
`origin/1.x` transcoder provides the native `tx3g`/`c608` and nonzero text-rectangle
baseline; it explicitly deferred other formats until dedicated converters existed.

The Classic 6.5 investigation on 2026-10-20 found all 1,534 full-English cues intact
in a failing synced episode. Its generated subtitle track instead occupied the
whole 640×360 video, with an identity matrix and an empty default text box.
The Original project's `scripts/ipod_caption_probe.py` uses a known-good-style
640×54 track. The corrected layout follows Apple's
[track size and placement](https://developer.apple.com/documentation/quicktime-file-format/subtitle_track_header_size_and_placement)
and [default text box](https://developer.apple.com/documentation/quicktime-file-format/subtitle_sample_description/default_text_box)
requirements. Header validation is reproducible; physical playback remains a
separate acceptance check.

Prepared MP4 video explicitly uses a movie timescale of 1,000 for both the `ipod`
and `mov` muxers. FFmpeg builds with automatic movie-clock selection can produce
441,000,000 from fractional-frame-rate video, 44.1 kHz audio, and timed text.
On the Classic 6.5, reciprocal stream-copy experiments preserved every compressed
audio, video, and subtitle packet and its timing. Controlled replays confirmed that
the full episode and synthetic clip with a 441,000,000 movie clock did not display
subtitles, while both normal-clock copies did. The high clock also required 64-bit
movie-duration headers; the experiments do not isolate those two format details.
Explicitly using 1,000 fixes the demonstrated failure without changing language
tags or forcing ordinary subtitles to display. The episode's first cue starts at
2.64 seconds, followed by another at 22.16 seconds, so blank playback intervals
alone do not establish a decoding failure or loading delay. The regression
verifies the emitted movie header and retained dialogue; it does not emulate
firmware rendering.

Applied-choice digests include a preparation revision for saved selections that
convert other text codecs to `tx3g`: revision 1 corrected display geometry and
revision 2 also fixes the movie clock. Their old receipts request one reviewed
replacement; successful Sync records the new digest and subsequent scans stay In sync.
Choice-file serialization is unchanged. Automatic choices and copied native text
do not gain an unconditional replacement requirement.

External subtitle selection, bitmap OCR, and burning subtitles into video are
outside this change. No dependency is added. Physical font coverage and subtitle
rendering still require device-specific playback validation.
