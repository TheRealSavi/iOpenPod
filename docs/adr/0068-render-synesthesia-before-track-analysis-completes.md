# ADR-0068: Render Synesthesia before Track Analysis completes

- Status: Accepted
- Date: 2026-09-24
- Supersedes in part: ADR-0051's exact relocation on analysis completion

## Context

The Player continues while a Musical Analysis Job decodes and analyzes the current
Track. Synesthesia already has a live field renderer, but its pre-analysis idle
field does not follow the Track's transport and installing the completed Track
Analysis resets the field. Long analysis therefore appears to delay the visualizer
and interrupts its visual continuity.

## Decision

Opening Synesthesia starts a Synesthesia Preview immediately. The preview
uses the current Playback Entry's Track identity and Player clock to produce
modest, deterministic field forcing. It reads no audio, creates no Musical
Evidence, and does not claim beat, Source, or Section information. The independent
Musical Analysis Job continues unchanged in the background.

When Track Analysis arrives for the current Playback Entry, the renderer retains
its Coupled Field, GPU particles, feedback, and Transport Epoch. It aligns with
the Player's latest position through the existing bounded clock correction, then
blends continuous forcing, Scene tuning, motion, and camera pose over 2.4 seconds
of playing time. Musical events crossed during that handoff are consumed but not
rendered as delayed impulses. A pause freezes both the field and handoff. Explicit
Player seeks still relocate the field and clear view-dependent feedback. A new
Playback Entry starts a fresh preview; leaving the page releases the state.

## Consequences

- The visualizer can appear before any Track bytes are copied or decoded.
- The preview expresses motion and Track continuity, not audio-reactive analysis.
- A failed or cancelled analysis leaves the preview available while the page is
  active.
- Analysis completion no longer resets the visual world or flashes its feedback.
