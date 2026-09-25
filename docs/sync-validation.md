# Sync validation record

> Historical checkpoint: the implementation recorded below predates the current
> source. Its counts and coverage do not validate the post-Review execution added
> in [ADR-0076](adr/0076-execute-reviewed-sync-through-storage.md). Current execution
> tests cover virtual Storage transactions, actual local media tools, partial
> success, cancellation, recovery, and settings; physical-device validation remains
> outstanding.

Recorded on 2026-09-18. Sync is enabled when the Active iPod permits writes and the
Library Workspace is unlocked. Automated UI coverage checks operation reservations
and workspace locking; dirty-workspace Save/Discard/Cancel handling is retained.
All device publication in this implementation session used virtual Storage volumes.
No physical iPod was written, played, disconnected, or tested.

## Automated evidence

| Area | Exercised evidence |
| --- | --- |
| Device Profile | MA002, iPod 5th Gen 30 GB, for application audio/Photo Sync and recovery fixtures |
| Audio | Compatible MP3 copy; WAV and surround FLAC to ALAC; AAC/MP3 lossy conversion; spoken-word mono 64 kb/s |
| Video | Authored MPEG-4/H.264 input to bounded Baseline output; silent video; chapter and subtitle retention |
| Subtitle capability | Retention test explicitly overrides MA002's subtitle capability; it is not evidence that MA002 displays subtitles |
| Photos | Native creation/replacement, folder/master albums, original-retention changes, packed-resource retention, preserved unknown header bytes |
| History | Ratings/count baselines, external ID3 owner changes, supported tag transformations, Play Counts and PlayCounts.plist |
| Matching | Chromaprint 1.6.1 raw algorithm 2; authored re-encoding/offset/silence/shared-introduction/short-evidence fixtures |
| Recovery | Source changes, cancellation, disconnect/reconnect, damaged-library recovery, device/Host boundary failures, final-index retry |
| Metadata writes | Intent, publication, flush, cleanup and receipt interruption, both creation and replacement |
| Host staging | Interrupted original/output copies, unreported completed preparation, abandoned and completed receipts |
| UI | Shared browser selection, full collection toggles under filtering, Photo labels, review deferral/back navigation, worker-driven publication |
| Scan cache | No media capture on warm reload; changed/removed/unconfigured source retirement; hard byte cap; evicted-analysis rebuild; cancellation, redirects and changed-file preconditions |

The authored Chromaprint generator reproduced the committed fixture document
exactly, including source hashes and fingerprint sequences. A separate live
130-second test exercises full-duration analysis. The full regression checkpoint
passed 2,054 tests with one Darwin-only skip in 183.16 seconds, including Sync
readiness, low-rate/high-bitrate audio, variable-rate video and bounded scan-cache
cleanup. Locked dependency validation, Ruff formatting/lint, Rumdl, Mypy and
Pyright also passed; both type checkers covered 634 files. These counts record a
checkpoint, not a permanent assertion about future repository state.

## Local encoders

The installed Windows FFmpeg identifies itself as `N-126388-g3bec07993`.
The following rate-control cases produced independently inspected output:

| Encoder | Rate controls exercised |
| --- | --- |
| libfdk_aac | CBR, VBR |
| aac_at | CBR, VBR, ABR, CVBR |
| aac | CBR |
| libmp3lame | CBR, VBR, ABR |
| libshine | CBR |

All five encoders also produced the separate mono spoken-word output. Sample-rate
cases exercise forced 48-to-44.1 kHz, 96-to-48 kHz, 88.2-to-44.1 kHz and a
22.05 kHz source prepared as 44.1 kHz for Shine.

This installed Shine backend advertises 32 kHz but fails an authored 32 kHz,
192 kb/s mono encode with `free format output not supported`. The same local
test at 44.1 kHz succeeds. Planning now explicitly rejects the failing combination
before preparation; forcing 44.1 kHz produces verified output. No claim is made
that all advertised backend/rate/bitrate combinations work. The FFmpeg
[Shine wrapper](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/libshine.c)
separately exposes sample-rate declarations and validates emitted packet headers.

Additional real encoder fixtures cover LAME 16 kHz/128 kb/s mono and the rejection
of 16 kHz/320 kb/s, native AAC 16 kHz/96 kb/s mono and the rejection of 8 kHz/96 kb/s.
Forced 44.1 kHz alternatives are verified at LAME 320 kb/s and AAC 192 kb/s.
An authored video averages below 30 fps but has 60 fps bursts; it is converted to
constant 30 fps and independently checked for timing and dimensions.

Scan analysis defaults to a 2048 MiB global limit, configurable from 64 to 65536 MiB
in Sync preferences. Publication removes analysis for changed/deleted files and
unconfigured roots, then evicts oldest persisted analysis before root manifests.
Recovery state and conversion-cache artifacts remain in separate repositories.

## Validation still open

- Continue broadening representative media and codec/settings boundary fixtures.
- Run the encoder and filesystem recovery cases on macOS and Linux.
- Exercise the complete folder/Playlist/audio/video/Photo flow on each enabled
  physical Device Profile and firmware, including repeated Sync and Back Sync.
- Record exact model, firmware, filesystem, encoder build, input/output media,
  playback/Photo/Playlist results and interruption recovery for every hardware run.
- Finish keyboard, accessibility, mixed-media and representative-library UI QA.

Hardware coverage currently contains **zero Device Profiles**. Virtual model
selection and a successful database reparse do not establish firmware playback.
