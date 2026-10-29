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
- [ADR-0091: Sync Podcasts through shared media publication](0091-sync-podcasts-through-shared-media-publication.md)
- [ADR-0092: Enforce Podcast and video playback options](0092-enforce-podcast-and-video-playback-options.md)
- [ADR-0093: Complete terminal transaction cleanup automatically](0093-complete-terminal-transaction-cleanup-automatically.md)
- [ADR-0094: Target macOS 12.3 with platform-specific native dependencies](0094-target-macos-12-3-with-platform-specific-native-dependencies.md)
- [ADR-0095: Convert a complete Album to one chaptered Track](0095-convert-a-complete-album-to-one-chaptered-track.md)
- [ADR-0096: Publish status progress and actions as source-owned data](0096-publish-status-progress-and-actions-as-source-owned-data.md)
- [ADR-0097: Model Preferences as a lossless flat document](0097-model-preferences-as-a-lossless-flat-document.md)
- [ADR-0098: Capture Device Time Context for Library dates](0098-capture-device-time-context-for-library-dates.md)
- [ADR-0099: Share native Host tag interpretation](0099-share-native-host-tag-interpretation.md)
- [ADR-0100: Reconcile firmware playback sidecars on device selection](0100-reconcile-firmware-playback-sidecars-on-device-selection.md)
- [ADR-0101: Retain account-scoped scrobble delivery on the Host](0101-retain-account-scoped-scrobble-delivery-on-the-host.md)
- [ADR-0102: Adjust old Last.fm submission dates](0102-adjust-old-lastfm-submission-dates.md)
- [ADR-0103: Offer native media-tool installation](0103-offer-native-media-tool-installation.md)
- [ADR-0104: Publish validated tagged GitHub Releases](0104-publish-validated-tagged-github-releases.md)
- [ADR-0105: Route application updates by Install Channel](0105-route-application-updates-by-install-channel.md)
- [ADR-0106: Run Health only on explicit dispatch](0106-run-health-only-on-explicit-dispatch.md)
- [ADR-0107: Publish only native release archives](0107-publish-only-native-release-archives.md)
- [ADR-0108: Bundle Windows as one executable](0108-bundle-windows-as-one-executable.md)
- [ADR-0109: Authenticate and isolate GitHub application updates](0109-authenticate-and-isolate-github-application-updates.md)
- [ADR-0110: Offer macOS drag-to-Applications disk images](0110-offer-macos-drag-to-applications-disk-images.md)
- [ADR-0111: Correct evidenced artwork format sizes during preparation](0111-correct-evidenced-artwork-format-sizes-during-preparation.md)
- [ADR-0112: Publish Python distributions with GitHub Releases](0112-publish-python-distributions-with-github-releases.md)
- [ADR-0113: Update installed Python packages through PyPI](0113-update-installed-python-packages-through-pypi.md)
- [ADR-0114: Distinguish install downloads from update archives](0114-distinguish-install-downloads-from-update-archives.md)
- [ADR-0115: Treat SysInfo files as optional metadata](0115-treat-sysinfo-files-as-optional-metadata.md)
- [ADR-0116: Retain bounded Unknown Data with log-only diagnostics](0116-retain-bounded-unknown-data-with-log-only-diagnostics.md)
- [ADR-0117: Spill prepared Library content to Host storage](0117-spill-prepared-library-content-to-host-storage.md)
- [ADR-0118: Write application artwork for non-cover devices](0118-write-application-artwork-for-non-cover-devices.md)
- [ADR-0119: Compare Track tags and artwork before Sync Update](0119-compare-track-tags-and-artwork-after-host-file-changes.md)
- [ADR-0120: Separate Track payload replacement from tag and artwork updates](0120-separate-track-payload-replacement-from-tag-and-artwork-updates.md)
- [ADR-0121: Preserve retained F1061 raster height](0121-preserve-retained-f1061-raster-height.md)
- [ADR-0122: Match Original iOpenPod signing behavior](0122-match-original-signing-behavior.md)
- [ADR-0123: Reuse bounded media scan analysis](0123-reuse-bounded-media-scan-analysis.md)
- [ADR-0124: Accept validated mixed F1061 layouts](0124-accept-validated-mixed-f1061-layouts.md)
- [ADR-0125: Defer cover failures during Sync](0125-defer-cover-failures-during-sync.md)
- [ADR-0126: Persist individual iPod setting overrides](0126-persist-individual-ipod-setting-overrides.md)
- [ADR-0127: Resolve Sync duplicates with explicit Track associations](0127-resolve-sync-duplicates-with-explicit-track-associations.md)
- [ADR-0128: Discard explicitly removed Track media after Library save](0128-discard-explicitly-removed-track-media-after-save.md)
- [ADR-0129: Validate Library files at workflow boundaries](0129-validate-library-files-at-workflow-boundaries.md)
- [ADR-0130: Use Pillow limits for Photo sources](0130-use-pillow-limits-for-photo-sources.md)
- [ADR-0131: Accept bounded visible dimensions in packed artwork](0131-accept-bounded-visible-dimensions-in-packed-artwork.md)
- [ADR-0132: Follow explicitly authorized Host symbolic links](0132-follow-explicitly-authorized-host-symbolic-links.md)
- [ADR-0133: Recover evidenced artwork without clearing unavailable covers](0133-recover-evidenced-artwork-without-clearing-unavailable-covers.md)
- [ADR-0134: Verify unconfirmed durability before recovery cleanup](0134-verify-unconfirmed-durability-before-recovery-cleanup.md)
- [ADR-0135: Pack Photos into bounded shared shards](0135-pack-photos-into-bounded-shared-shards.md)
- [ADR-0136: Allow network filesystems as Host media sources](0136-allow-network-filesystems-as-host-media-sources.md)
- [ADR-0137: Warn and default unrecognized album collation](0137-warn-and-default-unrecognized-album-collation.md)
- [ADR-0138: Edit artwork by display time](0138-edit-artwork-by-display-time.md)
- [ADR-0139: Complete timed artwork formats and counts](0139-complete-timed-artwork-formats-and-counts.md)
- [ADR-0140: Restore Host media-tool path overrides](0140-restore-host-media-tool-path-overrides.md)
- [ADR-0141: Project native CDB metadata into SQLite](0141-project-native-cdb-metadata-into-sqlite.md)
- [ADR-0142: Refresh Smart Playlists before Library publication](0142-refresh-smart-playlists-before-library-publication.md)
- [ADR-0143: Separate scan cache size from firmware database limits](0143-separate-scan-cache-size-from-firmware-database-limits.md)
- [ADR-0144: Expand Track headers with device capabilities](0144-expand-track-headers-with-device-capabilities.md)
- [ADR-0145: Select Track layouts for all Library writes](0145-select-track-layouts-for-all-library-writes.md)
- [ADR-0146: Remove routine Podcast and re-encoding notices](0146-remove-routine-podcast-and-reencoding-notices.md)
- [ADR-0147: Restore late-iPod firmware write compatibility](0147-restore-late-ipod-firmware-write-compatibility.md)
- [ADR-0148: Keep Album browse groups contiguous](0148-keep-album-browse-groups-contiguous.md)
- [ADR-0149: Author Podcasts from Finder capture evidence](0149-author-podcasts-from-finder-capture-evidence.md)
- [ADR-0150: Retain firmware SQLite metadata and dual signatures](0150-retain-firmware-sqlite-metadata-and-dual-signatures.md)
- [ADR-0151: Write audio Podcasts with media type four](0151-write-audio-podcasts-with-media-type-four.md)
- [ADR-0152: Normalize Podcast Sync to the 12.6 baseline structure](0152-normalize-podcast-sync-to-baseline.md)
- [ADR-0153: Normalize SQLite Podcast Sync from Nano 5 evidence](0153-normalize-sqlite-podcast-sync.md)
- [ADR-0154: Import publisher Podcast metadata and images](0154-import-publisher-podcast-metadata-and-images.md)
- [ADR-0155: Preview publisher covers in Podcast discovery](0155-preview-publisher-covers-in-podcast-discovery.md)
- [ADR-0156: Bound device scan reads and cache absent audio](0156-bound-device-scan-reads-and-cache-absent-audio.md)
- [ADR-0157: Review explicit media stream selection](0157-review-explicit-media-stream-selection.md)
- [ADR-0158: Remember stream choices and committed video preparation](0158-remember-stream-choices-and-committed-video-preparation.md)
- [ADR-0159: Review and remember Playlist Sync matches](0159-review-and-remember-playlist-sync-matches.md)
- [ADR-0160: Preserve readable text subtitles](0160-preserve-readable-text-subtitles.md)
- [ADR-0161: Repair video playback metadata during Sync](0161-repair-video-playback-metadata-during-sync.md)
- [ADR-0162: Bound Host reads to observed file size](0162-bound-host-reads-to-observed-file-size.md)
- [ADR-0163: Preserve tag evidence during normalization](0163-preserve-tag-evidence-during-normalization.md)
- [ADR-0164: Keep Library save progress and safety visible](0164-keep-library-save-progress-and-safety-visible.md)
- [ADR-0165: Preserve shared Podcast albums during metadata edits](0165-preserve-shared-podcast-albums-during-metadata-edits.md)
- [ADR-0166: Stage Library media replacements one at a time](0166-stage-library-media-replacements-one-at-a-time.md)
- [ADR-0167: Recover Library transactions from the Host](0167-recover-library-transactions-from-the-host.md)
- [ADR-0168: Recover optional scan work without losing evidence](0168-recover-optional-scan-work-without-losing-evidence.md)
- [ADR-0169: Sign HASHAB with the published scheme](0169-sign-hashab-with-the-published-scheme.md)
- [ADR-0170: Correct development Qt typing](0170-correct-development-qt-typing.md)
- [ADR-0171: Use standard Track headers on Mini 2 and iPod video](0171-use-standard-track-headers-on-mini-2-and-ipod-video.md)
- [ADR-0172: Keep artist capitalization significant](0172-keep-artist-capitalization-significant.md)
- [ADR-0173: Initialize missing Libraries on selected iPods](0173-initialize-missing-libraries-on-selected-ipods.md)
- [ADR-0174: Create missing flat Podcasts counterparts](0174-create-missing-flat-podcasts-counterparts.md)
- [ADR-0175: Model native Genius capabilities by firmware](0175-model-native-genius-capabilities-by-firmware.md)
- [ADR-0176: Preserve and author native Genius data](0176-preserve-and-author-native-genius-data.md)
- [ADR-0177: Browse native Genius collections](0177-browse-native-genius-collections.md)
- [ADR-0178: Generate basic Genius during Sync](0178-generate-basic-genius-during-sync.md)
- [ADR-0179: Rank Genius with Elephant-Ear audio profiles](0179-rank-genius-with-elephant-ear-audio-profiles.md)
- [ADR-0180: Reuse confirmed durability during Host recovery cleanup](0180-reuse-confirmed-durability-during-host-recovery-cleanup.md)
- [ADR-0181: Bound Sync reads to workflow boundaries](0181-bound-sync-reads-to-workflow-boundaries.md)
- [ADR-0182: Verify Host transaction outputs once before commit](0182-verify-host-transaction-outputs-once-before-commit.md)
- [ADR-0183: Bound concurrent Genius audio analysis](0183-bound-concurrent-genius-audio-analysis.md)
- [ADR-0184: Manage manual and automatic Genius Mixes](0184-manage-manual-and-automatic-genius-mixes.md)
- [ADR-0185: Remove native Genius collections explicitly](0185-remove-native-genius-collections-explicitly.md)
- [ADR-0186: Reconcile Genius collections after Track removal](0186-reconcile-genius-collections-after-track-removal.md)
- [ADR-0187: Propose audio-informed Genius Mixes](0187-propose-audio-informed-genius-mixes.md)
- [ADR-0188: Bound authored Genius candidate rows](0188-bound-authored-genius-candidate-rows.md)
- [ADR-0189: Protect GitHub release credentials](0189-protect-github-release-credentials.md)
- [ADR-0190: Prepare and diagnose Linux device access](0190-prepare-and-diagnose-linux-device-access.md)
- [ADR-0191: Compare live Linux physical backing](0191-compare-live-linux-physical-backing.md)
- [ADR-0192: Pin Linux search-only ancestors](0192-pin-linux-search-only-ancestors.md)
- [ADR-0193: Resolve Btrfs recovery through all member devices](0193-resolve-btrfs-recovery-through-all-member-devices.md)
- [ADR-0194: Allow retained Album indexes without jump tables](0194-allow-retained-album-indexes-without-jump-tables.md)
- [ADR-0195: Adopt firmware database field semantics](0195-adopt-firmware-database-field-semantics.md)
- [ADR-0196: Adopt firmware clock and date evidence](0196-adopt-firmware-clock-and-date-evidence.md)
- [ADR-0197: Default full-suite tests to eight workers](0197-default-full-suite-tests-to-eight-workers.md)
- [ADR-0198: Adopt native rule operands and import markers](0198-adopt-native-rule-operands-and-import-markers.md)
- [ADR-0203: Validate artwork file references and allocations](0203-validate-artwork-file-references-and-allocations.md)
- [ADR-0204: Edit and preview artwork through Chapters](0204-edit-and-preview-artwork-through-chapters.md)
- [ADR-0205: Adopt native video playback contracts](0205-adopt-native-video-playback-contracts.md)
- [ADR-0206: Validate native lyrics publication](0206-validate-native-lyrics-publication.md)
- [ADR-0207: Resume create-only transaction staging](0207-resume-create-only-transaction-staging.md)
- [ADR-0208: Synchronize Jellyfin play counts through an iPod memory](0208-synchronize-jellyfin-play-counts-through-an-ipod-memory.md)
