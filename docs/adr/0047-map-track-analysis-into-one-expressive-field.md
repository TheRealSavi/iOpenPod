# ADR-0047: Map Track Analysis into one expressive field

- Status: Accepted
- Date: 2026-09-13
- Supersedes: ADR-0045's restriction of presentation input to four continuous
  values plus impacts
- Superseded in part by: ADR-0048's frontend visual Scene direction

## Context

ADR-0046 replaced the music-analysis backend with `TrackAnalysis`, but the existing
presentation still imported the removed World Score contract. Its conductor also
reduced every moment to activity, low-frequency mass, fine excitation, and harmonic
coherence. The shader derived color mostly from a Track seed and elapsed time. That
made materially different Sections, Sources, spectra, and stereo arrangements look
too similar even when the backend had measured those differences.

## Decision

Migrate the Synesthesia integration directly to `TrackAnalysis` without a World
Score compatibility envelope. A Qt-facing `SynesthesiaController` runs one Musical
Analysis Job off the GUI thread and privately plays the chosen Host file.

`FieldConductor` samples the complete Track Analysis and preserves independent
controls for energy, bass mass, fine excitation, harmonic coherence, chroma-derived
palette, spectral brightness and flux, timbral noise, stereo pan and width, beat
phase, acoustic or learned Source activity, and Section progress, identity, energy,
and novelty. Reliability is applied before a measurement becomes forcing. Onsets,
downbeats, Source entrances, and Section boundaries become confidence-gated Field
Impulses delivered at most once per Transport Epoch. Each impulse retains a typed
presentation character across the persistent-world boundary instead of collapsing
to amplitude alone.

The GPU uses those controls to modulate one shared system through multiple drawing
passes. Ambient particles reveal the base flow; a selected particle species becomes
velocity-aligned comets under flux and percussion; filaments reveal harmonic and
vocal organization; and the event pass renders onset bursts, downbeat lasers,
Section rifts, and Source-entrance flares. Every event also remains a physical
pressure input to the same particle simulation. No control chooses a named scene or
literal instrument animation.

The page is a full-bleed visual field with sparse musical annotation. Its seekable
timeline displays the backend's actual Section spans, while its readout reports the
current Section, confidence-gated tempo, relative energy, and active typed Sources.

## Consequences

- Similar loudness no longer implies similar geometry or color.
- Sections and Source changes remain visible without resetting the persistent
  Coupled Field.
- Common downbeats provide a reliable laser cadence even when learned Source
  separation is unavailable; rarer evidence produces correspondingly rarer forms.
- Distinct passes can become fully dormant, preventing quiet or unsupported
  evidence from degenerating into permanent decorative motion.
- The renderer uniform contract grows to carry the independent controls; packaged
  QShader artifacts must be rebuilt whenever that layout changes.
- Instrument names appear only when a typed Source supports them. The deterministic
  fallback remains honestly labeled harmonic and percussive.
- Analysis, presentation mapping, persistent-world state, and GPU drawing remain
  separate, testable boundaries.
