# ADR-0100: Reconcile firmware playback sidecars on device selection

- Status: Accepted
- Date: 2026-09-30
- Extends: ADR-0019, ADR-0029, ADR-0030, ADR-0098
- Supersedes: ADR-0085's preservation-only treatment of understood, loaded sidecars

Playback history and On-The-Go Playlists must already be committed when device
selection finishes. The Application Layer captures sidecars, asks iPodDB to project
their evidence over the retained database snapshot, and immediately prepares and
saves the result through the existing verified Library transaction. Only the
committed Library becomes the Active iPod visible to the application. This runs
independently of later user edits, Draft mode, or Sync. Discovery remains read-only.

iPodDB remains pure: projection starts from the retained baseline, `serialize()`
reproduces the source bytes, and preparation produces the candidate output. The
Application Layer owns the timing and Storage owns persistence. Selection skips
the save entirely when no understood sidecars need consumption.

The standalone `iPodDB.sidecars` package owns raw sidecar records, lossless readers,
and positional remapping. It does not depend on Library types, Storage, or iOpenPod.
Library-specific merging remains in `library._sidecar_projection`, which consumes
that package. The public Library interface re-exports only the captured-input type
and capture/preservation helpers needed by application workflows; raw format
readers and document types are exposed by the sidecar package itself.

Storage captures bounded sidecar bytes and fingerprints. The selection-time save
archives each consumed file verbatim as its inactive `.bak` companion and removes
the active input in the same Storage Transaction. Existing backups have captured
preconditions and participate in recovery. Publication writes the database before
removing active inputs. Recovery restores both, including previous backups. A
changed, missing, or newly introduced sidecar invalidates reconciliation. Files
that were not loaded for interpretation retain ADR-0085's positional preservation
rules; they are never deleted just because a Library was saved.

Supported interpretation covers binary Play Counts, both Shuffle iTunesStats
layouts, persistent-ID PlayCounts.plist, and base/numbered OTGPlaylistInfo. The base
OTG file is a semaphore; orphan numbered files are not reimported. All captured
numbered files are imported in numeric order, including gaps, and each consumed
file is archived. Duplicate Track occurrences and distinct identical Playlists
survive. Multiple competing playback sources, malformed records, unavailable
identities, unrepresentable totals, and ambiguous Device Time Context dates
produce diagnostics and fail selection without publishing a pending Library.
Read-only devices with understood pending evidence cannot complete selection.
Pre-publication failures preserve the database and sidecars; interrupted writes
use the existing recovery workflow. Verified commits remain successful when only
cleanup or flushing needs attention, with a diagnostic and retained recovery path
where applicable.

Reloading after Restore or Keep Current Contents bypasses sidecar projection and
consumption. It displays the actual restored or kept database without immediately
changing that explicit recovery outcome. A later ordinary selection reconciles
pending evidence again. Recovery reloads retain sidecar fingerprints for the
existing conservative save protections.

The `.bak` archive preserves Unknown Data that has no Library representation.
Known binary ratings include zero (an explicit clear) and the all-ones unavailable
sentinel. This deliberately corrects the Original iOpenPod's zero-rating heuristic.
The plist's zero rating remains unspecified, following its different reference
semantics. Shuffle's undocumented `skipped` value is exposed but not invented as
a skip-count delta. See [the format and lifecycle contract](../playback-sidecars.md).

No dependencies, Back Sync, Host tag updates, scrobbling, or firmware Preferences
edits are introduced. Authored fixtures and virtual Storage transactions cover the
implementation; physical firmware acceptance remains separate.
