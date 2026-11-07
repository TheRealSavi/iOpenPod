# ADR-0222: Anchor Phase attacks to percussion

- Status: Accepted
- Date: 2026-11-01
- Supersedes: ADR-0215's vocal/guitar preference and ADR-0217's close-attack priority

Reported Phase gameplay can follow expressive vocals or guitar ahead of the
song's percussion. An authored regression reproduces a melodic anticipation
35 ms before a drum hit displacing that hit during the existing duplicate merge.
Audible percussion now receives priority within that merge window and a bounded
whole-vector magnitude preference. Times remain observed attacks, never snapped
to an inferred pulse. Native Phase continues to own difficulty and spacing.

Separated drums that satisfy the existing audibility and passage-power gates
anchor passages with at least two drum attacks. Otherwise melodic prominence,
recurrence, and continuity choose the foreground, without a vocal/guitar label
bonus. Acoustic analysis qualifies percussion using HPSS attack magnitude in the
shipped bands. Both paths retain other attacks outside the duplicate window and
keep the shared spectral scale and ratio-preserving quantizer from ADR-0221.

Drum detections match nearby measured acoustic percussion first; if none exists,
their own measured time takes precedence over nearby melodic mix evidence. This
deliberately relaxes the previous blanket mix-timestamp priority. Source estimates
and acoustic percussion classification remain fallible, especially in distorted
music. A stronger percussion preference trades some melodic emphasis for a more
stable rhythmic anchor; it does not claim to reconstruct Apple's analysis.

`librosa-phase-7` upgrades cached charts on ordinary Save/Sync. Device selection
still defers analysis. No dependency, codec, or Storage changes are introduced.
The [version-7 evaluation](../research/phase-algorithm-v7.md) records the local
*softscars* comparison and the limits of native conversion as play-feel evidence.
