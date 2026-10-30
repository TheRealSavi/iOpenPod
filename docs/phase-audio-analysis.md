# Phase gameplay analysis

Saving the Phase Playlist now analyzes eligible music instead of generating
regular placeholder events. Eligibility remains the firmware/game rule: music
with whole-second duration 30 through 1800. Repeated Playlist occurrences share
one chart for the Track persistent ID. Other media stays in the Playlist without
an invented analysis record.

## Audio and bounded processing

The shared FFmpeg decoder accepts a verified incoming Host file or a validated
device-relative music path. Its explicit demuxer and protocol restrictions match
Genius. Phase requests complete mono float32 PCM at 22,050 Hz, capped at 1801
seconds. Decoded duration must agree with the database within three seconds;
extra encoder padding is clipped at the declared duration. Non-finite samples
and decode errors stop preparation with an error.

DSP uses librosa 0.11 with a 2048-sample centered STFT and 256-sample hop
(11.61 ms). Core blocks contain 2048 frames, with 64 context frames on either
side. HPSS uses a 31-bin median kernel and separation margins of 2. The spectral
power sent to a 64-band mel transform combines 75% percussive and 25% full
magnitude, retaining pitched attacks. Mel analysis begins at 20 Hz.

The implementation keeps full mono PCM and compact whole-song feature vectors;
large spectrograms, HPSS intermediates and tempograms are block-local. It avoids
allocating a whole-song tempogram. Two DSP threads process at most two spectral
blocks at once, sharing read-only PCM. Their feature results are assembled in
the original order on the coordinator thread. Beat tracking, decoding, device
reads, hashing and publication remain serial. This bounds extra working memory
to another block rather than another whole decoded song.

Only the coordinator invokes the caller's cancellation checkpoint. It checks
while waiting for workers, signals them to stop on cancellation or failure, and
joins them before returning. A running native median filter must finish before
that worker can stop. FFmpeg remains cancellable through Storage's runner.

The optional `max_workers=1` argument supports diagnosis and exact serial/parallel
comparison; normal saves use two workers. The algorithm version remains unchanged
because transforms, thresholds, overlap, frame order and chart events are
unchanged. Existing cached charts remain valid.

A warmed 120-second authored music fixture measured 7.19 seconds with the original
serial code and 4.41 seconds with two workers on the development Windows host
(about 39% less DSP time). The complete chart compared exactly equal, including
all integer timestamps and magnitudes. The profile attributed 5.9 of 6.4 seconds
in an earlier serial run to HPSS, primarily native median filtering. These are
DSP measurements, not a promised end-to-end USB save speedup; startup and decoding
still contribute to the first-track cost.

## Events and strengths

Three mel regions cover below 250 Hz, 250 to 2000 Hz, and above 2000 Hz. Positive
spectral-flux onset envelopes are balanced using each region's 95th percentile
of positive strengths. Their clipped mean drives librosa onset detection with
delta 0.1 and a minimum spacing of approximately 120 ms. Centering of the provided
spectrogram is accounted for without adding a second FFT-centering delay.

Frames quieter than 1% of peak spectral RMS, or below absolute threshold 0.00001,
cannot generate events. Beat tracking runs in local core blocks with 256 context
frames, allowing tempo estimates to change across the track. Overlap events are
kept only in their own core block; another 120 ms gate avoids seam duplicates.
There are no fabricated beats in silent sections.

| Event | iOpenPod mapping | Native representation |
| --- | --- | --- |
| Transient time | Detected attack frame | Absolute unsigned Q16.16 seconds after byte `0xff` |
| Three transient strengths | Low, mid and high onset strengths | Three five-bit values packed into a u16 |
| Beat time | Locally tracked pulse frame | Absolute unsigned Q16.16 seconds after byte `0xff` |
| Beat strength | Onset-envelope strength at the pulse | High four bits of a u8 |
| Beat accent | Harmonic spectral RMS at the pulse | Low four bits of a u8 |

Strengths use percentile scaling, clipping and exponent 0.65 before quantization
to 0–31 or 0–15. Timestamps stay before the declared end of the Track. The codec
requires strictly increasing timestamps, validates magnitude bounds and limits
each stream to 20,000 events. Silence produces two empty streams. The old
placeholder builder remains available only for research fixtures.

These assignments are a new musical interpretation of the known packed fields.
The original iTunes analysis algorithm and all downstream gameplay semantics are
not claimed to be recovered.

## Saving and reuse

Analysis happens during Library preparation, after final Track and Playlist IDs
exist and before any device writes. New audio imports are analyzed from their
prepared Host source. Existing audio is fingerprinted through Storage and those
fingerprints become transaction dependencies. Inputs are checked again after
analysis; changing inputs fail preparation or invalidate the reviewed save.

`iPod_Control/iOpenPod/phase-analysis-v1.json` stores a per-PID provenance string
containing algorithm version, source content SHA-256, declared duration and chart
SHA-256. The first analysis upgrades existing untracked charts, including old
placeholders. Matching entries reuse the existing encrypted chart bytes; changed
audio, changed duration, changed algorithm or changed chart data triggers fresh
analysis. The metadata file retains only the current indexed tracks and is
bounded to 8 MiB. Charts, provenance, the Phase Library index and database changes
are published together in the normal recoverable Storage Transaction.

## Verification

Authored pulse signals test attack alignment within 90 ms, multiple spectral
regions, silence, local tempo changes, magnitude limits and deterministic events.
A WAV fixture exercises real FFmpeg decoding and librosa analysis. Virtual Storage
tests cover cache reuse and source changes alongside ordinary publication tests.
Offline execution of the hash-checked Phase build-3168002 parser accepts both
musical and zero-event charts and agrees on counts, first timestamps and packed
strength decoding. Physical gameplay remains to be evaluated on an iPod.

API references: [onset detection](https://librosa.org/doc/0.11.0/generated/librosa.onset.onset_detect.html),
[beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html),
and [HPSS](https://librosa.org/doc/0.11.0/generated/librosa.decompose.hpss.html).
