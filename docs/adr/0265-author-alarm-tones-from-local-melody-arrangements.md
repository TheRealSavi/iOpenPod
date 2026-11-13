# ADR-0265: Author Alarm Tones from local melody arrangements

- Status: Accepted
- Date: 2026-11-13
- Extends: ADR-0247, ADR-0260 and ADR-0263

## Decision

The requested Tones page is available for Classic and Nano 3–5. Device Registry
describes custom-tone capability separately from Alarm and Countdown Timer
support. Nano 6/7's fixed timer sounds do not imply custom-tone files. Compact
navigation places Tones under Extras; Sidebar lists it directly. The page uses
the existing iOpenPod theme, typography and controls, with explicit Host preview.

iPodDB authors the common native UTF-8 name and unsigned frequency/duration
format. The Application Layer captures tone files and saved language through
Storage. New tone publication uses the existing connection-bound Extras
transaction, checks firmware and captured sources, enforces the native 19-custom
limit and unique names, and chooses an opaque filename. Opening the page never
writes. Publication rereads the catalog, making the tone available to Alarm
sound selection. Neither existing Alarm selections nor the Library are rewritten.

**Convert to tone…** operates on one saved Music Track. The background worker
captures its bytes through the existing Playback Source interface and decodes
bounded PCM locally. It uses ordered chroma recurrence and musical activity to
rank phrases throughout the Track. A harmonically weighted salience function,
percussion suppression, persistent-accompaniment attenuation and a continuous pitch path transcribe up to six short
candidates into roughly seven seconds of monophonic notes and rests. Odd partial
support distinguishes missing fundamentals from unsupported lower octaves.
The implementation uses existing NumPy, SciPy, librosa and FFmpeg dependencies.

The current optional source-separation interfaces return derived features, not
separated PCM suitable for this operation. Adding a model/runtime dependency
would increase installation and execution costs without establishing that the
returned voice is the main melody. The chosen algorithm is an automatic
arrangement inspired by predominant-melody research; it does not claim exact
transcription or guaranteed main-melody recognition. Unpitched inputs can fail
with an actionable message. The user listens to the actual generated notes,
chooses a name and explicitly saves. Preview approximates pitch and timing;
the physical speaker's timbre is not emulated.

Analysis is cancellable and preserves its read reservation until the worker
exits. Device changes invalidate pending results and dialogs. Encoded temporary
audio is removed on completion or failure; decoded audio remains in memory.
Inputs are bounded to 512 MiB and 15 minutes. No audio is uploaded or retained
as a new Library Track.

## Evidence and consequences

The [native authoring investigation](../research/alarm-tone-authoring-2026-11-13.md)
executes all seven target parsers and sound paths, including silent rests.
The [melody investigation](../research/alarm-tone-melody-extraction-2026-11-13.md)
records algorithm sources, alternatives and limitations.

Tests cover native receipt vectors, damaged framing, capacity and collisions,
virtual-device publication and stale sources, melody with louder accompaniment,
missing fundamentals, nonmelodic rejection, cancellation and GUI review. Firmware
execution and synthetic audio checks do not establish subjective quality for
every recording or physical speaker acceptance. Dense polyphony, layered voices
and a prominent accompaniment remain difficult cases; preview exposes the actual
result before it becomes a saved tone.
