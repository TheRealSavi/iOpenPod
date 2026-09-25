# Synesthesia coupled-field research

- Date: 2026-09-13
- Scope: technical precedents for the first coupled-field proof in ADR-0045
- Status: implementation input, not a visual preset specification

## Question

What should replace a literal tunnel so Synesthesia has the immediacy of a classic
music visualizer, real spatial depth, and modern large-scale motion without becoming
a sequence of unrelated effects?

## Findings

### Make motion a field that matter reveals

Bridson, Hourihan, and Nordenstam's
[curl-noise method](https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph2007-curlnoise.pdf)
constructs divergence-free turbulent velocity from the curl of procedural noise.
It is inexpensive, spatially continuous, and explicitly designed for convincing
smoke and vapor motion. It is therefore a strong first-proof flow model: particles
can reveal its trajectories immediately while a later grid solver can deepen the
same seam.

Epic's
[vector-field particle documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/vector-fields?application_version=4.27)
documents the useful production relationship: a grid of vectors influences large
GPU particle populations, with a controllable blend between adding force and making
particles follow the field. Synesthesia should use the same conceptual separation
between the field and the matter that reveals it, without adopting Unreal assets or
emitters.

### Couple visible density to the same velocity

The NVIDIA GPU Gems chapter
[Fast Fluid Dynamics Simulation on the GPU](https://developer.nvidia.com/gpugems/gpugems/part-vi-beyond-triangles/chapter-38-fast-fluid-dynamics-simulation-gpu)
explains advection, force application, pressure projection, and passive scalar
density as composable GPU passes. Its central lesson here is not that the first proof
must implement a full Navier–Stokes solver. It is that smoke-like density and
particle motion should share velocity and external forces; otherwise they read as
layered effects. Ping-pong state and pass boundaries are the natural implementation
shape.

The later GPU Gems chapter on
[real-time 3D fluids](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-30-real-time-simulation-and-rendering-3d-fluids)
shows that three-dimensional density, velocity, and vorticity are viable GPU
building blocks. Dense ray-marched volume simulation is a later quality tier, not a
reason to postpone the current proof.

### Retain light, not a succession of scenes

[projectM](https://github.com/projectM-visualizer/projectm) remains a useful modern
implementation reference for the MilkDrop lineage. The original
[MilkDrop preset-authoring guide](https://github.com/clangen/milkdrop2-musikcube/blob/master/resources/Milkdrop2/docs/milkdrop_preset_authoring.html)
describes its double-buffered warp stage: sample the previous frame at displaced
coordinates, attenuate it, then composite new energy. Synesthesia should retain this
principle as a restrained temporal layer. The previous image can carry trajectories
and continuity, but it must not replace the physical field or drive preset changes.

## Local QRhi feasibility

A PySide 6.11.2 runtime probe on the development RTX 4070 host verified the intended
portable resource pattern with the actual project environment:

- Direct3D 11, Direct3D 12, and OpenGL created QRhi compute pipelines and completed
  compute dispatches inside a `QRhiWidget`;
- all three created a one-million-particle ping-pong pool using combined storage and
  vertex-buffer usage (32 bytes per particle, 64 MB total);
- all three created and wrote a 64 cubed `R16F` storage texture;
- all three reported compute, instancing, 3D-texture, float-format, and storage
  readback support; and
- Direct3D 11 and 12 do not support programmable point size through this path, so
  particles must be instanced camera-facing quads rather than point primitives.

Observed first-dispatch/readback wall times were approximately 15 ms on Direct3D 11,
5 ms on Direct3D 12, and 40 ms on OpenGL. Those figures include widget scheduling,
presentation, and readback around a trivial integrator, so they establish
feasibility rather than a production performance budget.

PySide exposes no explicit QRhi barrier API. Resource dependencies should therefore
be separated by compute- or render-pass boundaries: particle ping-pong, optional
volume advection, offscreen matter rendering, temporal composition, then final tone
mapping to the widget render target.

## Applied decision

The proof should combine these ideas rather than reproduce any one reference:

1. A bounded three-dimensional procedural force field provides curl, a few wells,
   pressure shells, charge, and slow organization.
2. At least 131,072 GPU particles reveal the field; larger soft particles expose a
   smoke-like population without a separate visual universe.
3. Pressure impulses alter trajectories and density. Fine excitation raises charge
   and filament probability. Harmonic coherence changes organization.
4. Offscreen ping-pong composition warps and decays prior light before adding the
   current projection.
5. A fixed or nearly fixed view is used for the five-minute acceptance run.

This is deliberately a first proof. A sparse 3D fluid grid, stronger
reaction-diffusion organization, and richer filament solvers may deepen the same
field later; they must not arrive as replacement scenes.
