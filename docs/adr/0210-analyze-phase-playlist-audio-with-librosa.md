# ADR-0210: Analyze Phase playlist audio with librosa

- Status: Accepted
- Date: 2026-10-30
- Supersedes: ADR-0209's placeholder-chart generation policy

Phase saves generate gameplay analysis from each eligible Track's actual audio.
The Application Layer owns decoding and music analysis using the existing
librosa dependency and the bounded FFmpeg runner already used for Genius.
iPodDB owns typed transient/beat records and the native PHZ envelope. Firmware,
game executables, Ghidra and emulators remain offline verification tools.

The first real analyzer uses mono 22,050 Hz PCM, overlapping bounded STFT/HPSS
blocks, mel-band onset strength and onset detection, plus local beat tracking.
Low, mid and high onset strengths map to the three five-bit transient fields.
Pulse strength and harmonic energy map to the two four-bit beat fields. This is
an iOpenPod musical mapping, not a reconstruction of iTunes' original analyzer or
a claim that every packed field's gameplay role has been recovered. See
[Phase audio analysis](../phase-audio-analysis.md) for constants and validation.

The first save upgrades existing charts, including placeholders, when they lack
matching analysis provenance. Subsequent saves reuse a chart only when the audio
content SHA-256, Track duration, algorithm version and chart SHA-256 match. The
small application-owned provenance file accompanies chart and index writes in the
same recoverable Storage Transaction. It is bounded to the current playlist.
Removing tracks does not delete their old gameplay files.

Prepared incoming audio is analyzed before publication using its verified Host
source. Retained audio is read through its identity-bound Filesystem Session.
Source fingerprints are checked around analysis and retained device inputs enter
the save transaction's preconditions. Analysis supports cancellation between
decode/DSP stages and blocks, reports per-Track progress, and retries tool
discovery on subsequent saves. Decode failures stop preparation; they never
silently substitute a fabricated chart. Silence encodes empty event streams.

Spectral blocks use two bounded DSP workers because profiling identified HPSS
median filtering as the dominant CPU cost. Only two blocks are admitted at once;
PCM is shared read-only and feature assembly preserves the original order.
Device I/O and analysis checkpoints remain on the coordinator. Cancellation or
failure stops further admission and drains workers before returning. This avoids
concurrent disk seeks and multiple whole-song PCM buffers. Exact chart equality
with serial execution is a regression requirement; the cache version stays valid.

The native build-3168002 parser accepts generated musical and silent charts, with
counts, packed magnitudes and Q16.16 timing checked against its decoded output.
Signal tests check attack alignment, band variation, quiet passages, tempo changes
and repeatability. This does not establish physical gameplay quality.
