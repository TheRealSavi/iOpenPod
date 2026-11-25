# ADR-0298: Share interruptible presentation motion

- Status: Accepted
- Date: 2026-11-24
- Extends: ADR-0072 and ADR-0244

## Context and evidence

The GUI mixed symmetric cubic selectors, a visibly overshooting popup, and
independently timed fades. Restarting their curves preserved position but discarded
velocity. Some controls also ignored the Host's widget-animation preference.

Independent practitioner work converges on responsiveness, continuity, restraint,
and context-dependent timing. This is a design synthesis, not a measured universal
Apple curve or a claim of formal community consensus:

- Nathan Gitter's [Building Fluid Interfaces](https://medium.com/@nathangitter/building-fluid-interfaces-ios-swift-9732bb934bf5)
  implements and analyzes iPhone interactions, including redirectable springs.
- Emil Kowalski's [7 Practical Animation Tips](https://emilkowal.ski/ui/7-practical-animation-tips)
  compares curves with identical durations and demonstrates the importance of early
  response. [You Don't Need Animations](https://emilkowal.ski/ui/you-dont-need-animations)
  emphasizes frequency of use and purposeful motion.
- Josh Comeau's [spring analysis](https://www.joshwcomeau.com/animation/a-friendly-introduction-to-spring-physics/),
  updated in November 2025, distinguishes natural settling from visible bouncing
  and recommends using springs primarily for movement rather than opacity.

Apple's [Animate with springs](https://developer.apple.com/videos/play/wwdc2023/10158/)
corroborates continuity and non-bouncy springs. Current
[Qt animation documentation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QVariantAnimation.html)
supports custom interpolation on the existing animation clock. The independent
sources were revisited on 2026-11-24; their older publication dates do not imply
new measurements of current Apple software.

## Decision

Keep the existing Widgets implementation and introduce one presentation-owned
motion module, with no dependency change. Spatial controls and panels use the
closed-form critically damped spring. Retargeting retains position and velocity;
explicit cancellation starts the next transition from rest. Qt owns scheduling
and lifetime. No per-widget timers or numerical integration are needed.

`MOTION` defines iOpenPod's own tunings: 240 ms control settling, 280 ms expansions,
320 ms panel entrances, and 220 ms dismissals. These are maximum settling budgets,
not a delay before responding. Ten time constants leave less than 0.05% of initial
travel before exact final-value snapping for a spring starting from rest. Normal
entrances do not overshoot; interruption can briefly continue the existing motion
before reversing. Fades use `(0.2, 0, 0, 1)` over 180 ms, 120 ms for dismissal, and
240 ms for Now Playing artwork. Settings illustrations retain their deliberate
450 ms symmetric cubic crossfade and 300 ms appearance/disappearance curves.
Calendar page snapshots retain their bounded 280 ms transition.

Navigation and selection commit immediately. Existing snapshot transitions remain
bounded to their viewport and restart from the current composition. They do not
claim spring velocity continuity across replacement images. Trackpad input remains
direct; discrete wheel steps retain ADR-0244's bounded 140 ms easing and row policy.
Disabled Host widget animation applies immediately, including those wheel steps.

Audio mute ramps, playback meters, Synesthesia choreography, and the continuous
Now Playing artwork field have different timing semantics and retain their existing
behavior. Focus and ordinary button press feedback remain immediate.

## Consequences

A shared spring has more code than swapping easing enums, but makes rapid reversal
continuous rather than merely cosmetic. Tests cover finite-frame continuity,
endpoint settling, cancellation, native property binding, rendered transitions,
and disabled-motion behavior. All changes remain inside presentation; no device,
Library, transport, or persistence workflow gains new authority.
