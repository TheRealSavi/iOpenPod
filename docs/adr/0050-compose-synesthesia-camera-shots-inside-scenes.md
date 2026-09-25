# ADR-0050: Compose Synesthesia Camera Shots inside Scenes

- Status: Accepted
- Date: 2026-09-14
- Extends: ADR-0049

## Context

ADR-0049 gave every visual Scene a directional journey, but it represented both
world motion and camera intent with one continuous `SceneMotion`. The renderer then
invented one sinusoidal orbit around the origin with a fixed lens. More importantly,
the dominant procedural Scene remained a screen-space image, so changing the field
camera mostly moved particles and filaments layered above an unchanged composition.
An entire Scene residence therefore read as one animated viewpoint.

Track Analysis already provides Sections, local development, stereo position, and
reliable musical events. Camera parameters do not belong in that analysis result;
they are editorial presentation decisions.

## Decision

Deepen `SceneDirector` so its single `sample(musical_seconds)` operation also returns
an immutable Camera Shot and Camera Pose. A Camera Shot has an identity, a bounded
span, and one of a small visual-editorial vocabulary: establishing, track, orbit,
inspection, fly-through, or reveal. A Camera Pose contains position, target, roll,
and vertical field of view.

Each Scene owns a distinct private shot grammar. The Scene Director composes one to
four shots within a Scene residence according to its duration, joins their authored
poses with bounded smooth paths, and bridges ordinary Scene boundaries without a
viewpoint discontinuity. Interior edits may move within a small window to a
trustworthy Section boundary, Source entrance, downbeat, or strong beat. Beats do
not pulse the lens or continuously shake the camera. Planning is deterministic per
Track and experience seed, and sampling depends only on musical time, so pause and
seek remain stable. Shot paths are rate-limited, and newly introduced tail shots
develop continuously around duration thresholds rather than abruptly replacing the
existing composition.

`SceneMotion` now describes world travel, orbit, depth flow, waveform deformation,
parallax, and world scale only. It does not encode camera policy. The renderer
receives the already composed Camera Pose and contains no Section or shot-selection
logic.

The procedural Scene pass reconstructs a world-space view ray from the Camera Pose.
Instead of intersecting absolute world-Z planes, which can fall behind a camera
during a bridged transition, it samples target-focused camera-facing slices. Each
slice uses focus distance plus a bounded relative layer offset. The dominant
composition and the shared Coupled Field therefore use one viewpoint and exhibit
perspective and parallax throughout directed transitions. Camera position, basis,
focus distance, lens scale, backend NDC orientation, and bounded motion share the
124-float uniform contract. Feedback retention falls during meaningful camera
travel so the previous viewpoint does not obscure the new composition.

The Scene Director normalizes tolerance-valid Section bounds into one exact,
contiguous cue partition before composing shots. An explicit seek preserves the
world simulation but clears retained presentation history because those pixels were
made from a different view.

## Consequences

- A long Scene residence contains a directed sequence of framings instead of one
  periodic camera oscillator.
- Different Scenes can establish, approach, inspect, pass through, and reveal their
  geometry with different visual grammar.
- The same Track, seed, and musical time reproduce the same shot and pose regardless
  of sampling history.
- Musical evidence influences edit timing, cue development, camera attention, and
  world motion without becoming renderer parameters in Track Analysis.
- Every shader that shares `FieldState` must keep the 124-float uniform layout and
  portable QShader packages must be regenerated together.
- Multi-slice perspective provides immediate depth and parallax. True opaque
  occlusion would require a later depth-attachment decision; this ADR does not imply
  one.
