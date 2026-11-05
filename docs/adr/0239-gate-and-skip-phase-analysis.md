# ADR-0239: Gate and skip Phase analysis

- Status: Accepted
- Date: 2026-11-04
- Supersedes: ADR-0216's upgrades on ordinary saves and ADR-0232's unrelated-save checks
- Clarifies: ADR-0225's producer provenance

Library saves and Sync only enter Phase preparation when the selected Phase
Playlist changes, including designation, membership, order or its editable
properties, or when a member's audio input changes. Input changes include incoming
media replacement, location, duration, eligibility and persistent identity.
Unrelated Playlists, Track titles, artwork, photos, device names and maintenance
writes do not trigger Phase cache checks, runtime discovery or analysis. Ordinary
source and Phase selection transaction preconditions still apply. Device selection
continues to defer Phase preparation, including Smart Playlist consequences;
the next edit affecting Phase can reconcile its companion index.

Chart compatibility ignores CPU/CUDA/MPS placement and the corresponding Torch
wheel build suffix. Existing provenance uses the same comparison, so previously
published charts need no migration or reanalysis just for changing acceleration.
The actual producer remains recorded verbatim. Algorithm, model, runtime release,
audio content and duration differences still invalidate reuse when preparation is
requested by a relevant write.

Automatic-save status, Review Changes and Sync offer **Skip Phase analysis**.
A fresh request-scoped event interrupts unfinished work at its existing checkpoints
and joins the input reader and optional analysis workers. Full cancellation and
disconnection retain precedence. Only fully verified completed charts and validated
cache hits enter the new Phase Library, in Playlist order. No partial chart or
placeholder is published. Tracks without a verified chart remain in the ordinary
Playlist but are unavailable in the game until a later Phase edit runs analysis.
Old chart files remain on disk; Skip does not delete game data or change settings.
The normal recoverable Library transaction publishes all completed work together.

This deliberately stops unrelated writes from retrying skipped work, repairing
Phase caches or upgrading analysis. Tests cover unrelated writes, relevant edits,
legacy and current backend provenance, partial-work publication, fresh requests,
UI action lifetime, cancellation and disconnection.
