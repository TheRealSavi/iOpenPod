# ADR-0043: Render Synesthesia as one continuous world

- Status: Accepted
- Date: 2026-09-13

## Context

ADR-0042 established the immutable World Score as the boundary between complete-song
musical understanding and presentation. A renderer could still consume that score
as disconnected effects, direct transient flashes, or a catalog of unrelated scene
presets. That would lose the intended experience: one world whose biological and
cosmic forms appear to descend from the same forces.

The experience needs strong art direction without moving GPU behavior, visual
memory, or camera choreography into the musical-analysis backend. It must also stay
alive during silence and degrade gracefully when some Musical Evidence is missing.

## Decision

Synesthesia renders one persistent procedural world. It rarely cuts. A fixed path
of rich Visual Motifs continuously interpolates through roots, leaf veins, mycelium,
coral, cells, fish-like schools, ribbons, river deltas, lightning, neurons, nebulae,
and the cosmic web. The motifs share eight Visual Laws: branching, spiraling,
radial growth, cellular division, fluid flow, wave propagation, erosion, and
network formation.

`GUI/synesthesia/WorldDirector` owns runtime-only World Memory and translates calm
`WorldMoment` samples into renderer-facing World Conditions. It remembers motif
identity, pigment, position, camera attention, and delayed pressure waves within the
current Track. It does not change the World Score or persist Track-derived data.

The broad causal mapping is:

- energy changes evolutionary speed;
- bass changes mass, depth, displacement, and delayed pressure;
- rhythm changes local activity rather than screen brightness;
- harmony changes stability and structural coherence;
- timbre changes material character;
- melodic motion changes growth direction;
- silence removes drive without removing the world.

The artist-facing controls are limited to Life–Cosmos, Evolution, Connectedness,
Scale, Dream Logic, Memory, and Entropy. Connectedness is the signature force: as it
increases, shared networks become visible and motifs transform more directly into
one another across apparent scales.

The GPU implementation belongs to `GUI/synesthesia`. A `QOpenGLWidget` renders the
world into paired floating-point feedback surfaces, then displays the retained
formation through a separate tone-mapping pass. PyOpenGL is the narrow OpenGL
binding. GPU resources are created and destroyed only while the widget's context is
current.

`app/synesthesia/SynesthesiaController` runs the Musical Analysis Job outside the
GUI thread and rejects stale completion by monotonic token. After analysis succeeds,
it owns a private Qt Multimedia session for the explicitly selected Host audio file
so renderer position and sound share one clock. The analysis backend remains
independent of playback and retains no cache or persistent World Score.

Fish-like forms are coordinated flow geometry, not autonomous animals. The design
does not add civilizations, genetic simulation, or a claim to interpret every
instrument, emotion, or compositional intention.

## Consequences

- New motifs must join the existing transformation path and reuse the Visual Laws;
  adding an isolated effect is not sufficient.
- Renderer evolution can continue when evidence is limited or silent because its
  state has momentum and a restrained idle condition.
- Seeking may reveal a different musical cause immediately, while visual state
  approaches the new conditions instead of cutting to a replacement scene.
- Visual Memory ends with the current runtime session and cannot become an
  undocumented Track cache.
- The application now depends on PyOpenGL in addition to Qt's OpenGL widget API.
- Visual regression inspection requires a working OpenGL context and complements,
  rather than replaces, deterministic unit tests for motif and directing rules.
