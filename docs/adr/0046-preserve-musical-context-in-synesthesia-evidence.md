# ADR-0046: Replace the Synesthesia analysis contract

- Status: Accepted
- Date: 2026-09-13
- Supersedes: ADR-0042's World Score result contract and ADR-0045's restriction of
  musical evidence to five force-input families

## Context

The first Synesthesia backend accumulated three overlapping contracts: a broad
string-addressed World Score, a reduced force-oriented Music Evidence Timeline, and
learned-provider contributions shaped around both. The analyzer mixed musical
measurement with presentation response policy. Its reduced trusted seam discarded
Sections, source context, and part of the rhythm and timbre analysis that the same
Job had already computed. Consistently mastered music could consequently produce
nearly stationary forcing even when its arrangement and musical role changed.

Literal instrument identification is a separate reliability problem. Harmonic and
percussive separation can describe overlapping acoustic families deterministically,
but it cannot honestly label vocals, drums, bass, and residual instrumentation.
Those labels require a learned separation provider and must retain provider
confidence and provenance.

## Decision

Replace the existing backend contract without a compatibility adapter.
`WholeTrackMusicAnalyzer.analyze(...)` is the single Application Layer operation,
and immutable `TrackAnalysis` is its single result. The GUI and presentation layer
will migrate independently.

`TrackAnalysis` groups measurements into explicit energy, rhythm, spectrum, timbre,
harmony, spatial, layer, and structure domains. Every sampled signal carries fixed
timing, physical or normalized units, validity, and independent confidence. The
result also carries complete-Track Sections, discrete musical events, typed Sources,
issues, and provider provenance. No result field prescribes visual response.

The deterministic core always provides calibrated absolute and Track-relative
energy, seven fixed spectral bands, multiband onset and pulse analysis,
confidence-gated tempo and pitch, harmonic and timbral motion, stereo evidence,
acoustic source families, and novelty/recurrence structure. It does not fabricate
beats, notes, or multiple Sections when evidence is insufficient, and it does not
claim semantic Section names.

Optional learned providers run only after the deterministic result succeeds.
HTDemucs may replace broad harmonic/percussive Sources with vocals, drums, bass, and
other Sources. Provider absence or failure becomes a typed issue and never destroys
the core result. `ENRICHED` is the default request; callers choose `STANDARD` when
they explicitly want deterministic-only cost.

FFmpeg decoding and every derived array remain bounded and runtime-only. No decoded
PCM, stem, embedding, or analysis cache is persisted.

## Consequences

- The old `WorldScore`, `MusicEvidenceTimeline`, feature catalog, controller, and
  dual analysis operations are removed from the backend package.
- Existing GUI imports were allowed to stop compiling until presentation migrated
  to `TrackAnalysis`; ADR-0047 defines the completed migration and response policy.
- A mastered Track retains internal contrast without sacrificing calibrated levels
  across Tracks.
- Sections, events, rhythm, timbre, harmony, stereo space, and source changes reach
  consumers through one typed result instead of a reduced or string-addressed seam.
- Deterministic source-family activity is never mislabeled as an instrument.
- Optional provider cost and failure are isolated from always-available analysis.
