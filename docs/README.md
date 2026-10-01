# Documentation

- [Scrobbling](scrobbling.md) — Last.fm and ListenBrainz setup, Sync behavior,
  delivery receipts, and API references.

This directory holds shared project knowledge that should survive individual coding
sessions.

## Start here

- [`../CONTEXT.md`](../CONTEXT.md) — system purpose, boundaries, present stage, and
  open questions.
- [`../GLOSSARY.md`](../GLOSSARY.md) — canonical domain terminology.
- [`source_architecture.md`](source_architecture.md) — detailed target source
  architecture.
- [`gui-design-language.md`](gui-design-language.md) — working semantic color,
  typography, metric, and interaction foundations for the desktop GUI.
- [`eta.md`](eta.md) — reusable stage ETA model, integration, and accuracy limits.
- [iPod timestamp conversion](ipod-time.md)
- [Firmware playback sidecars](playback-sidecars.md) — parsing, Library projection,
  transactional consumption, and recovery of playback history and OTG Playlists.
- [`ipod-preferences.md`](ipod-preferences.md) — typed, lossless firmware Preferences
  and iTunesPrefs readers/writers, supported layouts, and model limitations.
- [`sync-workflow-audit-2026-09-26.md`](sync-workflow-audit-2026-09-26.md) — scan and Sync findings, fixes, and remaining limits.
- [`packaging.md`](packaging.md) — native builds, store metadata, validation, and
  unresolved store-release requirements.
- [`licensing.md`](licensing.md) — GPL distribution, corresponding source,
  third-party notices, and optional donations.
- [`adr/`](adr/) — durable architectural decisions and their consequences.
- [`agents/`](agents/) — configuration for agent-oriented engineering workflows.
- [`research/`](research/) — supporting investigation and reference material.

Private plans and work items belong under `.scratch/` at the repository root. That
directory is intentionally excluded from version control.
