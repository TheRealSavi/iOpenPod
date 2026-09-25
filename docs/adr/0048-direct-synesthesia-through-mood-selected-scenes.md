# ADR-0048: Direct Synesthesia through mood-selected visual Scenes

- Status: Accepted
- Date: 2026-09-13
- Supersedes: ADR-0045 and ADR-0047 restrictions against named Scene selection
- Extended by: ADR-0049's music-driven Scene Motion and camera choreography
- Residence timing superseded by: ADR-0077's grouping across short Sections

## Context

The Coupled Field proof preserved substantially more Musical Evidence than the
earlier visualizer, but every moment still used the same composition: one particle
field, one filament mesh, one camera, one feedback treatment, and short event
ornaments. Even when the controls changed independently, a full Track read as one
pattern breathing and changing color.

Classic iTunes visualizers demonstrate a broader visual grammar. Their identity
comes from decisive changes among fluid ribbons, radial tunnels, mirrored waveform
contours, perspective lattices, color fields, orbital clusters, star chambers, and
large transient blooms. Magnetosphere adds sparse gravitational nuclei, orbiting
particle populations, satellite trails, and explosive changes of scale. These are
useful structural references, not assets to copy.

The music-analysis backend already supplies enough calibrated information to direct
such variety. Adding Scene labels or mood claims to `TrackAnalysis` would mix
presentation policy back into analysis.

## Decision

Add a frontend-only `SceneDirector` between `TrackAnalysis` and
`SynesthesiaRenderer`. It derives a presentation-owned `MoodSignature` from energy,
brightness, harmonicity, percussion, bass-register activity, stereo width, and
noise. Mood is an artistic control vector; it is not a claim about listener emotion,
genre, lyrics, or compositional intent.

The director divides long Sections into bounded Scene cues of at most 22 seconds,
samples the local musical evidence, scores the visual vocabulary, and applies a
deterministic diversity penalty to recently used Scenes. Adjacent cues cannot use
the same Scene. Selection remains stable for a Track and strongly mood-weighted
without allowing one high-scoring Scene to monopolize the entire runtime.

The initial Scene vocabulary is:

- **Magnetosphere** — gravitational nuclei, orbital particles, and radial bursts;
- **Ribbon Cascade** — layered fluid ribbons and travelling light;
- **Warp Tunnel** — radial depth, streaks, spokes, and accelerating rings;
- **Mirror Wave** — bilateral and kaleidoscopic waveform contours;
- **Prismatic Veil** — luminous folding sheets and broad color atmosphere;
- **Lattice Cathedral** — perspective grids, arches, and restrained geometry;
- **Solar Bloom** — a hot radial body, corona, petals, and flares; and
- **Star Chamber** — sparse parallax stars and a slow nebular horizon.

`SynesthesiaRenderer` draws the selected procedural Scene first, then projects the
shared particle field, comet species, filaments, and typed event phenomena with
Scene-specific gains. This lets a Scene remove a visual system completely instead
of painting every mechanism over every composition. Adjacent cues crossfade over a
short bounded interval; feedback retention drops during the transition so the old
silhouette does not smear over the new one.

The renderer's public input remains `TrackAnalysis`. The analysis backend gains no
Scene, mood, palette, shader, or camera fields. Existing Field Impulses continue to
affect shared particle physics and retain their burst, laser, rift, or Source-flare
character.

## Consequences

- Similar moments can retain continuity, while materially different musical moods
  receive different silhouettes, spatial organizations, and motion languages.
- A five-minute Track receives enough Scene opportunities even when structural
  analysis finds only a few long Sections.
- Scene choice, transition policy, and system visibility are deterministic and
  unit-testable without a graphics context.
- The shader uniform contract and portable QShader packages expand again.
- The visual acceptance test is no longer whether one fixed field survives five
  minutes. It is whether the directed sequence feels musically caused, varied, and
  coherent rather than random or preset-timed.
- ADR-0045 still governs ephemeral analysis, transport behavior, GPU ownership, and
  resource recovery. ADR-0047 still governs independent evidence mapping and typed
  events. Their prohibitions on named Scenes and Scene selection are historical.
