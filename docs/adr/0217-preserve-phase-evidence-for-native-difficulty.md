# ADR-0217: Preserve Phase evidence for native difficulty

- Status: Accepted
- Date: 2026-10-31
- Supersedes: ADR-0214's exclusive family selection and ADR-0215's magnitude policy
- Close-attack priority superseded by: [ADR-0222](0222-anchor-phase-attacks-to-percussion.md)

Phase Gameplay Analysis supplies a shared pool of measured attacks. The native
game owns difficulty, spacing, lanes, checkpoints, and sweep construction. Native
conversion experiments show that selecting a sparse foreground beforehand loses
useful evidence and that input counts alone do not predict emitted gameplay.

Full-mix attacks remain available with or without source separation. Phase Parts
and recurring Phase Hooks can add audible attacks and modestly favor a foreground
phrase, but cannot erase accompaniment. Detection can normalize each source;
encoded strengths use a common mix-derived scale and measured source energy.
Near-coincident source detections annotate the existing mix attack. They do not
shift its time. The native beat-power field uses smoothed full-mix energy,
independently of foreground selection, instead of harmonic energy alone.

This intentionally supersedes passage thinning and fixed support attenuation.
It preserves the existing optional model, codecs, Storage publication, and
failure behavior. There are no new dependencies or runtime emulator requirements.
Version `librosa-phase-5` invalidates older chart provenance on ordinary Save/Sync;
device selection still defers analysis under ADR-0216. Bounded evidence can cost
more than a sparse chart, but avoids applying difficulty twice. The 20,000-event
codec ceiling is enforced across time so loud sections cannot evict entire quiet
sections. The mapping remains an iOpenPod design, not recovered iTunes behavior.

The [version-5 evaluation](../research/phase-algorithm-v5.md) records iterations,
native output, and limitations. Headless conversion verifies mechanics; physical
play feel and source-identity accuracy remain open acceptance criteria.
