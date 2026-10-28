# Video playback firmware findings adopted by iOpenPod

Target: Classic 120GB RetailOS 2.0.1. Normalized OSOS SHA-256:
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Main-image mapping: runtime address minus `0x08000000`, plus file offset `0xB65C`.
Names below are analyst proposals, not recovered Apple source symbols.

The companion firmware-lab reports contain instruction listings, byte-audit
scripts and bounded Host models. Their published entry point is the
[video research overview](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/video-research-overview).
This document records the product consequences without requiring the sibling
checkout or proprietary firmware at runtime or in tests.

## Subtitles

`MovieParser_ReadTrackHeaderIdentityAndGeometry` at `0x08137694` compares masked
version bits `0xFF000000` with literal one. It therefore uses version-0 offsets
even for a version-1 `tkhd`. A bounded model of retained synthetic ST15/ST16 files
read the failed file's subtitle width and track ID as zero, while reading the
working file correctly. That establishes a metadata-misread mechanism; independent
device testing is still needed to establish its causal role in the old failure.

`SubtitleCache_BuildSampleOffsetsAndCentisecondTimes` at `0x0819F7DC` first divides
media timescale by 100, then divides sample deltas and accumulated media time by
that truncated divisor. Accumulation is 32-bit and division has signed handling.
The movie timescale and subtitle media timescale are separate values. Merely
forcing the movie clock to 1,000 does not solve subtitle-media overflow.

`mdhd` and edit-list readers have explicit 64-bit paths. Do not treat every
version-1 atom as unsupported. The RTTI-linked subtitle renderer requests
Helvetica and applies nine-pixel inset padding, but copying serialized style
fields is not proof that each field affects visible output. The sample producer's
full forced-subtitle/style behavior remains unresolved.

Implementation checks native track geometry and clocks and performs only exact
timestamp rescaling in private preparation. A local FFmpeg experiment found that
`-enc_time_base:s 1:1000` still produced a `1/1000000` subtitle clock for both copy
and `mov_text` encoding, so that option is not a reliable repair by itself.
An authored one-hour subtitle timeline also demonstrated a muxer failure/loss at
the high clock. Exactly normalizing the private input to 1,000 before stream-copy
remuxing preserves the last cue at 3,600–3,602 seconds. This Host fixture isolates
the preparation behavior; it does not execute the iPod renderer.
See the [subtitle report](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/video-subtitles).

## Closed captions

`Caption608_ApplyMiscControl` at `0x08107990` implements pop-on, paint-on and
two/three/four-row roll-up behavior. `TCaptionView` stores decoder mode at `+0xA1`,
previous control-pair bytes at `+0xA3/+0xA4`, and displayed/hidden row collections
at `+0xA8/+0xAC`. The byte consumer masks with `0x7F`, while retaining repeated
control pairs until the decoder suppresses them. It does not prove upstream
parity validation.

Alarm suffixes `0x22/0x23` are unhandled here; flashing `0x28` and text-mode
`0x2A/0x2B` commands are handled without state mutation in this handler. Keep the
commands and diagnose uncertain presentation instead of deleting them.
`MediaSettings_SetCaptionsAndDisableSubtitles` at `0x08232F64` and reciprocal
subtitle setter `0x08232C20` implement mutual exclusion at enable time. That does
not prohibit storing both kinds of track in one file.

FFmpeg's MOV reader converts caption sample atoms into A53-style triples, so its
packet output cannot validate the whole original atom envelope. The tested MOV
writer retains field-1 `0xFC` triples and drops field-2 `0xFD` triples. Preparation
therefore verifies selected demuxed payloads and blocks that known lossy remux.
This is a Host-tool limitation, not proof that the iPod rejects field 2.
See the [caption report](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/video-closed-captions),
[Apple's caption sample data](https://developer.apple.com/documentation/quicktime-file-format/closed_captioning_sample_data),
[FFmpeg MOV reader](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/mov.c),
and [MOV writer](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/movenc.c).

## Alternate Audio

`Preferences_GetAlternateAudioEnabledRaw` at `0x0802F8EC` and setter `0x08045558`
access context byte `+0xB89`. The native writer copies its payload from context
`+4`, establishing file offset `0xB85` in the qualified `0x3D`/2,956-byte layout.
Zero is Off; one is On. Raw values are retained, while the UI toggle maps larger
values to zero and the observer normalizes with `value == 1`. Runtime copies at
settings-service `+0x8D` and media-settings `+0x64` are not file offsets.

The audio selector at the end of `0x0819D12C` chooses the first language match,
even when disabled, otherwise the first enabled track. With neither it returns
null. Audio node fields include track ID `+0xCC`, enabled byte `+0xD0`, alternate
group `+0xD2` and language `+0xD4`. This loop does not test alternate group. Requested
language at reader `+0x2B8` is signed 16-bit, so `-1` does not equal unsigned
language `0xFFFF`.

The global Boolean's connection to that requested language, and the timing of
live decoder switching, remain untraced. iOpenPod can preserve two selected audio
tracks, order/default metadata and language tags without inventing that policy.
It does not promise that On always means the second track or that two tracks with
the same language are independently selectable on the device.
See the [Alternate Audio report](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/video-alternate-audio).

## Validation boundary

Firmware byte audits, binary-fixture tests, real FFmpeg packet/timing checks and
virtual-device Sync are distinct evidence. None executes this firmware renderer.
The implementation policy is in
[ADR-0205](../adr/0205-adopt-native-video-playback-contracts.md).
Current changes do not author unknown SQLite alternate-audio flags or add a
physical Preferences writer, and unchanged existing device media is not silently
rewritten merely because this research is available.
