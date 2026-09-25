# Synesthesia persistent-world architecture

> Superseded as current direction by
> [ADR-0045](../adr/0045-drive-synesthesia-through-one-coupled-field.md). This note
> remains historical research for the rejected topology-and-tunnel proof. See the
> [coupled-field research](synesthesia-coupled-field.md) for the active proof.

## Scope

This note investigates the architecture implied by the current artistic ruling:

- identity must survive changes of material, apparent scale, context, and rendering
  representation;
- topology must accumulate a biography of growth, pressure, damage, healing, and
  deformation;
- interpretation should begin changing before the decisive cue lets the viewer
  recognize the new interpretation;
- the same spatial world, causal events, and camera decisions must exist at every
  fidelity tier, including an integrated-GPU tier;
- the first proof is one continuously reinterpreted branching tunnel, not a catalog
  of scenes.

The research question is therefore not which technique draws the richest tunnel.
It is which architecture lets persistent matter remain itself while its meaning and
its rendered representation change.

This is research, not an accepted decision. It does not change product behavior,
dependencies, or an ADR. External facts below come only from official
documentation, specifications, source repositories, and original research papers.
Recommendations and unverified hypotheses are labeled separately.

## Finding

The strongest architecture is a **stable, CPU-authoritative branching graph with
biographical state, from which every visible representation is derived**.

The graph is the identity. Its nodes and branches have never-reused identities,
lineage, rest and current shape, age, damage, accumulated deformation, pressure
state, and interpretation envelopes. A bounded causal ledger records why durable
changes happened. Geometry, an implicit skeletal field, volumetric density,
particles, lighting, and material parameters are rebuildable projections of that
state. None of those projections owns identity.

This is a hybrid rather than an ideological all-mesh, all-SDF, or all-volume design:

- swept polygonal branches establish the Core World's depth, occlusion, tunnel,
  shadows, and integrated-GPU baseline;
- local skeletal implicit fields hide difficult junctions and support the most
  fluid transformations where the available graphics backend can afford them;
- bounded 3D fields carry pressure, atmosphere, and soft material transitions;
- particles make flow and causality legible but do not carry essential world state;
- one CPU-side camera planner sees the authoritative graph, so its decisions do not
  change with rendering fidelity.

For the production rendering Adapter, Qt 6.11's `QRhiWidget` is the best current
direction to validate. It remains a `QWidget`, defaults to Metal on macOS, Direct3D
11 on Windows, and OpenGL elsewhere, and exposes capability-gated compute, storage
buffers, instancing, and 3D textures. Its main risk is explicit: Qt gives the QRhi
family limited compatibility guarantees. That risk is containable behind one
rendering Seam. The current `QOpenGLWidget` remains useful for an early Core proof
only if the QRhi feasibility spike is blocked, and its shader ideas remain useful
as later material or atmosphere passes. Do not build the Core World twice. OpenGL
4.3 compute must not become an architectural requirement.

## Present repository evidence

The existing analysis side is already the right upstream shape. The immutable
`WorldScore` retains complete fields, sparse events, Source Objects, structure,
future evidence, confidence, and degradation information. It should remain the only
musical-analysis contract. See [ADR-0042](../adr/0042-analyze-audio-into-ephemeral-world-scores.md)
and the [Synesthesia backend contract](../synesthesia_backend.md).

At the time of this investigation, the visual side was an exploratory 2D
implementation (the superseded modules named below have since been removed):

- `WorldDirector` emitted two motif indices, a blend, 2D camera coordinates and
  scale, and scalar shader controls;
- [`SynesthesiaRenderer`](../../src/iOpenPod/GUI/synesthesia/renderer.py) owns paired
  2D floating-point feedback textures and draws full-screen triangles;
- `WORLD_FRAGMENT_SHADER` evaluated flat procedural fields in `vec2` coordinates,
  crossfaded motif fields, and retained the prior image;
- the Visual Motifs in the former `motifs.py` were shader-stable catalog indices,
  not persistent spatial entities.

That code can create continuity of pixels, but it cannot carry topology, 3D
position, physical occlusion, lineage, or a deformation history. This agrees with
the artistic diagnosis and is not a criticism of the analysis contract.

There is one documentation conflict to resolve before implementation. Accepted
[ADR-0043](../adr/0043-render-synesthesia-as-one-continuous-world.md) fixes paired
feedback surfaces as the GPU implementation and places all World Memory in
`WorldDirector`. The new requirement needs authoritative embodied memory below the
director and permits several rendering representations. If this recommendation is
accepted, ADR-0043 and the corresponding paragraphs in
[`source_architecture.md`](../source_architecture.md) should be amended or
superseded explicitly. They should not be made to agree silently.

## Make the backend and world one causal system

The analysis backend does not need another representation. It needs a presentation
consumer that treats `WorldScore` as a score instead of reducing it to shader
uniforms. Today's `_evidence()` path reads a small scalar subset, discards most
sample confidence and `ControlBehavior`, never consumes `upcoming_events`, and does
not distinguish a transport seek from ordinary playback. A package-internal score
conductor should correct that before any new Musical Evidence is requested.

The conductor and director should divide the existing contract into five kinds of
influence:

- **Genesis priors**: `WORLD_GENOME` and continuous semantic axes bias the initial
  spatial grammar and material tendencies. They do not choose a scene or make a
  semantic label literal.
- **Continuous conditions**: energy, spectral mass, harmony, timbre, spatial
  evidence, and Source Object presence become bounded forces and material targets.
  Each control follows its own attack, release, maximum slew, confidence, and
  validity instead of one universal smoother.
- **Causal occurrences**: Musical Events are delivered exactly once when a forward
  traversal crosses them. Irreversible growth, fracture, or revelation requires
  sufficient confidence; degraded evidence falls back to restrained continuous
  influence.
- **Structural memory**: the Structural Graph and recurring motif identities recall
  stable regions, branches, pigments, and camera subjects. A return revisits and
  further develops matter; it does not select a similarly named preset.
- **Forecast and staging**: anticipation, future energy, future novelty, and the
  existing lookahead prepare camera clearance, stillness, and interpretation arcs.
  They may stage a future cause but may not deform or scar matter before that cause
  occurs.

Source Objects and spatial fields should become stable force loci or regions of
influence, never cartoon drawings of instruments. This uses the backend's
separation and spatial evidence while preserving the existing deliberate limit
against claiming that every source or emotion is known.

The director's output should therefore deepen into typed, renderer-independent
World Conditions: continuous causes, idempotent event occurrences, interpretation
envelopes with delayed recognition, and semantic camera attention. Mesh density,
particle counts, shaders, texture dimensions, and fidelity remain absent. No
backend change is justified until a proof demonstrates a specific missing fact.

## What primary sources establish

### A graph is a credible developmental substrate

Runions and colleagues' leaf-venation model iteratively grows vein nodes while
maintaining a vein connection graph, and can produce both tree-shaped and looped
networks. Their later space-colonization work grows a 3D skeleton one node and
segment at a time under spatial attraction. These are direct precedents for keeping
developmental topology separate from final appearance, although neither paper
defines Synesthesia's identity or biography model
([leaf venation paper](https://algorithmicbotany.org/papers/venation.sig2005.html),
[3D space-colonization paper](https://algorithmicbotany.org/papers/colonization.egwnp2007.pdf)).

L-systems likewise model development through rewriting, and parametric L-systems
attach numerical state to branching elements. Environment-sensitive extensions
demonstrate growth constrained by collision, space, light, and water. This supports
using explicit developmental rules, but a raw rewritten string is not by itself a
stable entity store or event history
([The Algorithmic Beauty of Plants](https://algorithmicbotany.org/papers/abop/abop.pdf),
[environment-interaction paper](https://algorithmicbotany.org/papers/enviro.sig96.html)).

The self-organizing tree model demonstrates that procedural growth can coexist with
editing operations such as pruning and bending. It supports treating growth and
damage as operations on persistent structure rather than regenerating a replacement
asset ([original paper and abstract](https://algorithmicbotany.org/papers/selforg.sig2009.html)).

### A skeleton can drive more than one surface representation

Bloomenthal and Shoemake convolve fields around curve or polygon skeletons. Their
implicit surfaces were designed for seamless joins and fluid topology changes.
That is unusually close to Synesthesia's need for one branch graph to support soft,
vascular, botanical, and cosmic readings
([original paper](https://www.unchainedgeometry.com/JBloom/pdf/CSurfFinal.pdf)).

This does not mean every skeletal field is a signed distance field. Hart's sphere
tracing relies on distance information or a valid Lipschitz bound to take safe
steps. Smooth unions and convolution fields must therefore carry a conservative
distance bound, use another root finder, or be polygonized; calling every implicit
field an SDF would hide a correctness and performance risk
([original sphere-tracing publication record](https://experts.illinois.edu/en/publications/sphere-tracing-a-geometric-method-for-the-antialiased-ray-tracing/)).

Marching Cubes is the classic direct conversion of a sampled scalar field into a
triangle surface. It establishes a possible bridge from the same implicit field to
rasterized geometry, but its sampling and mesh-generation cost make a full-world
rebuild every frame a poor unproven assumption for the Core tier
([original paper](https://www.cs.toronto.edu/~jacobson/seminar/lorenson-and-cline-1987.pdf)).

For direct tube meshes, rotation-minimizing frames are a well-studied way to sweep a
cross-section along a spatial curve without unnecessary twist. Wang and colleagues'
double-reflection method is accurate and stable with a low per-frame computational
cost, making it a plausible implementation technique for curved branches
([original publication record](https://hub.hku.hk/handle/10722/152386)).

### Controllable deformation need not be a full finite-element simulation

Position-Based Dynamics directly projects positions to satisfy constraints and was
introduced for controllability and robust real-time behavior. XPBD later made
compliance substantially less dependent on time step and solver iteration count.
Those methods are credible candidates for bending, length, attachment, and collision
constraints on selected graph nodes. They do not solve biography or material
reinterpretation; those remain Synesthesia state
([PBD paper](https://diglib.eg.org/items/deb0a7a1-2ddf-496f-889a-fe0df1feeb73),
[XPBD paper](https://matthias-research.github.io/pages/publications/XPBD.pdf)).

The Material Point Method offers a materially different identity model: persistent
Lagrangian samples carry history-dependent material state while a background grid
computes interactions. APIC refines particle-grid transfers for fluid and solid
simulation. This is credible for large deformation and flow, but neither method
supplies Synesthesia's branch lineage, interpretation, or bounded biography by
itself
([original MPM report](https://digital.library.unt.edu/ark:/67531/metadc1385575/m1/1/),
[APIC technical report](https://www.cs.ucr.edu/~craigs/papers/2015-apic/tech-doc.pdf)).

### Camera intention and geometric placement can remain separate

The Virtual Cinematographer separated high-level cinematographic idioms from
lower-level camera-placement modules and ran them in real time. Synesthesia does not
need to copy its shot grammar, but the separation supports keeping curiosity,
attention, dwelling, and revelation decisions above collision avoidance and path
solving ([original paper](https://grail.cs.washington.edu/wp-content/uploads/2015/08/he-1996-tvc.pdf)).

### The graphics platform supports a staged hybrid, with real limits

`QOpenGLWidget` is a stable way to place OpenGL rendering in a Widgets application.
Qt guarantees a current context in `initializeGL()`, `resizeGL()`, and `paintGL()`,
requires a nonzero requested depth buffer for reliable depth testing, warns that the
actual context may differ from the requested one, and requires context-current
resource cleanup. Those requirements fit a true 3D Core proof, but they also require
explicit capability discovery and resource reconstruction
([Qt `QOpenGLWidget` documentation](https://doc.qt.io/qt-6/qopenglwidget.html),
[Qt `QOpenGLContext` documentation](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QOpenGLContext.html)).

OpenGL 4.3 adds compute shaders and shader-storage blocks. The GLSL specification
also states that relative reads and writes by different invocations are largely
unordered unless the program supplies the required synchronization. GPU mutation
is therefore useful for derived simulation, but it is a poor implicit source of
stable biography unless ordering and recovery are designed deliberately
([OpenGL 4.3 core specification](https://registry.khronos.org/OpenGL/specs/gl/glspec43.core.pdf),
[GLSL 4.30 specification](https://registry.khronos.org/OpenGL/specs/gl/GLSLangSpec.4.30.pdf)).

Apple deprecated OpenGL in macOS 10.14 and directs high-performance work to Metal.
Qt's own current RHI example requests only OpenGL 4.1 when OpenGL is selected on
macOS and calls Metal the recommended default. This makes an OpenGL-4.3-only world
incompatible with the project's cross-platform direction
([Apple OpenGL guide](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/OpenGL-MacProgGuide/opengl_pg_concepts/opengl_pg_concepts.html),
[Qt RHI example](https://doc.qt.io/qtforpython-6/examples/example_gui_rhiwindow.html)).

Qt 6.11's `QRhiWidget` provides a `QWidget` render target over Metal, Direct3D 11,
Direct3D 12, Vulkan, or OpenGL. QRhi exposes feature queries for compute, instancing,
and 3D textures; it reports compute unavailable on OpenGL below 4.3 and OpenGL ES
below 3.1. Qt Shader Tools translate Vulkan-style GLSL/SPIR-V into backend-specific
GLSL, HLSL, and Metal source. These are the relevant capabilities for one rendering
Adapter spanning current desktop graphics backends
([`QRhiWidget`](https://doc.qt.io/qt-6/qrhiwidget.html),
[`QRhi`](https://doc.qt.io/qt-6/qrhi.html),
[Qt Shader Tools](https://doc.qt.io/qt-6/qtshadertools-overview.html)).

The limitation is first-party and explicit: `QRhiWidget` is public, but QRhi,
`QShader`, and related classes have no source or binary compatibility guarantee
between Qt minor releases. The repository's installed PySide6 6.11.2 does expose
`QRhiWidget`, `QRhi`, `QRhiBuffer`, and `QRhiComputePipeline`; import success is
local evidence only, not a cross-platform rendering test.

Sparse volume structures are possible later but are not a free foundation. OpenVDB
stores sparse volume values in a hierarchical tree. NanoVDB is a compact linearized
GPU-friendly snapshot, and its own header describes it as read-only by design.
These properties suit large derived volume snapshots better than authoritative,
frequently mutating topology in the first proof
([OpenVDB overview](https://www.openvdb.org/documentation/doxygen/overview.html),
[NanoVDB paper](https://research.nvidia.com/labs/prl/nanovdb/nanovdb2021.pdf),
[NanoVDB source](https://github.com/AcademySoftwareFoundation/openvdb/blob/master/nanovdb/nanovdb/NanoVDB.h)).

Production volumetric systems also support restraint. Frostbite's published design
unifies particles and participating media in bounded volume representations instead
of making every object a volume. This supports using atmosphere as one projection
of the world, not as its identity store
([Frostbite course material](https://www.advances.realtimerendering.com/s2015/index.html)).

## What contemporary audiovisual practice adds

These precedents are systems evidence, not a visual shopping list. Synesthesia
should borrow their constraints and production lessons without copying their look.

- MONOCOLOR's *Latent Space* restricts itself to lines and points, then blends
  displacement, opacity, lighting, particles, and transforms as states of one space
  without fading to black. Its creator describes the system as an instrument whose
  first piece was only one possible performance. That supports one persistent
  grammar rather than a bank of scenes
  ([artist interview](https://derivative.ca/community-post/monocolor-latent-space-and-fulldome-environment/62598)).
- Ubisoft's *Far Cry 6* weather system had to move continuously among arbitrary
  states while wetness, drying, puddles, clouds, fog, rain, lightning, wind,
  vegetation, ocean, and lighting remained coherent. The transferable lesson is a
  small shared physical state with subsystem-specific response times, not a visual
  crossfade
  ([GDC 2022 session](https://www.gdcvault.com/play/1027725)).
- Epic's Substrate work represents layered matter and can simplify its material
  topology for different platforms. Synesthesia needs the same policy at a smaller
  scale: fidelity may simplify the realization of a material relationship, but it
  may not invent another identity
  ([Substrate documentation](https://dev.epicgames.com/documentation/unreal-engine/overview-of-substrate-materials-in-unreal-engine)).
- Marshmallow Laser Feast's *Evolver* follows oxygen through airway,
  cardiovascular tributaries, synapses, forest-like pathways, and a breathing cell.
  Its relevance is the legibility of one branching relation across apparent scales,
  not its imagery
  ([studio project page](https://marshmallowlaserfeast.com/project/evolver/)).
- Brett Bolton's *Phases* combines immediate drum and gesture response with slower
  matter-state organization; Jon Hopkins' tour visuals reserve a very dense particle
  event for a climax. Together they support distinct event, phrase, and narrative
  timescales—and treating density as a rare consequence rather than the default
  ([*Phases* case study](https://www.notch.one/madewithnotch/phases-mutek-montreal-2023/),
  [Jon Hopkins case study](https://www.notch.one/madewithnotch/jon-hopkins-tour-visuals)).
- *Real-Time Samurai Cinema* treats atmosphere, exposure, and darkness as a
  coherent cinematographic system. That supports readable blacks, haze as depth
  separation, and revelation through controlled light instead of permanent bloom
  ([SIGGRAPH 2021 presentation](https://www.advances.realtimerendering.com/s2021/jpatry_advances2021/index.html)).
- Current Cinemachine and Unreal camera systems separate high-level directing,
  shot-quality evaluation, rigs, transitions, and spline following. Synesthesia
  should borrow that separation for semantic attention and continuous geometric
  solving, without importing their shot-preset grammar
  ([Cinemachine 3 overview](https://unity.com/blog/engine-platform/see-whats-new-with-cinemachine-3),
  [Unreal Gameplay Camera System](https://dev.epicgames.com/documentation/en-us/unreal-engine/gameplay-camera-system-overview)).

The shared lesson is restraint through coupling: a few persistent primitives and
causes can generate greater coherence than many individually impressive effects.

## Canonical representation alternatives

The identity representation and the renderer Interface are separate decisions.
Four plausible identity substrates were compared before choosing the graph-first
hybrid.

| Canonical substrate | Principal strength | Failure against the ruling | Proper role |
| --- | --- | --- | --- |
| Embedded branching graph with material coordinates and biography | Explicit connectivity, stable lineage, addressable scars, efficient graph propagation, and deterministic growth | Can collapse into glowing tubes or fail to express soft matter if every projection is a sweep | **Authority for the first proof**, enriched by local material samples and derived fields |
| Persistent Lagrangian material samples plus a transient Eulerian grid | Matter identity survives large deformation; pressure, flow, splitting, and healing share one substrate | Considerably more simulation and sparse-grid machinery; thin branches may fuse or become mushy; exact branch authoring and lineage are harder | Borrow material coordinates and localized field response; reconsider as a later world-kernel deepening |
| Sparse SDF, density field, or volume | Seamless surfaces, collision queries, volumetrics, erosion, and fluid transitions | A scalar cell does not explain which branch it belongs to, why it exists, or how its scar persists; mutation and Core cost are high | Derived local projection for junctions, atmosphere, collision, and high-tier refinement |
| Mesh, framebuffer, particle buffer, or GPU simulation | Direct and often fast to render | Identity depends on tessellation, fidelity, graphics context, and backend; device loss can erase biography | Disposable Adapter state only |

The graph wins because the signature experience is a branching correspondence with
history. The material-field alternative is more general, but that generality is not
free and does not make the first proof more truthful. The hybrid retains the graph's
addressable identity while allowing soft matter and atmosphere to be reconstructed
from it.

## Recommended world model

Everything in this section is a recommendation derived from the evidence and the
artistic constraints. It is not a fact established by the cited systems.

### Identity layer

Use a spatial property graph with two stable entity kinds:

- a **junction** owns a never-reused identity, lineage, rest and current position,
  velocity, accumulated plastic offset, attachment constraints, age, damage, and
  healing state;
- a **branch** owns a never-reused identity, endpoint identities, one or more curve
  controls, rest and current arc length, radius profile, flow and pressure state,
  material coordinates, birth cause, and fracture/scar state.

Stable identities must not be dense GPU array positions. Each projection maintains
an internal identity-to-slot map and may compact or reorder its slots without
changing the world. A branch that is temporarily invisible or summarized at a lower
level of detail remains present in the graph.

Every created entity stores a lineage record: genesis identity or parent branch,
birth time, and the causal event that created it. Deletion should normally become a
tombstone for the rest of the experience, because reusing an identity would make a
later scar or recurrence point at a different thing.

### Biography layer

Biography should be both embodied and bounded:

- **embodied state** stores the lasting result: plastic bend, thickening, healed
  radius, fracture, scar strength, pigment residue, or secondary branch;
- a **causal ledger** stores durable events with event identity, experience time,
  transport epoch, source Musical Event or structural cause, affected topology
  identities, rule parameters, and deterministic seed;
- old high-frequency events compact into per-entity summaries once they can no
  longer be addressed individually.

Do not log every integration step. That would make memory grow with frame count and
mistake replay data for biography. Keep enough causal information to explain and
test durable changes, while current state remains authoritative.

### Interpretation layer

Interpretation must be orthogonal to topology. Each region carries continuous
weights for material families and contextual readings, plus two times:

- **transformation onset**, when material, atmosphere, and behavior begin changing;
- **recognition release**, when the first unambiguous contextual cue may appear.

For example, vascular-to-terrain reinterpretation can dry and roughen the same
branches, widen channels, change surrounding atmosphere, and adjust apparent scale
before a cloud shadow is allowed. The branch identities and correspondence do not
change. A later cosmic reinterpretation can reduce nearby parallax, deepen the
surrounding void, and reveal one spiral point only after the scale transition is
already underway.

This makes “interpretation lags transformation” an explicit timing contract rather
than an accidental shader crossfade.

### Topology-changing causes

Only causal world events may alter connectivity:

- growth creates a junction or branch from an existing lineage;
- division creates related descendants;
- fracture splits a branch but preserves its ancestry;
- healing reconnects or bridges identified descendants;
- erosion may thin or remove matter after a recorded threshold;
- regeneration grows from a scar or dormant site.

Space colonization is a strong starting rule for new branches because it grows a
skeleton incrementally toward a bounded set of attractors. It should be one hidden
rule, not the world representation. Hand-authored guide fields, tropism, collision,
and musical direction can all influence the same growth transaction.

### Pressure and persistent deformation

The first proof does not need a full compressible-fluid solver. A graph-geodesic
pressure event is cheaper, clearer, and tier-invariant:

1. anchor the event to a point on a branch;
2. compute travel distance over connected branches;
3. evaluate a damped wave envelope from distance, propagation speed, and time;
4. feed that response into branch constraints and nearby particles;
5. accumulate plastic deformation or damage only when stress crosses an explicit
   threshold.

Every tier receives the same event, arrival times, and durable result. Full and
Excess may add a local 3D pressure field, denser matter response, and more particles,
but those are richer evidence of the same cause. The graph wave is an artistic
propagation model, not a claim of physically accurate vascular, hydraulic, or
acoustic simulation.

Use XPBD or an equivalently controllable constraint solver only on graph regions
whose motion matters. Sleeping or distant branches can use analytic settling. A
fixed simulation step and fixed constraint parameters prevent rendering frame rate
from becoming world physics.

## Derived representations

### Swept branch geometry

Core should build low-sided swept surfaces along branch curves using
rotation-minimizing frames. A branch's radius, material coordinates, and stable
segment identity travel with that sweep. Overlap or small local junction patches are
acceptable initially if they do not reveal a scene swap.

Advantages:

- ordinary depth testing, perspective, occlusion, shadows, and motion vectors;
- predictable cost based on visible segments and radial tessellation;
- a vertex/fragment path that does not require compute shaders;
- reusable meshes and instance data on integrated hardware.

Risks:

- naive independent tubes crack or bulge at junctions;
- topology changes require local mesh repair;
- translucency and inside-out tunnel views require careful normal, thickness, and
  sorting policy.

### Skeletal implicit field

Define a bounded implicit field from the same branch curves and radii. Use it
locally around junctions, healing, fracture, and high-value transformations rather
than ray marching the entire world at all tiers.

Core may approximate that field with cached mesh patches. Full may ray march bounded
tiles or polygonize only dirty bricks. Excess may retain a larger sparse field. All
three representations evaluate the same topology and material coordinates, so a
representation change is a refinement of the same matter rather than a replacement
scene.

Maintain the distinction between an exact signed distance, a conservative distance
bound, and a generic density or convolution field. Each permits different safe
rendering algorithms.

### Fields and volumes

Use small world- or camera-local fields for atmosphere, pressure visualization,
extinction, and nebular reinterpretation. The field is derived from topology,
events, and interpretation envelopes; it does not decide what exists.

A dense 64-cubed `RGBA16F` field is about 2 MiB before mipmaps; 96 cubed is about
6.75 MiB; 128 cubed is 16 MiB. Double buffering, lighting fields, history, and
multiple cascades multiply those figures. These calculations explain why Core
needs a small field or a 2D slice/atlas fallback and why Excess can spend much more.
They are budget examples, not measured requirements.

### Particles

Give particle emissions stable event seeds and particle ordinal identities. A tier
selects a deterministic prefix or stable-hash subset, so changing density never
reshuffles the surviving motes. Essential “hero” particles may be CPU advanced;
additional particles may live entirely in GPU caches.

Particles can reveal flow, pressure arrival, scale, and atmosphere. They must not be
the only record that a pressure wave or fracture occurred, because a lower tier may
not instantiate most of them and a graphics-device loss may erase GPU state.

## Simulation and GPU data flow

Keep the authoritative graph, causal ledger, fixed-step clock, interpretation
envelopes, and camera plan on the CPU. Pack derived GPU data as structure-of-arrays:

- dense junction and branch slots;
- curve controls and radius profiles;
- current and previous transforms;
- interpretation/material weights;
- stable identity hashes for temporal correspondence;
- dirty ranges and topology revisions.

The renderer may use vertex buffers and instancing on Core, then storage buffers and
compute on capable Full or Excess hardware. GPU slots may be reordered. The mapping
back to stable world identities belongs inside the rendering Adapter.

Do not read simulation buffers back every frame. The CPU world must be able to
rebuild all essential GPU resources after context recreation or device loss. GPU
state may accelerate secondary deformation, particles, field construction,
culling, and indirect draws, but any result that changes biography must return as a
deliberate, bounded event or remain CPU authoritative.

Run world simulation on one worker with immutable frame publication to the GUI
thread. The renderer consumes the newest complete frame and its dirty ranges. It may
drop intermediate visual frames, but it must never discard or reorder discrete
world events. Continuous forces may be coalesced over a bounded interval.

## Autonomous camera

The camera should read the authoritative topology and its spatial index, not visible
render instances. Otherwise fewer Core branches would change collision, attention,
or choreography.

Split its hidden implementation into two levels:

- an intention planner chooses **Dwell**, **Inspect**, **Traverse**, **Follow
  propagation**, **Withdraw**, or **Reveal scale** from director attention,
  interpretation timing, recurrence, and climax;
- a geometric planner chooses a collision-free pose and path, checks visibility of
  the subject, controls lens and focus distance, and limits acceleration and angular
  velocity.

The camera pose is part of the world frame shared by every rendering Adapter. Depth
of field, motion blur, and volumetric sampling quality may vary by tier; camera
decisions may not.

Stillness is an explicit camera state, not zero input to a constantly wandering
camera. A revelation should have a refractory interval so repeated energy peaks do
not create perpetual pull-backs.

## Fidelity contract

The tier is selected below `WorldDirector`. The director emits the same World
Conditions and causal events regardless of hardware.

| Concern | Core World | Full World | Excess |
| --- | --- | --- | --- |
| Authoritative graph and biography | Complete | Same | Same |
| Pressure event and durable deformation | Complete graph event | Same event plus local field response | Same event plus denser secondary simulation |
| Camera plan | Identical | Identical | Identical |
| Solid matter | Low-sided swept mesh and cached junction patches | Denser mesh plus local implicit transitions | Dense/local sparse implicit refinement and secondary branches |
| Particles | Deterministic sparse subset | Larger stable subset with GPU dynamics | Very dense stable population and more species |
| Atmosphere | Analytic fog or small field | Bounded froxel/3D fields | Larger/cascaded or sparse volumes |
| Lighting | Few lights, short/simple shadows | Better shadows and translucency | Scattering, reflections, refraction, longer histories |
| Resolution | Dynamic internal scale allowed | Higher target | Highest target |

Counts and resolutions must be budgets, not artistic branches in control flow. Use
capability queries first, then a measured frame-time governor with hysteresis. A
quality transition may reduce tessellation, particle subset, ray steps, shadow
distance, volume dimensions, and internal resolution. It may not reset GPU caches
in a way that pops, mutate topology, reschedule an event, or ask the director for a
different decision.

A proposed Core acceptance target is sustained 30 frames per second at a 1280 by
720 internal render size on the named minimum integrated GPU, with 60 frames per
second preferred where available. This is a recommendation only. No minimum GPU has
been named and no prototype has been measured, so current evidence cannot establish
that target as feasible.

## Deep Module candidate

### Design it twice: Interface alternatives

This comparison is only about the public **Interface** and state ownership. It does
not choose among swept meshes, implicit fields, volumes, or particles; those are
representation choices hidden behind the rendering **Seam**.

Four materially different designs were considered:

1. **Deep stateful session facade**: `PersistentWorld.create(genesis)` returns the
   sole owner of biography, and `advance(request)` atomically returns an immutable
   frame. The caller owns lifecycle and ordered requests, but not simulation phases,
   storage layout, or rendering projections.
2. **Event-log and reducer pipeline**: a pure
   `reduce(previous_state, ordered_causes) -> (next_state, frame)` exposes state and
   makes the caller own log retention, transport epochs, checkpoint policy, and
   publication. Replay is natural, but ordinary seeking must still advance the
   existing state rather than restore historical state under ADR-0043.
3. **Renderer-query or ECS surface**: generic `spawn`, `update`, and `query`
   operations expose topology and biography as components. Systems and renderers can
   consume cache-friendly arrays directly, but callers must coordinate system order,
   component validity, identity, and topology transactions.
4. **Pure time projection**: `project(score, musical_time, seed) -> frame` derives a
   world independently for any requested time. Random access and golden tests are
   simple, but path-dependent damage, healing, and seek-preserved World Memory either
   disappear or require a hidden history that turns this back into design 1 or 2.

| Interface design | Caller burden | Invariant ownership | Performance shape | Testing | Evolution cost |
| --- | --- | --- | --- | --- | --- |
| Stateful facade | Low: create once, submit ordered causes, render returned frame | Centralized in one Module and one atomic `advance` | Incremental fixed ticks, dirty regions, bounded publication | Deterministic semantic traces plus a headless Adapter; checkpoints stay test/export tools | Low outside the Seam because storage and phase changes remain hidden |
| Reducer and event log | High: retain state/log, order batches, manage epochs and recovery | Reducer can validate transitions, but lifecycle and publication invariants leak to its caller | Pure batching can parallelize; state copies, log growth, and checkpoint policy add cost | Excellent replay and property-test ergonomics | Event and state schema migrations become public obligations |
| Renderer-query/ECS | High: schedule systems and form consistent queries | Distributed across components, systems, and query discipline | Potentially excellent cache locality and parallel iteration | Individual systems are easy to isolate; cross-system biography and atomic topology changes are harder | Component layout and sequencing leak through every consumer |
| Pure time projection | Initially minimal | Determinism is simple; accumulated biography has no natural owner | Recompute or cache from an origin for every random access | Excellent stateless golden tests, poor causal-history tests | Each new path-dependent law pressures the signature or invents hidden state |

The stateful facade wins because it gives the biography one owner and makes the
ordinary seek rule an invariant instead of a convention shared by several callers.
It also has the greatest **Depth**: two operations hide causal ordering, topology
transactions, simulation, camera planning, projection invalidation, and recovery.
The reducer remains a useful hidden implementation technique, and structure-of-arrays
or ECS-like storage remains a useful hidden data model, but neither earns a public
**Seam**. The pure projection is rejected because the defining requirement is a
world that remembers what happened to it.

### Module and Seam

The proposed **Module** is `PersistentWorld`. Its external **Seam** sits between
`WorldDirector` and all graphical **Adapters**. `WorldDirector` continues to turn a
`WorldMoment`, artist controls, and narrative World Memory into typed World
Conditions. `PersistentWorld` turns those causes into persistent spatial matter,
biography, and a camera-authored world frame.

`PersistentWorld` is an in-process dependency. Its simulation has no I/O and needs
no external Adapter for tests. A second, package-internal rendering Seam is real
because at least two **Adapters** are justified:

- `QrhiWorldAdapter` presents production frames through `QRhiWidget`;
- `HeadlessWorldAdapter` verifies geometry summaries, identity, events, and camera
  without a GPU;
- a direct `QOpenGLWidget` Adapter is only a contingency if the QRhi/PySide spike
  fails, not a reason to expose OpenGL concepts through the Module's Interface.

### Interface

The `PersistentWorld` **Interface** has two entry points:

```python
class PersistentWorld:
    @classmethod
    def create(cls, genesis: WorldGenesis) -> PersistentWorld: ...

    def advance(self, request: WorldAdvance) -> WorldFrame: ...
```

Proposed immutable values at the Interface:

```python
@dataclass(frozen=True, slots=True)
class WorldGenesis:
    experience_seed: int
    authoritative_limits: WorldLimits


@dataclass(frozen=True, slots=True)
class WorldAdvance:
    experience_time: float
    musical_time: float
    transport_state: TransportState
    transport_epoch: int
    viewport_aspect: float
    conditions: WorldConditions


@dataclass(frozen=True, slots=True)
class WorldFrame:
    revision: int
    camera: CameraFrame
    diagnostics: tuple[WorldDiagnostic, ...]
    _render_state: object
```

`WorldConditions` should deepen from today's scalar shader-uniform bundle into a
typed cause value containing continuous forces, idempotent discrete events,
interpretation envelopes, and attention. It must not contain a fidelity tier,
particle count, shader choice, mesh density, or volume resolution.

`WorldLimits` is an authoritative product/session budget measured against the
minimum supported platform and is identical for every fidelity tier. It is not a
GPU capability report. Genesis creates the one branching world internally; exposing
an `InitialWorldForm` enum would invite the scene-selection architecture this design
is meant to remove.

`WorldFrame._render_state` is opaque outside `GUI/synesthesia`. Application callers
may inspect revision, camera, and diagnostics, but they pass the frame unchanged to
a rendering Adapter. Keeping mesh buffers, graph arrays, SDF bricks, and spatial
indices out of the Interface preserves **Depth**.

### Interface invariants

1. `experience_time` is finite and monotonic. `musical_time` may jump only with a
   new transport epoch because a seek changes musical cause without rewinding world
   biography. `transport_state` explicitly distinguishes playback, pause, and end.
2. A discrete event identity is idempotent within one transport epoch. Explicit
   seek, loop wrap, or restart creates a new epoch; decoder jitter does not. Repeating
   the same identity and payload has no effect; repeating it with another payload
   is an error. Re-crossing the same Musical Event after a seek creates a new world
   event identity in a new transport epoch while retaining the same musical cause.
3. Topology identities are never reused in one `PersistentWorld` lifetime.
4. Material and interpretation changes never change a topology identity.
5. Connectivity changes occur only through validated causal events and increment a
   monotonic topology revision.
6. The authoritative state and camera are independent of rendering Adapter and
   fidelity tier.
7. The same genesis and ordered advances produce the same semantic event trace and
   camera plan within a documented CPU floating-point tolerance. Pixel identity
   across graphics backends is not promised.
8. A `WorldFrame` is immutable. Publication never exposes a partially applied
   topology transaction.
9. World state remains runtime-only. `PersistentWorld` does not create a Track cache
   or persist Track-derived data.
10. Paused transport advances neither the fixed World tick nor camera and
    interpretation time. In-Track silence is different: the Track and World keep
    moving under restrained conditions.

### Ordering

One owner calls `advance` sequentially. The Module internally accumulates elapsed
time and performs bounded fixed ticks in this order:

1. validate and deduplicate scheduled events;
2. apply due growth, fracture, healing, and regeneration transactions;
3. advance continuous forces and constrained deformation;
4. propagate pressure and accumulate thresholded damage or plastic change;
5. advance interpretation envelopes and release due recognition cues;
6. update dirty spatial-index regions and projection revisions;
7. advance camera intention and geometric placement;
8. publish one immutable `WorldFrame`.

If the caller falls behind, the Module limits catch-up work and reports lag. It may
coalesce continuous conditions, but it must retain ordered discrete events. Seeking
increments the transport epoch, re-anchors future causes, and does not call `create`,
rewind biography, rebuild the world, or synthesize events skipped by a forward
seek. Beginning a new experience calls `create`.
Optional checkpoints may support deterministic QA, frame export, or recovery from a
failed process; ordinary transport seeking must not restore one.

`experience_time` measures the monotonic host experience, `musical_time` locates
Musical Evidence, and the internal fixed World tick records biography. On resume,
the paused host interval is not treated as simulation debt. A renderer may maintain
a fourth, presentation-only clock for dithering or exposure, but it cannot mutate
World Memory from it.

### Errors and degradation

- `InvalidWorldAdvance`: non-finite time, invalid aspect, malformed condition, or an
  event targeting an identity that cannot legally receive it;
- `ExperienceTimeRegression`: the monotonic host-experience clock moved backward;
- `UnclassifiedTransportJump`: musical time jumped without a new transport epoch;
- `ConflictingWorldEvent`: an event identity was reused with different content;
- `WorldLimitReached`: returned as a diagnostic when a growth request must be
  deferred, summarized, or rejected without corrupting existing topology;
- `SimulationLag`: returned as a diagnostic when bounded catch-up cannot reach the
  requested time this frame.

Rendering failures do not mutate `PersistentWorld`. An Adapter separately reports
unsupported Core capability, shader/pipeline failure, out-of-budget allocation, or
graphics-device loss. Device loss discards derived caches and rebuilds from the next
complete `WorldFrame`.

### Performance characteristics

- CPU work is bounded by explicit active-junction, active-branch, event, solver, and
  spatial-query limits in `WorldLimits`.
- Topology changes rebuild only affected graph regions and projection ranges.
- Ordinary frames publish structural sharing plus dirty revisions rather than deep
  copies of the full graph.
- Camera collision and attention queries use a CPU spatial index over authoritative
  branch bounds.
- The GUI thread performs bounded uploads and rendering; it does not run growth,
  shortest-path propagation, or whole-graph constraint solving.
- No normal frame requires GPU readback.

The exact limits remain prototype results, not Interface defaults to invent in this
research note.

### Usage example

```python
world = PersistentWorld.create(
    WorldGenesis(
        experience_seed=experience_seed,
        authoritative_limits=measured_world_limits,
    )
)

conditions = director.direct(
    score=score,
    previous_transport=previous_transport,
    transport=transport,
)
frame = world.advance(
    WorldAdvance(
        experience_time=experience_clock,
        musical_time=musical_time,
        transport_state=transport.state,
        transport_epoch=transport_epoch,
        viewport_aspect=width / height,
        conditions=conditions,
    )
)
renderer.present(frame)
```

The example is illustrative. The experience seed is created once for the runtime
World; the accepted names and exact owner of transport classification must be
settled before implementation.

### Hidden implementation, Depth, Leverage, and Locality

The Module hides graph allocation, identity-to-slot maps, lineage, bounded causal
compaction, growth algorithms, topology transactions, graph propagation, constraint
solving, fixed-tick accumulation, interpretation timing, spatial indexing, camera
planning, immutable frame publication, and dirty projection tracking.

That **Depth** gives `WorldDirector` one operation worth of **Leverage**: it can cause
growth, pressure, damage, reinterpretation, recurrence, and camera attention without
knowing how any of them are simulated or drawn. Rendering Adapters gain the same
Leverage from one world frame and cannot accidentally create a parallel universe.

The design gives maintainers **Locality**: identity and biography bugs concentrate
in `PersistentWorld`; graphics-backend and fidelity bugs concentrate in rendering
Adapters; musical inference remains behind `WorldScore`; artistic mapping remains
in `WorldDirector`. Replacing OpenGL with QRhi, or QRhi with another backend, cannot
change topology semantics unless the `PersistentWorld` Interface is deliberately
changed.

The deletion test supports the Module: deleting it would force stable identity,
event ordering, growth, damage, interpretation lag, camera planning, and tier parity
back into the director and every renderer. It is therefore not a pass-through.

## Rendering alternatives in 2026

| Direction | What it protects | Principal weakness | Recommendation |
| --- | --- | --- | --- |
| `QOpenGLWidget`, OpenGL 3.3 Core | Smallest step from current code; true perspective, depth, mesh, instancing, texture fields | macOS OpenGL is deprecated; no Core compute/SSBO; investing in GL 4.3 creates a platform split | Keep only as a contingency if the QRhi spike fails; do not build a parallel Core implementation or make it the high-fidelity ceiling |
| `QRhiWidget` and QRhi | One Widgets-native Adapter over Metal, D3D, Vulkan, and OpenGL; capability-gated compute and 3D resources; packaged cross-language shaders | QRhi has limited minor-version compatibility; advanced cross-backend shaders need real validation | Preferred production direction after a short multi-platform spike |
| `wgpu-py` plus `rendercanvas.qt` | Modern storage/compute model over Windows, Linux, and macOS; Qt embedding exists | The project states its Interface may still change with WebGPU; adds a second presentation stack and native dependency family | Best contingency if QRhi's Python surface blocks required passes, not the first choice |
| Qt Quick 3D | Ready-made scene, camera, materials, instancing, particles, and custom geometry | Morph targets require fixed mesh topology; dynamic procedural topology and custom simulation would fight a higher-level scene model; the app is Widgets-based | Useful for conventional 3D assets, not recommended as the world's authority or primary renderer |
| Raw Vulkan + Metal + Direct3D | Maximum backend control | Three deep native implementations, shader/tooling duplication, and high Python integration cost | Reject for the proof and foreseeable production scope |
| OpenVDB/NanoVDB foundation | Excellent sparse derived volumes at high fidelity | Native dependency and mostly snapshot-oriented GPU data; does not solve entity biography, camera, or mesh baseline | Revisit for Excess volumetrics only after the world proof |

The wgpu-py project reports Windows, Linux, Intel macOS, and Apple-silicon support,
Qt embedding, and coverage sufficient for its `pygfx` renderer, but also warns that
its Interface may change while WebGPU settles
([official repository](https://github.com/pygfx/wgpu-py)). Qt Quick 3D's own
documentation states that morph targets preserve the base mesh's triangle structure,
which is a mismatch for growth and fracture as identity-level events
([Qt morphing documentation](https://doc.qt.io/qt-6/quick3d-morphing.html)).

## Recommended implementation sequence

### 1. Prove identity without graphics

Build `PersistentWorld` and the headless Adapter around a small branching tunnel.
Tests should prove:

- stable identities survive tissue-to-botanical-to-terrain-to-cosmic
  reinterpretation;
- one growth event creates traceable lineage;
- one pressure event has ordered arrivals and leaves a lasting bend or scar;
- seek increments a transport epoch and changes future causes without replacing or
  rewinding the world, while a later re-crossing can cause the Musical Event again;
- the same ordered input produces the same semantic trace and camera plan;
- event-ledger compaction retains durable biography while memory stays bounded.

### 2. Run a rendering-backend spike

Before building rich materials, render the same static and deforming frame through
`QRhiWidget` on Windows/Direct3D 11, macOS/Metal, and Linux/OpenGL or Vulkan. Verify:

- PySide packaging and `.qsb` shader generation;
- depth, floating-point targets, instancing, 3D textures, storage buffers, and
  compute feature reporting;
- device/context reconstruction;
- dynamic buffer updates without GUI stalls;
- GPU timing and diagnostic capture.

Keep the shader subset to vertex and fragment stages for Core. Geometry shaders are
experimental in QRhi and absent on Metal; compute stays an optional capability.

### 3. Prove the Core World

Render a navigable, low-sided swept tunnel with perspective, depth, occlusion, a
modest stable particle subset, simple atmosphere, and the autonomous camera. It must
remain spatial and causally alive with compute disabled. If this fails on the named
minimum integrated GPU, simplify representation rather than fall back to the old 2D
visualizer.

### 4. Prove reinterpretation before density

On unchanged topology, perform one slow vascular-to-botanical-to-terrain transition
whose recognition cue is delayed. Add the cosmic point only after the scale has
already become ambiguous. Inspect motion, correspondence, silhouettes, material
coordinates, and camera continuity; a still image is not sufficient evidence.

### 5. Prove local topology and representation change

Grow one secondary branch, propagate one pressure wave, fracture or bend one
identified region, and retain the result through later interpretations. Add a local
implicit junction or transition patch derived from the same graph. Switching that
patch on and off must not visibly replace the matter.

### 6. Enrich, then compare tiers

Add Full and Excess fields, particles, lighting, and secondary simulation. Capture
the same deterministic input trace at every tier and compare:

- identical topology revision and event ledger;
- identical durable deformation and interpretation schedule;
- identical camera poses within tolerance;
- no tier-specific cut or motif replacement;
- only density, precision, lighting, atmosphere, and secondary response differ.

Do not rebuild the twelve-motif path until the single proof passes these checks.

## Unknowns and required measurements

The following remain explicitly uncertain:

- No minimum integrated GPU, operating-system floor, resolution, frame rate, or
  memory budget has been named. “Viable integrated GPU” is not yet a testable
  requirement.
- No cross-platform QRhi/PySide prototype has been run. Documentation and local
  importability do not establish shader correctness, packaging, driver behavior, or
  adequate performance.
- The cost of Python-to-GPU updates for the proposed graph sizes is unknown. NumPy
  packing and dirty-range uploads may be sufficient; a compiled helper may be
  required later.
- The best junction method is unresolved. Overlapping sweeps, cached convolution
  patches, local field polygonization, and bounded ray marching must be compared in
  motion.
- The amount of branch deformation that can remain CPU authoritative at Core frame
  rates is unmeasured.
- Cross-backend pixel equivalence is neither expected nor required. Semantic trace,
  camera, causal ordering, and persistent topology are the portable contract.
- Dense volumetrics can consume memory and fill rate rapidly. The example field
  sizes above are arithmetic, not a performance result.
- Apparent-scale transitions may expose floating-point precision, clipping, and
  depth-buffer problems. A floating origin or scale-local coordinate frames may be
  necessary, but the first proof should measure before choosing one.
- Current World Memory ownership in ADR-0043 is too narrow for embodied biography.
  The exact split between the director's narrative memory and the world's physical
  memory requires a recorded decision.

## Decision recommendation

Accept the stable graph plus derived hybrid representation as the architecture to
prototype. Preserve `WorldScore`. Deepen World Conditions from shader controls into
typed continuous causes, discrete causal events, interpretation timing, and camera
attention. Put authoritative topology, biography, propagation, and camera planning
in the `PersistentWorld` Module. Put every graphics detail and quality budget behind
the rendering Seam.

Validate `QRhiWidget` as the production Adapter now, while retaining the existing
OpenGL work only as a disposable Core proof or compatibility Adapter. Do not build
identity-critical state in framebuffer feedback, a mesh topology, a voxel grid, a
particle buffer, or a GPU-only simulation.

This recommendation most directly protects the four artistic invariants:

- **identity beneath appearance**: stable graph identities outlive every projection;
- **history beneath transformation**: embodied state and bounded causes form a
  biography;
- **ambiguity before recognition**: transformation onset and recognition release
  are separate times;
- **restraint before revelation**: density, cues, camera scale, and atmosphere are
  scheduled evidence, not a permanently maximal shader.
