# Melody extraction for short Alarm Tones

Investigated 2026-11-13 for the requested **Convert to tone** Track action.
The target is a roughly seven-second sequence of monophonic notes and rests,
not an excerpt of recorded audio. Native sound selection is documented in the
[click-wheel sound investigation](alarm-sounds-clickwheel-2026-11-13.md);
the tone-authoring investigation separately qualifies writable note sequences.

## Recommended approach

Use the existing NumPy, SciPy and librosa dependencies for a bounded two-pass
analyzer. First rank short phrases throughout the Track using repetition,
audibility and musical boundaries. Then estimate a continuous melodic pitch
path for a small set of promising phrases using harmonic salience and temporal
continuity. Convert the winning path into notes and rests and let the user hear
the generated Tone before saving it.

This is an iOpenPod arrangement algorithm inspired by published predominant
melody methods. It must not be described as an implementation of MELODIA, an
exact transcription, or a guaranteed identification of the composer's main
melody. No new dependency or downloaded model is required for this approach.

## What the primary sources establish

Predominant melody estimation has two tasks: identify when a melodic voice is
present and estimate its fundamental frequency. The established salience-based
approach uses spectral peaks, weighted harmonic evidence and continuous pitch
contours. Contour salience and pitch evolution help distinguish melody from
accompaniment. The author's overview also explains why equal-loudness
preprocessing can reduce low-frequency accompaniment dominance. These are
algorithmic precedents, not accuracy evidence for a new implementation.
[Salamon's explanation](https://www.justinsalamon.com/melody-extraction.html)
and [the original paper](https://mtg.upf.edu/node/2436).

The reference pitch-salience implementation sums evidence at harmonics of each
candidate fundamental. Its defaults include exponential harmonic weighting of
0.8, 20 harmonics, a 40 dB spectral-peak threshold and 10-cent pitch bins. Those
values are a useful starting reference; a different sample rate, preprocessing
or contour selector requires independent evaluation.
[PitchSalienceFunction](https://essentia.upf.edu/reference/streaming_PitchSalienceFunction.html).

The full reference melody estimator adds contour grouping, octave/outlier
filtering and voiced/unvoiced selection. Its documentation recommends
equal-loudness preprocessing and normally leaving unvoiced sections unpitched.
This establishes why a strongest-bin lookup or independent per-frame winner is
not an adequate substitute.
[PredominantMelody](https://essentia.upf.edu/reference/streaming_PredominantMelody.html).

librosa's pYIN computes candidate fundamental frequencies and probabilities,
then performs Viterbi decoding to return pitch, voicing flags and voicing
probabilities. It is appropriate for a clear monophonic source. HPSS separates
harmonic from percussive components, so its harmonic output can still contain
bass, chords and multiple melodic instruments. HPSS followed by pYIN therefore
does not by itself establish predominant-melody recovery from a full mix.
[pYIN 0.11](https://librosa.org/doc/0.11.0/generated/librosa.pyin.html),
[fundamental-frequency tutorial](https://librosa.org/doc/dev/auto_tutorials/01-intro/03-f0.html)
and [HPSS 0.11](https://librosa.org/doc/0.11.0/generated/librosa.decompose.hpss.html).

Recurrence compares features at separate times, with an exclusion width for
nearby frames. Chroma recurrence can support phrase ranking, but a repeated chord
progression does not prove that a phrase is a chorus or the main melody.
[Recurrence matrix 0.11](https://librosa.org/doc/0.11.0/generated/librosa.segment.recurrence_matrix.html).

Context7 was used to resolve and query librosa documentation. Its latest results
currently include newer APIs such as `transition_min_prob` and `loadx`; neither
belongs to this repository's locked librosa 0.11 API. The versioned references
above control implementation syntax.

## Concrete analysis design

The following choices are proposed iOpenPod policy, not recovered Apple behavior
or claims that the cited algorithms use this exact combination.

1. Decode the complete selected Track into bounded float PCM. Reject nonfinite
   data and retain real silence. Work at 22,050 Hz; avoid retaining a full
   high-resolution spectrogram for the whole Track.
2. Measure coarse harmonic chroma, energy and onset strength in cancellable
   blocks. Compare ordered short chroma sequences at separated positions,
   rather than comparing only average pitch-class histograms. Coarsen the
   repetition grid and bound the comparison set to prevent an unbounded
   full-resolution quadratic matrix.
3. Rank candidate starts near onsets or phrase boundaries. Reward repetition,
   sustained audibility and musical activity; penalize silence and windows
   consisting of a single unchanging note. Keep a small, temporally diverse
   set, such as six candidates. Repetition is evidence, not a requirement:
   through-composed music still needs eligible candidates.
4. Analyze each candidate with surrounding context. A 4,096-sample FFT and
   256-sample hop at 22,050 Hz are plausible initial settings for short
   candidates. Estimate spectral peaks and remove percussive interference.
   Use perceptual frequency weighting or bounded spectral whitening, with a
   noise floor so quiet numerical bins do not become salient.
5. For candidate fundamental `f`, sum harmonic support using a decay such as
   `0.8 ** (harmonic - 1)`. Compression of peak amplitudes and normalization
   are tunable choices. Preserve evidence when the fundamental itself is
   missing. Penalize unsupported subharmonic candidates using harmonic
   distribution, not a rule demanding a visible fundamental.
6. Select a temporal pitch path with an explicit unvoiced state. Reward
   supported continuity and discourage unsupported large jumps. Compare
   octave-related paths; do not blindly lower every high estimate by an
   octave. A sustained loud bass path can be continuous, so phrase scoring
   also needs melodic movement and note diversity. These preferences require
   tests with a quiet, slowly moving lead and a more active accompaniment.
7. Merge stable pitch regions into notes and retain rests. Suppress tiny
   pitch flicker without erasing short intentional notes or repeated
   same-pitch attacks. Use detected onset evidence for articulation. Trim
   leading/trailing silence, avoid cutting a final note unnecessarily and
   keep the result close to the requested duration without changing tempo.
8. Rank extracted candidates again using pitch support, audible coverage,
   note continuity and phrase repetition. Preview the actual serialized
   note durations and frequencies; do not preview the original recording
   as though it were the resulting Tone.

Low-confidence or nonmelodic input should report that a usable melody could not
be found. It must not silently substitute a fixed tune, fabricate a melody, or
produce a chain of noise-derived notes. Dense ensembles, rap, unpitched
percussion, layered vocals and prominent accompaniment remain difficult inputs.
Listening acceptance is needed in addition to synthetic correctness tests.

## Existing application seams

| Seam | Reuse or limitation |
| --- | --- |
| [`PlaybackSourceProvider`](../../src/iOpenPod/app/playback/backend.py) | Supplies independent read-only Track bytes without giving the analyzer a Mount Point or Filesystem Session. |
| [`DeviceCoordinator.open_playback_source`](../../src/iOpenPod/app/services/device_coordinator.py) | Resolves the current Library Track and binds range reads to the current session and captured file identity. |
| [`SynesthesiaController`](../../src/iOpenPod/app/synesthesia/controller.py) | Existing example of asynchronous source materialization, cancellation, temporary encoded-file cleanup and rejection of stale completion. Do not couple Tone conversion to playback transport. |
| [`FFmpegDecoder`](../../src/iOpenPod/app/synesthesia/audio.py) | Bounded stereo float32 decode, injected media-tool resolution, cancellation checkpoints, process cleanup and a default 15-minute decoded-duration bound. A Tone backend can use a separate instance with explicit limits. |
| [`DeterministicMusicAnalyzer`](../../src/iOpenPod/app/synesthesia/dsp.py) | Its private predominant-pitch calculation chooses the strongest harmonic spectral bin. This is insufficient for the new melody contract and should not be reused as a transcription result. |
| [`PhasePart`](../../src/iOpenPod/app/phase_parts.py) | Contains bands, energy, chroma and magnitudes, not separated PCM or note pitch. |
| [`ManagedPhaseSources`](../../src/iOpenPod/app/phase_runtime.py) | Installed child runtime returns Phase Parts; it does not expose separated audio for pYIN. |
| [`DemucsSourceEnricher`](../../src/iOpenPod/app/synesthesia/enrichment.py) | Computes separated audio internally but returns derived analysis. Its public result also cannot supply melody PCM. |

The optional Demucs model separates source families, including vocals. Its
six-source model adds guitar and piano, with acknowledged quality limitations.
A future separated-source melody route would need a new bounded output contract
and tested fallback; installing the existing runtime does not make its current
feature arrays usable as a pitch sequence.
[Demucs upstream documentation](https://github.com/facebookresearch/demucs)
and [ADR-0225](../adr/0225-install-optional-phase-analysis-with-safe-fallbacks.md).

Keep the new analyzer independent of the GUI and of device publication. Pass
typed progress and a cancellation checkpoint. Check cancellation between scan
blocks, candidates and path-decoding chunks; bound the longest noninterruptible
DSP operation. The GUI must discard a result if the selected device or source
generation changed. Saving the resulting native file remains an explicit
source-checked Storage Transaction.

## Diagnostic performed

A local seven-second synthetic sequence contained 14 half-second harmonic notes
between MIDI 60 and 69, with five harmonics and short amplitude ramps. pYIN 0.11
at 22,050 Hz, hop 256 and quarter-semitone resolution recovered 97.5% of all
frames within half a semitone for the isolated sequence. Adding sustained
130.8128, 196 and 261.6256 Hz accompaniment reduced correct melody frames to 0%,
despite returning voiced estimates for 64.8% of frames. This is a diagnostic of
the monophonic assumption, not a general comparison of melody algorithms.

On this Windows Host, the first pYIN call including lazy setup took 1.79 seconds;
the next took 0.11 seconds. STFT plus HPSS on seven seconds took 0.88 seconds.
These timings exclude full-Track scanning, capture, decode and any proposed
salience/path implementation. They are not a latency promise.

The reproducible private harness and receipt are
`.scratch/tones-research-20261113/benchmark.py` and `benchmark.json`. Run with
`uv run python .scratch/tones-research-20261113/benchmark.py`. No physical iPod
was accessed and no audio was uploaded.

## Implementation acceptance

Proportionate tests should cover known-note melodies with louder bass/chords,
missing fundamentals, dominant upper harmonics, repeated same-pitch attacks,
rests and vibrato; silence and percussion-only rejection; selection of a later
recurring phrase over an intro; nonrepeating melodic music; short Tracks and
duration limits; cancellation and stale-device completion. Check pitch and
duration behavior against generated ground truth, not only that a nonempty
Tone was produced. At least a small varied listening set is needed before
claiming perceptual melody quality on real music.
