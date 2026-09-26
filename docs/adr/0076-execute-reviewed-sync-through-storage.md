# ADR-0076: Execute reviewed Sync through Storage

> ADR-0084 narrows media-tool requirements to affected operations and makes acoustic
> matching optional for explicit Adds. ADR-0085 preserves positional playback
> sidecars in the Library transaction.

- Status: Accepted
- Date: 2026-09-25
- Extends: ADR-0029, ADR-0030, ADR-0034, ADR-0065, ADR-0066 and ADR-0070
- Supersedes: ADR-0070's disabled execution control and the retained media policy's
  assumptions about the current Sync implementation

The retained `sync-media-policy.md` and `sync-validation.md` describe an earlier
implementation absent from the current source. Their recipe cache, encoder matrix,
and Back Sync evidence are historical; they do not validate this execution path.

Review now authorizes execution of its immutable selected Sync Plan. Execution
reserves a clean Library Workspace and the Active iPod, snapshots user settings,
checks the plan against its completed scans, and validates current source facts.
FFmpeg, FFprobe, and Chromaprint fpcalc must be available before preparation.
Tool failures reach the result screen with installation or source/setting remedies.

Independent media preparation runs concurrently on the Host. Storage owns private
captures, external file-processing processes, content identities, temporary files,
and cleanup. The application chooses encoding policy from the Device Profile and
the captured preferences. Output must meet the profile's limits, retain its duration,
and decode successfully. Workers use bounded process output and cooperative
cancellation; device publication remains sequential to respect the shared USB 2.0
bus. No new media-processing dependency is introduced.

Incoming Track filenames use exactly four uppercase letters plus the media format's
lowercase extension. Sync and Add Music share an allocator that reserves existing
Library and pending batch paths without reusing files awaiting removal. Storage
checks candidate destinations for untracked files; Sync performs these metadata
checks serially after concurrent preparation. Track locations, prepared media paths,
and Sync Details stay consistent. Final absence preconditions still reject files
that appear after allocation, and collisions never produce longer filenames.

An isolated Library Draft contains only successfully prepared changes. Failed
replacements retain their existing Track and file. Playlist reconciliation must not
remove a retained Track merely because its Update was excluded or failed. It
preserves ambiguous, nested, and firmware-managed Playlists rather than guessing
their identity. Explicit Track removals remove Playlist occurrences as part of the
same desired snapshot. Shared files remain while another record references them.

Review previews Playlist creations and membership/order updates separately and
captures an explicit Reconcile Playlists choice. Selected Playlist changes can run
without media changes. Disabling reconciliation retains existing memberships except
references to explicitly removed Tracks. Host Playlist facts are revalidated before
execution; unreadable, excluded, or changed references cannot silently erase device
memberships. The result reports applied Playlist changes independently of media.

Photo creation and replacement supply independently verified original and thumbnail
resources. A new PhotosDB requires the Device Profile's explicit root policy.
Replacement preserves Photo identity and retained album membership; additions enter
the Master Photo Album. Rotation and fitting affect viewing copies only. Fresh
thumbnail shards avoid rewriting old packed data across USB. Cleanup may reclaim a
wholly unreferenced file under the supported Photo thumbnail namespace, extending
ADR-0059; unused ranges inside files still referenced by another Photo are retained.

iPodDB prepares and independently verifies the complete desired Library. The
Application Layer submits media and database artifacts through the existing issued
Library Review and Storage Transaction. Storage stages and verifies media before
publishing the database references, then recoverably removes obsolete files. A
preparation failure can therefore produce a useful partial Sync; an interrupted
publication requires restoration of the complete transaction. This is ordered,
recoverable publication, not filesystem-wide power-loss atomicity.

Cancellation before publication discards Host preparations and restores/cleans
staging when necessary. Once publication starts, Storage finishes the protected
transaction rather than stopping between related artifacts. A failed restore leaves
the Operation Journal available and reports that recovery is required. Retry
Recovery rediscovers the journal's identity-bound device and can restore it without
first parsing an incomplete Library. Unknown later changes block restoration.

The pre-Review iPod Media Scan no longer persists the Library Sync Helper. Only a
verified successful commit may publish successful Sync Details, and only committed
items receive that provenance. Failure to refresh this non-authoritative index is a
visible warning about an already saved Library. Terminal transaction cleanup follows
commit; failure retains a named recovery location and a warning. No backup preference
weakens these protections.

The Sync result distinguishes completion, partial completion, cancellation, failure,
and required recovery. Diagnostics include the affected item, underlying failure,
and an actionable remedy where possible. Retrying requires a fresh scan and Review;
an interrupted transaction must be recovered first.

The application persists an outstanding recovery journal location across restarts
and prevents further device writes until it is restored. Storage still verifies
device identity and journal contents; a saved location never grants write authority.
Prepared Photo images are bounded to 64 MiB and a 512 MiB prepared batch. ADR-0086
allows larger Host containers to supply a bounded still image. Optional
full Rockbox metadata transformations are bounded to 256 MiB per file. Exceeding a
bound skips the affected item with a remedy rather than risking unbounded memory.

Committed Syncs with retained recovery files expose Retry Cleanup separately from
Retry Recovery. The cleanup reminder survives a restart. Cleanup only accepts a
terminal journal and cannot restore the previous Library. An unconfirmed final
flush after cleanup reports safe-eject guidance without retaining a retry for a
deleted journal. Discovery checks unfinished journals before selection can repair
device metadata, including when an interrupted Library is not parseable.

Verified RESTORED markers grant the same narrowly scoped terminal cleanup authority
as COMMITTED markers. Retrying cleanup after a successful restoration validates the
device identity, exact journal fingerprint, terminal state, writer lease, and flush;
it does not repeat restoration or hash all media again. Missing cleanup entries
are already cleaned, including AppleDouble companions removed by macOS alongside
their data files. Links, unsafe entries, changed journals, and disconnects still
fail closed. Artwork capture excludes `._` companions from Library dependencies.

Storage reports file verification, dependency checks, recovery inspection, and
flush activity separately from durable journal-state events. Sync forwards these
activities and automatic restoration progress to the GUI, including after a
cancellation request. Elapsed time and time since the last progress update remain
visible. A restored Library with pending cleanup is distinguished from a failed
restoration.

Auto lossy encoding prefers available FDK AAC, AudioToolbox AAC, LAME MP3, then
native AAC. Manual controls expose supported bitrate modes and codec options.
Spoken Word always uses its lossy bitrate and optional mono policy when Smart
quality is enabled, including compatible sources. Explicit content tags and M4B
extensions identify Podcasts and Audiobooks. Lossless-to-lossy overrides PCM-to-ALAC;
normalization only reduces rates above 44.1 kHz. Normalize Tags After Sync applies
the existing device-specific normalizer to the committed Library. Sound Check uses
existing usable loudness tags where possible and analyzes missing values. Rockbox
tags are written into private prepared media; Host sources are never changed.
