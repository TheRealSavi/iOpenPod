# Synesthesia Visual Direction

Synesthesia is a living visual instrument in the lineage of classic music
visualizers, rebuilt around modern analysis and GPU simulation. It is not a
wallpaper, a slideshow of generated images, or a random preset shuffle. Musical
evidence directs a varied sequence of procedural visual Scenes.

## The governing idea

Think **visual instrument**, not wallpaper.

The renderer owns several strong compositional grammars: gravitational particle
systems, fluid ribbons, tunnels, mirrored waveforms, prismatic sheets, perspective
lattices, solar bodies, sparse star fields, contour maps, crystal shards, braided
currents, and falling signals. Each Scene must have a recognizable silhouette,
spatial logic, and motion language before color is considered.

Shared particles, comets, filaments, waves, and retained light remain reusable
materials. A Scene decides which are visible and how strongly, rather than stacking
all of them over every frame. The renderer must not reduce different evidence to a
global pulse and hue shift.

The result may suggest roots, veins, neurons, storms, plasma, deep water, nebulae,
or galaxies. Scene names describe implementation grammars, not literal narrative
claims. Several readings should often remain plausible at once.

## Scene library

The production library contains twelve Scenes:

- Magnetosphere: sparse gravitational nuclei, orbital populations, and starbursts;
- Ribbon Cascade: layered fluid ribbons with travelling charge;
- Warp Tunnel: accelerating spokes, rings, and radial streaks;
- Mirror Wave: bilateral and kaleidoscopic waveform contours;
- Prismatic Veil: folding sheets and broad color atmosphere;
- Lattice Cathedral: perspective grids, arches, and vanishing points;
- Solar Bloom: a hot radial body with corona, petals, and flares;
- Star Chamber: parallax stars, deep black space, and slow nebular structure;
- Contour Drift: asymmetric contour islands and channels sliding across depth layers;
- Crystal Shoal: tumbling angular shards with translucent facets and travelling glints;
- Braided Current: paired ropes of light with interwoven strands and moving charge; and
- Signal Rain: staggered columns of falling, segmented light at several depths.

These Scenes are procedural and parameterized, not authored videos or fixed asset
sequences. Their order comes from local Musical Evidence and deterministic diversity
policy. Scene changes use a short crossfade and deliberate feedback erosion instead
of a hard cut or a permanently smeared dissolve.

Scene changes follow analyzed Section boundaries with a two-second minimum hold.
The director groups shorter Sections and avoids a closing Scene shorter than two
seconds. Long Sections retain bounded subspans of at most 22 seconds, without moving
eligible Section edits. There is no preferred residence duration. Tracks shorter
than two seconds use one Scene. Analysis retains every Section; live Field Forcing
and musical accents continue inside each residence. See
[ADR-0077](adr/0077-hold-synesthesia-scenes-across-short-sections.md).

The director keeps at least six alternatives ranked by local Mood Signature before
applying diversity rules. The previous narrow score gate could leave only two
eligible Scenes, making usage penalties ineffective. The three most recent Scenes
now sit out; Solar Bloom sits out for five residences. Magnetosphere, Warp Tunnel,
and Solar Bloom cannot follow one another directly, giving radial compositions a
non-radial interval. Cumulative use reduces a Scene's rank within the candidate
pool. The order remains deterministic and evidence-weighted, including after seeks.

The additions offer alternatives across musical moods: quiet textured passages
favor contours, bright noisy passages favor shards, harmonic bass supports braided
currents, and bright percussion supports signal rain. Their shared field overlays
are restrained so their own geometry remains legible.

The acceptance review is a five-minute watch. It fails if the silhouette remains
constant, if Scene changes feel periodic rather than musical, if every event merely
changes brightness, if every system is visible at once, or if color is the main
difference between Scenes.

## Choreography and camera

A Scene is not a static composition with animated decoration. Every Scene residence
has a stable directional world journey expressed as travel, orbit, depth velocity,
waveform deformation, parallax, and world scale. Those continuous values come from
the Scene's motion grammar, its local Mood Signature, and a deterministic Track
identity. They do not double as camera instructions.

Travel, rotation, depth flow, musical wave phases, filament charges, and laser
sweeps accumulate from current rates over elapsed field time. A changing rate must
never multiply the entire elapsed playback time: that would reposition geometry
and cause increasingly violent reversals as a Track progresses. These live phases
freeze on pause, survive seeks and the analysis handoff, and restart with a new
Track alongside the field.

Each residence is also edited as one to four bounded Camera Shots. The shot
vocabulary is establishing, track, orbit, inspection, fly-through, and reveal. A
shot chooses a real position, subject target, roll, lens, and smooth path. Its
boundary may move slightly to trustworthy musical punctuation, but the lens does
not pump on every beat and the camera does not shake merely to prove it is alive.
Long passages should contain compositional landings where motion slows enough to
let the viewer inspect the place.

Magnetosphere can establish the whole cluster, orbit a nucleus, inspect a pole, and
pull back to reveal scale. Ribbons track along and pass between sheets. The tunnel
aligns with and crosses its throat. Mirrored contours are inspected laterally before
an axial reveal. Veils permit a dolly through a gap. The cathedral traverses an aisle
and cranes upward. The solar camera skims a limb. The star chamber approaches near
stars and a dust horizon. Contours use lateral survey and inspection; shards permit
an oblique fly-through; braids track along their length; rain descends between
columns before a wide reveal. The dominant procedural Scene reconstructs the same
camera ray as the Coupled Field and samples target-focused camera-facing slices at
relative depth offsets, so viewpoint changes produce perspective and parallax
instead of moving only the overlays. Feedback follows world travel and erodes
during camera movement so retained light describes a journey without preserving
the previous framing indefinitely.

Scene geometry bends around a musical deformation curve assembled from current
energy, spectrum, harmonic and percussive layers, rhythmic pulse, beat phase, flux,
and accepted onset strength. This is an evidence-shaped visual wave, not a literal
raw-PCM oscilloscope trace. Movement must remain directional when the music holds a
steady state, then change speed, curvature, or displacement as Musical Evidence
changes.

## Musical causality

Each input has one testable visual or physical role. The renderer must preserve
enough independence that two moments with similar loudness but different musical
content do not collapse to the same image:

- Activity injects kinetic energy into the shared flow. Quiet does not stop the
  field; it exposes momentum, settling, leakage, and slow organization.
- Low-frequency mass deepens attractor wells and moves broad quantities of matter.
  It must come from calibrated audible low-band power, not from a band's independent
  position in the Track.
- Impact events launch pressure waves from places in the domain and retain their
  event character. Every wave pushes shared matter, while admitted onsets add radial
  fragments, downbeats and rare strong rhythmic accents cut laser lines through the
  field, Section boundaries open chromatic rifts, and Source entrances bloom into
  rotating flares. Dense onset clusters are edited into a bounded number of salient
  bursts. These are transient consequences of evidence, not a timed effect playlist.
- Fine excitation injects charge and seeds short-lived dangerous detail. It can
  increase filament activity without turning the entire frame uniformly brighter.
- Harmonic coherence changes how strongly local matter organizes and aligns. Low
  coherence may dissolve order; unavailable evidence remains neutral rather than
  pretending to be chaos.
- Chroma and Section identity establish a slowly changing palette anchor. Spectral
  brightness and tonal focus determine its luminance and spread; color does not
  come from elapsed time alone.
- Spectrum and timbre control scale and texture. Low registers move broad mass,
  high-band flux creates fine dangerous detail, and noise roughens motion without
  becoming a full-frame brightness pulse.
- Stereo pan and width shift and spread the active field. Mono or unreliable stereo
  evidence stays centered rather than inventing movement.
- Harmonic, percussive, vocal, drum, and bass Sources modulate behaviors already in
  the shared field. Their entrances may excite a distinct field phenomenon, but
  they never select literal instrument animations or create an independent scene.
- Section progress and novelty change organization and retention gradually. A
  Section boundary sends a pressure cause through the current Scene and provides a
  natural transition opportunity.

The analysis layer measures those inputs and reports reliability. The Field
Conductor owns response time, thresholds, and mapping to force. The Scene Director
owns mood scoring, Scene residence, diversity, and transitions. The renderer owns
neither musical interpretation nor a clock-driven preset schedule.

## Motion language

Particles reveal trajectories: orbit, shear, capture, escape, turbulence, and wave
fronts. There should be enough of them to read a force field rather than a handful
of sprites.

Visible particle density builds gradually with musical activity. Stable particle
identities fade into view as activity rises, giving quiet and moderate passages
space without restarting the simulation. Comet trails remain restrained until
higher activity; strong peaks retain the fuller population and trail intensity.

Smoke is moving matter, not a translucent image layer. It follows the same flow as
the particles, accumulates around wells, stretches under shear, and parts around
pressure fronts.

Waves are a primary language. Their motion should remain legible as propagation and
interference even when their visible form changes. They alter the field rather than
being drawn over it.

Electricity is beautiful and dangerous. Filaments search through charge and
organization, fork, reconnect, fade, and leave a brief trace. They do not appear as
an unrelated lightning preset.

Recursive growth is a slow bias in the field. It should build branching ridges and
conductive paths that remain partially visible as flow and pressure disturb them.
This supplies continuity without freezing the image into a literal object.

Temporal feedback retains light carefully. Previous frames may be warped by the
current velocity, attenuated, and recombined, but feedback is not the simulation and
must not smear the image into featureless fog.

## Composition

Black space matters. Bright structure needs room to appear and disappear. Bloom is
reserved for concentrated energy; it does not wash every particle into the same
soft glow. Color follows field relationships and musical evidence, with controlled
complementary tension rather than a full-spectrum gradient applied everywhere.

Depth must be readable through parallax, occlusion, particle scale, focus, density,
and the way waves pass through matter. Camera motion must reveal a large spatial
volume without becoming arbitrary or nauseating: travel has a stable heading,
turning is bounded, and speed belongs to the current Scene and music. A pause or
seek samples the same deterministic Camera Shot rather than replaying a camera
animation from the beginning. A seek keeps the living field but discards retained
screen history from the previous viewpoint.

The procedural Scene is the composition, not a decorative background. Shared field
projections must support its silhouette. Multiple render passes are expected, but a
Scene may suppress most of them to preserve contrast and identity.

## Deliberate limits

Do not draw every note, claim instruments without learned Source evidence, or claim
knowledge of emotion, lyrics, genre, or compositional intent. `MoodSignature` is a
presentation-owned control vector, not an emotion classifier. Do not create literal
animals, landscapes, organs, or scripted stories.

Spend ambition on graphic structure and interaction: a ribbon canopy collapsing
into a tunnel, a quiet star chamber accumulating gravitational nuclei, a mirrored
wave cracking open under a downbeat laser, or a solar corona throwing comets into
the next Scene. Scene variety must amplify musical causality rather than replace it.
