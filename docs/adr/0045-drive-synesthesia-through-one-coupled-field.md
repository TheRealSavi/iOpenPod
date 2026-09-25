# ADR-0045: Drive Synesthesia through one coupled field

- Status: Accepted
- Date: 2026-09-13
- Supersedes: The World Score presentation contract in ADR-0042 and the visual
  architecture in ADR-0043 and ADR-0044
- Superseded in part by: ADR-0046's complete Music Evidence Timeline
- Superseded in part by: ADR-0048's frontend visual Scene direction

## Context

The topology proof made a stable branching tunnel authoritative, then depended on
an autonomous camera and material reinterpretation to make that tunnel interesting.
In motion it was a slow trip through a pipe. Geometry described a place, but there
was too little matter, force, interaction, or music-driven change to sustain the
experience. The camera was compensating for an inert simulation.

The upstream contract also proved unsuitable for physical control. `WorldScore`
contains a broad, string-addressed catalog whose analyzer-authored response
envelopes mix musical measurement with presentation policy. In particular, each
spectral band was normalized independently over the Track. An insignificant band
could therefore reach the same apparent maximum as a dominant band, so the values
could not be compared as bass mass or fine-frequency energy. Expensive learned
providers also ran before the small deterministic signal set needed by this proof.

The desired visualizer is closer to a contemporary continuation of classic music
visualizers than an authored three-dimensional environment. It needs a dark field
with real depth in which particles, smoke, waves, turbulent flow, electrical
filaments, recursive growth, and temporal traces expose the same changing forces.
Several readings may emerge from those relationships, but the implementation must
not switch between named scenes or literal objects.

## Decision

Synesthesia uses this boundary sequence:

```text
Music Analysis Job
  -> Music Evidence Timeline
  -> Field Conductor
  -> Field Forcing
  -> coupled GPU field
  -> temporal composition
```

The following five-input restriction records the original proof. ADR-0046
supersedes it with a complete typed Music Evidence Timeline while retaining the
same boundary sequence and Field Conductor ownership of response policy.

`MusicEvidenceTimeline` is the small, typed, force-ready result of deterministic
analysis. Its first proof contains exactly five musical inputs:

- activity: audibility-gated whole-mix power;
- low-frequency mass: the audible share of low-band power;
- impact: typed, confidence-gated positive-flux occurrences;
- fine excitation: audible high-band energy and positive spectral flux; and
- harmonic coherence: an organization measurement whose value is independent of
  estimator reliability.

These values have fixed meanings and independent reliability. Absolute/share-based
spectral measurements replace independently percentile-normalized band controls.
The analysis layer does not prescribe attack, release, slew, forces, materials,
camera behavior, narrative, or visual interpretation. The deterministic timeline
is always available first; optional learned enrichment may not block this proof.
The existing broad `WorldScore` may remain temporarily as a compatibility envelope,
but it is no longer the trusted presentation contract.

`FieldConductor` owns the artistic mapping from evidence to physics. It applies its
own response envelopes and produces typed continuous forcing plus idempotent
impulses. Continuous forcing controls kinetic activity, wells, turbulence, charge,
conductivity, emission, and organization. An impact injects a spatial pressure
wave; it is not a flash command or a camera cue.

The visual authority is one bounded three-dimensional field. A small stable set of
attractors and repulsors, curl-like flow, pressure waves, density, charge, and slow
organization coexist in the same coordinates. Particles reveal its velocity;
smoke-like matter is advected by it; pressure disturbs both; charge follows and
reinforces conductive organization; branching filaments sample that same state.
These are coupled views of one system, not sequential effects.

High-volume live simulation state resides on the GPU behind the renderer's narrow
advance, render, diagnostics, and recovery seam. Stable seeds, force-pole identity,
Transport Epoch, and an idempotent impulse-delivery ledger remain on the CPU. A
graphics-resource loss may reconstruct disposable detail from those values behind a
brief fade; exact particle identity and pixel history are not product semantics.

Temporal feedback is a restrained presentation layer. Each frame may advect and
decay prior light before adding the current field projection, creating trails and
continuity without making retained pixels the physical simulation. Bloom and tone
mapping remain subordinate to legible structure and black space.

The camera is nearly stationary, with at most slow bounded parallax. There is no
camera rail, authored environment, asset sequence, story progression, explicit
vascular/botanical/terrain/cosmic state, or motif catalog. If the coupled simulation
is not compelling from a fixed view, the proof has failed.

Pause freezes simulation and conductor evolution. A seek starts a new Transport
Epoch, reanchors evidence sampling, preserves the current live field, and delivers
no skipped-event backlog. Recrossing an event in a later epoch may create a new
impulse; an event is delivered at most once within one epoch.

The production renderer remains a `QRhiWidget`. Its primary quality tier uses QRhi
compute pipelines, ping-pong storage buffers, instanced particle quads, offscreen
render targets, and packaged portable QShader artifacts. Quality tiers may change
particle count, volume resolution, or postprocessing cost, but may not substitute a
different visual architecture.

The first acceptance run is deliberately narrow: one field, a large particle
population, a few force poles, turbulent flow, smoke-like density, propagating
waves, branching electrical filaments, recursive organization, and restrained
feedback driven by the five inputs above. It is observed from a fixed or nearly
fixed camera for five minutes. Breadth resumes only after that run demonstrates
continuous, musically legible emergence.

## Consequences

- The tunnel mesh, fixed branching topology, scar, interpretation schedule, and
  autonomous camera are removed rather than generalized.
- Musical measurements become testable against synthetic signals with physical
  expectations: low tones must produce more low-frequency mass than high tones,
  and steady tones must not invent impact events.
- Presentation response can be tuned per force without changing or relabeling
  Musical Evidence.
- Particles, smoke, waves, filaments, recursive growth, and feedback can interact
  because they share one coordinate system and forcing model.
- GPU simulation makes large populations practical but requires explicit resource
  recovery, cross-backend shader packaging, bounded time steps, and capability
  diagnostics.
- Exact replay across different graphics backends is not promised. Transport
  behavior, event identity, force meaning, stable genesis, and bounded state are the
  portable contract.
- ADR-0042 retains ephemeral analysis, cancellation, provenance, validity, and no
  Track-derived persistence. ADR-0043 retains continuous generative motion.
  ADR-0044 retains Transport Epoch semantics and the verified QRhi widget host. All
  topology-, scar-, interpretation-, camera-, and broad-World-Score-specific
  decisions in those records are historical.
