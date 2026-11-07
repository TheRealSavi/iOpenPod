# ADR-0205: Adopt native video playback contracts

- Status: Accepted
- Date: 2026-10-28
- Amends: ADR-0097, ADR-0157, ADR-0158, ADR-0160 and ADR-0196

Video Media Stream Selection can retain primary audio and one optional alternate
audio stream. Audio-only selection still requires exactly one stream. Keep the
primary first and default, the alternate nondefault, and each stream's language
and descriptive tags. Validate and prepare both against the Device Profile,
including independent copy/encode decisions. Verify both output streams. Sound
Check measures the primary; the Library still has one Track gain value.

Existing choices remain version 1 when no alternate is present. Choices with an
alternate use version 2 and the same stale-source, reviewed replacement,
publication, and applied-choice receipt rules. Restoring the saved choice must
retain both streams, and a successful unchanged repeat Sync must not replace them
again. The storage projection includes both audio bitrate ceilings.

The native Alternate Audio Boolean is distinct from these Host stream choices.
The verified Classic 120GB RetailOS 2.0.1 Preferences profile exposes raw file
byte `0xB85`: zero is Off and one is On. Preserve every retained unknown value;
explicit codec changes accept only zero or one. Existing identity, version,
extent and clock-edit protections remain. The iPod Preferences tab displays the
value read-only; this does not add a firmware-settings publication workflow.

Native subtitle compatibility now includes geometry and clocks. A codec-compatible
source with incompatible native headers is repaired in private staging, with a
remux only when necessary. Empty or
invalid native subtitle rectangles receive the established bottom subtitle layout;
valid retained geometry is preserved. The prepared subtitle `tkhd` must use
version 0, because the traced firmware reader misinterprets version 1. This is
not a rejection of version-1 `mvhd`, `mdhd`, or `elst` in general.

Subtitle and caption media clocks must preserve the native centisecond conversion
and signed sample-time range. When needed, rescale to 1,000 units per second only
when every relevant timestamp is exactly representable. Update `mdhd`, `stts`,
edit media times and composition offsets together; leave movie-clock edit
durations, samples, atom sizes, chunk offsets, and header versions intact. Preserve
safe clocks byte-for-byte. Inexact conversion, unknown timing structures and
unverifiable output block preparation instead of silently rounding or discarding
cues. Validate bounded headers again after metadata editing.

Keep selected text subtitles and `c608` captions together. The chooser explains
that the Classic enables only one display mode at a time. Inspect demuxed caption
triplets before and after preparation, preserving parity, repeated controls and
payload order. Unsupported alarm, flashing and text-mode controls produce
warnings without rewriting commands. Reject a remux containing field-2 captions,
because the tested MOV writer drops them; an unchanged copy retains them with a
playback-uncertainty warning. Do not equate FFprobe's triplets with complete
validation of every original `cdat`/`cdt2` atom.

The evidence and unresolved boundaries are recorded in
[the video firmware findings](../research/video-playback-firmware.md). The audio
selector's language match and enabled fallback are established, but its connection
to the global Alternate Audio Boolean is not. Retaining two tracks does not prove
that every model selects the second one when the toggle is On. Forced subtitle
semantics, arbitrary style fidelity, CEA-708 support, and device playback of these
new outputs remain unclaimed.

Validation uses authored binary fixtures, real FFmpeg preparation, GUI tests, and
virtual-device Sync. Tests cover independent audio conversion, exact copied
packets, languages/default flags, saved choices and unchanged repeat Sync, caption
preservation/loss rejection, bounded header validation and exact-only clock
repair. Normalize unsafe source clocks before a remux: the tested muxer can lose
long subtitle sample deltas at a high timescale before final verification runs.
Hour-long timing fixtures use short audiovisual samples to test this without
decoding an hour of media. No physical-device write is part of routine validation.
No dependency is added.
