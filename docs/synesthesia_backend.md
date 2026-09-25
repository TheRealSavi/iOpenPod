# Synesthesia Music-Analysis Backend

The low-level analysis boundary has one operation and one result. It analyzes a
private Host audio-file path and returns a fresh, immutable `TrackAnalysis`:

```python
from pathlib import Path

from iOpenPod.app.synesthesia import AnalysisRequest, WholeTrackMusicAnalyzer

analyzer = WholeTrackMusicAnalyzer()
analysis = analyzer.analyze(
    Path("music.flac"),
    AnalysisRequest(title="A Track"),
    checkpoint=lambda: None,
    progress=show_progress,
)

frame = analysis.sample(37.5)
section = analysis.section_at(37.5)
new_events = analysis.events_between(37.0, 37.5)
```

Run analysis in a worker thread. The operation decodes its input into bounded
memory, calls cooperative cancellation checkpoints, reports typed progress, and
creates no cache entries. The default decoder uses 32 kHz stereo float PCM and
rejects audio longer than 15 minutes; callers may set a different explicit bound
when long-form music is in scope.

`SynesthesiaController` is the Qt-facing integration adapter. It runs one analysis
at a time, forwards typed progress for the current Track, and discards stale Job
output. While Synesthesia is active, `prepare_next()` accepts the Player's next
Playback Entry and prepares it behind current analysis. It retains at most one
upcoming result in memory. `analyze(..., entry_id=...)` promotes matching completed
or unfinished preparation when playback advances; other entries start a new Job.
Preparation follows Queue and forward History changes, reports no progress or
failure to the current Track's status surface, and is released when the page closes
or the playback session ends. A failed preparation retries when its entry becomes
current. See ADR-0078.

Both inputs come from the Player. The worker opens a separate,
identity-bound `PlaybackSource`, materializes its encoded bytes in a private
temporary Host file for the path-oriented analyzer, and removes that copy on every
exit path.

The Player's `PlaybackController` and `PlaybackBackend` remain the only audio and
transport owners. Synesthesia never creates a media player or sends pause, play,
stop, restart, or seek commands. Its graphics-only page observes current Player
state; after analysis it installs `TrackAnalysis` and aligns with the latest Player
timestamp through bounded clock correction. While analysis is pending, a
Synesthesia Preview follows the Player clock without reading audio or
claiming Musical Evidence. Once the result is ready, the renderer blends into
the analyzed field while preserving its live state. The controller does not alter
or reduce `TrackAnalysis`; the Field Conductor samples that result directly.

## Result model

`TrackAnalysis` is organized by musical domains instead of renderer controls or
string-addressed feature IDs. It contains:

- `metadata` describing the decoded audio;
- an `AnalysisTimeline` with calibrated energy, rhythm, spectrum, timbre, harmony,
  stereo space, overlapping acoustic layers, and structure;
- contiguous complete-Track `sections` with motif labels and acoustic profiles;
- ordered onset, beat, downbeat, Section-boundary, and Source-activity `events`;
- acoustic or learned `sources`, each with its own activity, level, onset,
  brightness, pan, width, confidence, and provenance;
- typed degradation `issues`; and
- the exact provider `provenance` used to produce the result.

Every continuous signal carries a `TimeGrid`, unit, validity, and independent
per-frame confidence. `sample(seconds)` interpolates those measurements into a
`MusicFrame` whose scalar members remain typed `SignalSample` values and whose
vector members remain typed `VectorSample` values. Callers inspect each member's
own value, confidence, unit, and validity; there is no aggregate frame confidence.
Tempo and pitch retain their estimator output with zero confidence when unsupported,
so silence is not assigned a usable default metronome, note, or sequence of fake
Sections.

The result intentionally contains no force strengths, smoothing envelopes, shader
parameters, color, camera cues, world positions, or drawing commands. Presentation
owns every mapping from musical evidence to behavior.

## Deterministic core

The always-available core runs once across the complete song and computes:

- true waveform RMS in dBFS, Track-relative energy, and crest factor;
- seven Parseval-normalized bands: sub-bass (20-60 Hz), bass (60-250 Hz),
  low-mid (250-500 Hz), mid (500-2,000 Hz), upper-mid (2,000-4,000 Hz),
  presence (4,000-8,000 Hz), and brilliance (8,000 Hz to Nyquist);
- band power distribution and positive amplitude flux;
- multiband onset strength, predominant pulse, beats, downbeats, local tempo, and
  beat phase when meter is supported by the audio;
- chroma, harmonic coherence and change, and confidence-gated predominant pitch;
- spectral centroid, bandwidth, rolloff, flatness, contrast, and timbral change;
- pan, width, and channel correlation, with explicit limited validity for
  false-stereo audio;
- harmonic/percussive separation and overlapping bass-register, harmonic,
  percussive, and noise activity; and
- novelty-based structural boundaries plus recurrence-based motif labels such as
  A, B, A. The core does not claim semantic verse or chorus names.

Absolute and Track-relative measurements are both retained. This prevents a
consistently mastered Track from flattening its internal dynamics while preserving
meaningful comparisons between files.

## Optional instrument Sources

`AnalysisRequest` defaults to `ENRICHED`. The default optional enricher uses
HTDemucs to replace the core's broad harmonic/percussive Sources with learned
vocals, drums, bass, and other Sources. Each Source remains tied to model provenance
and separation confidence. A missing model is an informational issue; a provider
failure is a failed-provider issue. Neither discards the deterministic result.

Use `STANDARD` for deterministic-only analysis:

```python
from iOpenPod.app.synesthesia import AnalysisMode, AnalysisRequest

request = AnalysisRequest(mode=AnalysisMode.STANDARD)
```

Install the optional provider only when instrument separation is wanted:

```shell
uv sync --extra synesthesia-gpu
```

Model weights may remain in the provider's own store. The encoded temporary copy is
deleted when the Job ends. Decoded PCM, separated audio, and analysis results remain
in memory for the current Musical Analysis Job only.

## Extension seam

Additional learned analysis belongs behind `AnalysisEnricher`. An enricher receives
the decoded audio and successful core result, then returns typed Sources, events,
and provenance. It may replace Source classification, but it may not replace the
calibrated deterministic domains or introduce presentation policy.

See [ADR-0046](adr/0046-preserve-musical-context-in-synesthesia-evidence.md) for the
analysis-result decision and
[ADR-0051](adr/0051-make-player-transport-authoritative-for-synesthesia.md) for the
Player integration and source-lifetime decision.
