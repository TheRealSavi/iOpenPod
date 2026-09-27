# Architectural Decision Records

An Architectural Decision Record (ADR) captures a durable decision, the context in
which it was made, and its consequences. ADRs explain why the architecture has its
current shape; they do not replace implementation documentation.

## When to write an ADR

Write an ADR when a decision:

- changes a system boundary or dependency direction;
- selects or removes a foundational technology;
- establishes a safety or data-integrity policy;
- constrains multiple future features; or
- reverses an earlier architectural decision.

Do not create an ADR for routine implementation details or easily reversible local
choices.

## Naming and status

Use `NNNN-short-kebab-case-title.md`, with numbers assigned sequentially.

Supported statuses:

- **Proposed** — under active discussion and not yet binding.
- **Accepted** — the current decision.
- **Superseded by ADR-NNNN** — retained for history but no longer current.

Accepted ADRs are immutable historical records. Supersede one with a new ADR instead
of rewriting the old decision.

## Template

```md
# ADR-NNNN: Decision title

- Status: Proposed
- Date: YYYY-MM-DD

## Context

What forces and constraints require a decision?

## Decision

What was decided?

## Consequences

What becomes easier, harder, required, or prohibited?
```

## Index

- [ADR-0001: Use Python 3.12 and UV](0001-use-python-3-12-and-uv.md)
- [ADR-0002: Separate the four primary subsystems](0002-separate-the-four-primary-subsystems.md)
- [ADR-0003: Share quality configuration between CLI and VS Code](0003-share-quality-configuration-between-cli-and-vs-code.md)
- [ADR-0004: Use Original iOpenPod as the compatibility baseline](0004-use-original-iopenpod-as-the-compatibility-baseline.md)
- [ADR-0005: Use one Active iPod and user-directed Sync](0005-use-one-active-ipod-and-user-directed-sync.md)
- [ADR-0006: Require lossless iPodDB round trips](0006-require-lossless-ipoddb-round-trips.md)
- [ADR-0007: Ship one application with branded package names](0007-ship-one-application-with-branded-package-names.md)
- [ADR-0008: Require one definition-driven iPodDB path](0008-require-one-definition-driven-ipoddb-path.md)
- [ADR-0009: Use Qt logical pixels and native display metrics](0009-use-qt-logical-pixels-and-native-display-metrics.md)
- [ADR-0010: Resolve ranked Device Evidence in the Device Registry](0010-resolve-ranked-device-evidence-in-the-device-registry.md)
- [ADR-0011: Bind Storage access to Connection Generations](0011-bind-storage-access-to-connection-generations.md)
- [ADR-0012: Load artwork lazily across existing boundaries](0012-load-artwork-lazily-across-existing-boundaries.md)
- [ADR-0013: Reconcile device metadata across existing boundaries](0013-reconcile-device-metadata-across-existing-boundaries.md)
- [ADR-0014: Persist global settings through Storage](0014-persist-global-settings-through-storage.md)
- [ADR-0015: Isolate iOpenPod 2.0 global settings from Original iOpenPod](0015-isolate-iopenpod-2-settings-from-original-iopenpod.md)
- [ADR-0016: Qualify Device Candidates and correlate macOS hardware](0016-qualify-device-candidates-and-correlate-macos-hardware.md)
- [ADR-0017: Stream playback through a replaceable backend](0017-stream-playback-through-a-replaceable-backend.md)
- [ADR-0018: Publish playback through optional system media sessions](0018-publish-playback-through-optional-system-media-sessions.md)
- [ADR-0019: Project databases through a common Library contract](0019-project-databases-through-a-common-library-contract.md)
- [ADR-0020: Project Playlists and isolate session edits](0020-project-playlists-and-isolate-session-edits.md)
- [ADR-0021: Prepare Library Drafts over retained Database Documents](0021-prepare-library-drafts-over-retained-documents.md)
- [ADR-0022: Apply and save Playlist drafts](0022-apply-and-save-playlist-drafts.md)
- [ADR-0023: Capture write requests and inspect them without replay](0023-capture-write-requests-and-inspect-them-without-replay.md)
- [ADR-0024: Reconcile and verify Playlists by dataset](0024-reconcile-and-verify-playlists-by-dataset.md)
- [ADR-0025: Resolve Library edits before reconciliation](0025-resolve-library-edits-before-reconciliation.md)
- [ADR-0026: Share one Library Workspace for metadata and Playlists](0026-share-one-library-workspace-for-metadata-and-playlists.md)
- [ADR-0027: Restore the previously selected iPod](0027-restore-the-previously-selected-ipod.md)
- [ADR-0028: Record Library write DEBUG diagnostics](0028-record-library-write-debug-diagnostics.md)
- [ADR-0029: Publish file transactions with retained recovery](0029-publish-file-transactions-with-retained-recovery.md)
- [ADR-0030: Bind Library file transactions to issued reviews](0030-bind-library-file-transactions-to-issued-reviews.md)
- [ADR-0031: Inspect captured Host media before planning imports](0031-inspect-captured-host-media-before-planning-imports.md)
- [ADR-0032: Add inspected music through Library reviews](0032-add-inspected-music-through-library-reviews.md)
- [ADR-0033: Create ArtworkDB from catalog capabilities](0033-create-artworkdb-from-catalog-capabilities.md)
- [ADR-0034: Bind media replacement intent to Library Drafts](0034-bind-media-replacement-intent-to-library-drafts.md)
- [ADR-0035: Author evidence-backed Smart Playlist choices](0035-author-evidence-backed-smart-playlist-choices.md)
- [ADR-0036: Reclassify retained media without replacement](0036-reclassify-retained-media-without-replacement.md)
- [ADR-0037: Persist a device-aware Podcast catalog](0037-persist-a-device-aware-podcast-catalog.md)
- [ADR-0038: Preserve the Original backup archive contract](0038-preserve-the-original-backup-archive-contract.md)
- [ADR-0039: Use backup format v4 and bounded restore recovery](0039-use-backup-format-v4-and-bounded-restore-recovery.md)
- [ADR-0040: Identify backups by serial with a best-effort fallback](0040-identify-backups-by-serial-with-a-best-effort-fallback.md)
  (Original-archive identity treatment extended by ADR-0062)
- [ADR-0041: Allow foreground reads during Backup capture](0041-allow-foreground-reads-during-backup-capture.md)
- [ADR-0042: Analyze audio into ephemeral World Scores](0042-analyze-audio-into-ephemeral-world-scores.md)
  (analysis-result contract superseded by ADR-0046; selected-file input boundary
  superseded by ADR-0051)
- [ADR-0043: Render Synesthesia as one continuous world](0043-render-synesthesia-as-one-continuous-world.md)
  (rendering and fixed-motif portions superseded by ADR-0044; private playback
  session superseded by ADR-0051)
- [ADR-0044: Make Synesthesia topology and biography authoritative](0044-make-synesthesia-topology-and-biography-authoritative.md)
  (superseded by ADR-0045)
- [ADR-0045: Drive Synesthesia through one coupled field](0045-drive-synesthesia-through-one-coupled-field.md)
  (five-input presentation restriction superseded by ADR-0047; no-Scene restriction
  superseded by ADR-0048)
- [ADR-0046: Replace the Synesthesia analysis contract](0046-preserve-musical-context-in-synesthesia-evidence.md)
- [ADR-0047: Map Track Analysis into one expressive field](0047-map-track-analysis-into-one-expressive-field.md)
  (no-Scene restriction superseded by ADR-0048; private playback and page
  annotation superseded by ADR-0051)
- [ADR-0048: Direct Synesthesia through mood-selected visual Scenes](0048-direct-synesthesia-through-mood-selected-scenes.md)
- [ADR-0049: Choreograph Synesthesia Scenes as music-driven journeys](0049-choreograph-synesthesia-scenes-as-music-driven-journeys.md)
  (camera-policy portion extended by ADR-0050)
- [ADR-0050: Compose Synesthesia Camera Shots inside Scenes](0050-compose-synesthesia-camera-shots-inside-scenes.md)
- [ADR-0051: Make Player transport authoritative for Synesthesia](0051-make-player-transport-authoritative-for-synesthesia.md)
  (exact analysis-completion relocation superseded by ADR-0068)
- [ADR-0052: Model PhotosDB as a distinct artifact](0052-model-photosdb-as-a-distinct-artifact.md)
- [ADR-0053: Project Photos into Library Drafts](0053-project-photos-into-library-drafts.md)
  (Photo Album creation restriction extended by ADR-0058; Photo removal restriction
  extended by ADR-0059)
- [ADR-0054: Browse Photos through a lazy three-pane UI](0054-browse-photos-through-a-lazy-three-pane-ui.md)
  (Photo Album creation restriction extended by ADR-0058; Photo removal placeholder
  extended by ADR-0059)
- [ADR-0055: Export Photos through the Active Filesystem Session](0055-export-photos-through-the-active-filesystem-session.md)
- [ADR-0056: Preview retained full-resolution Photos safely](0056-preview-retained-full-resolution-photos-safely.md)
- [ADR-0057: Manage Photo Album membership through collection cards](0057-manage-photo-album-membership-through-collection-cards.md)
  (Photo Album creation restriction extended by ADR-0058)
- [ADR-0058: Create empty Photo Albums through Library Drafts](0058-create-empty-photo-albums-through-library-drafts.md)
  (Photo removal restriction extended by ADR-0059)
- [ADR-0059: Delete Photos through Library Drafts](0059-delete-photos-through-library-drafts.md)
- [ADR-0060: Use Native Safe-Removal Services](0060-use-native-safe-removal-services.md)
- [ADR-0061: Support late-iPod Library artifact sets](0061-support-late-ipod-library-artifact-sets.md)
- [ADR-0062: Assign matched Original backups to native identities](0062-assign-matched-original-backups-to-native-identities.md)
- [ADR-0063: Scan Host media into common Library Snapshots](0063-scan-host-media-into-common-library-snapshots.md)
- [ADR-0064: Browse Host and iPod Library Sources independently](0064-browse-host-and-ipod-library-sources-independently.md)
  (normal-sidebar source choice superseded by ADR-0067; source isolation retained)
- [ADR-0065: Index iPod media for Sync correlation](0065-index-ipod-media-for-sync-correlation.md)
- [ADR-0066: Prepare Sync Plans from correlated media](0066-prepare-sync-plans-from-correlated-media.md)
  (direct Review transition extended by ADR-0067)
- [ADR-0067: Present Host media inside the Sync Workspace](0067-present-host-media-inside-the-sync-workspace.md)
- [ADR-0068: Render Synesthesia before Track Analysis completes](0068-render-synesthesia-before-track-analysis-completes.md)
- [ADR-0069: Refresh devices while the Device Picker is open](0069-refresh-devices-while-the-picker-is-open.md)
- [ADR-0070: Select Sync actions in grouped Review](0070-select-sync-actions-in-grouped-review.md)
- [ADR-0071: Restore the remembered iPod at startup](0071-restore-the-remembered-ipod-at-startup.md)
- [ADR-0072: Open Sync collections as detail pages](0072-open-sync-collections-as-detail-pages.md)
- [ADR-0073: Apply Library changes automatically by default](0073-apply-library-changes-automatically-by-default.md)
- [ADR-0074: Constrain Host Playlist references through Storage](0074-constrain-host-playlist-references-through-storage.md)
- [ADR-0075: Publish lyrics with media-file tags](0075-publish-lyrics-with-media-file-tags.md)
- [ADR-0076: Execute reviewed Sync through Storage](0076-execute-reviewed-sync-through-storage.md)
- [ADR-0077: Hold Synesthesia Scenes across short Sections](0077-hold-synesthesia-scenes-across-short-sections.md)
- [ADR-0078: Prepare the next Synesthesia Playback Entry](0078-prepare-the-next-synesthesia-playback-entry.md)
- [ADR-0079: Prepare native packages with explicit store gates](0079-prepare-native-packages-with-explicit-store-gates.md)
- [ADR-0080: Distribute iOpenPod under GPLv3 or later](0080-distribute-iopenpod-under-gplv3-or-later.md)
- [ADR-0081: Require user-installed command-line media tools](0081-require-user-installed-media-tools.md)
- [ADR-0082: Tolerate Host Media Scan source churn](0082-tolerate-host-media-scan-source-churn.md)
- [ADR-0083: Tolerate Host-native media variants during preparation](0083-tolerate-host-native-media-variants.md)
- [ADR-0084: Keep optional media analysis out of Sync gates](0084-keep-optional-media-analysis-out-of-sync-gates.md)
- [ADR-0085: Preserve positional playback sidecars during Sync](0085-preserve-positional-playback-sidecars-during-sync.md)
- [ADR-0086: Prepare bounded stills for oversized Photos](0086-prepare-bounded-stills-for-oversized-photos.md)
- [ADR-0087: Report concurrent Host preparation progress](0087-report-concurrent-host-preparation-progress.md)
- [ADR-0088: Edit Track classification in the metadata editor](0088-edit-track-classification-in-the-metadata-editor.md)
- [ADR-0089: Make interrupted Sync recovery a device-scoped choice](0089-make-interrupted-sync-recovery-a-device-scoped-choice.md)
- [ADR-0090: Derive Volume presentation from the saved iPod](0090-derive-volume-presentation-from-the-saved-ipod.md)
