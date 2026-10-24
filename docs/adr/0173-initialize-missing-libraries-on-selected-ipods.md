# ADR-0173: Initialize missing Libraries on selected iPods

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0013, ADR-0016, ADR-0029, and ADR-0061

## Context

An Apple restore can leave an identified iPod with `iPod_Control` but without its
iTunesDB, as reported for the fourth-generation monochrome iPod. Original iOpenPod
automatically created the missing layout and empty, device-compatible Library on
selection. The 2.0 Device Picker instead made every missing database unselectable.

The behavioral baseline is `device/bootstrap.py` and
`itunesdb_writer/mhbd_writer.py` on the Original iOpenPod `1.x` branch at commit
`a20242428b93b672d14b37230772dbad75139c69`. Its root qualification, signing checks,
base directories, named Master Playlist, and older-firmware dataset exclusions
inform this change. Its globals and direct filesystem writes are not carried over.

## Decision

Discovery remains read-only. An exactly identified, write-safe Device Candidate
with an existing `iPod_Control` directory and an absent primary Library database
can be selected for initialization. This also applies when restoring the user's
remembered selection. Ordinary removable Volumes without the marker stay outside
the Device Picker. Initialization does not format a Volume or install firmware.

Selection revalidates the Connection Generation, Device Profile, marker, database
absence, identity metadata, signing inputs, and outstanding Storage Transactions.
Existing databases, including empty, malformed, or unsupported alternate databases,
are never replaced. The one exception to requiring both database paths to be absent
is the empty iTunesDB compatibility file on a compressed-database profile: that
file is retained unchanged. An externally supplied primary discovered before
preparation is loaded normally instead of initialized.

The public `iPodDB.library.create_empty_library` interface accepts the selected
binary version, Podcast support, filesystem platform, and existing `WriteTarget`
signing and artifact capabilities. It constructs a private unnamed seed through
the shared Chunk Definitions, then names the Master Playlists through ordinary
Library preparation. This reuses structural verification, size limits, CDB framing,
signing, and the complete SQLite projection. New persistent database identities are
allocated once. Older baselines omit artist and newer stub datasets, matching the
Original behavior. No application code imports binary-format implementation types.

The Application Layer requires valid signing material wherever the Device Profile
requires it. Missing identity or HASH72 material cannot produce unsigned fallback
output. Preparation rejects retained Playback Sidecars without their original
Library, unsafe directory shapes, and existing SQLite companions that would be
overwritten. It checks all required files and capacity before creating directories.

Storage creates the missing `Device`, `iTunes`, `Music`, and `Artwork` directories
under `iPod_Control`. Music distribution subdirectories are created by normal media
publication when needed. A single create-only Storage Transaction stages and
verifies every Library artifact. SQLite companions and the compatibility file
precede the primary database. Identity/signing dependencies and absent-file
preconditions are checked during publication; marker and Playback Sidecar checks
also run at transaction checkpoints. Existing media and optional ArtworkDB or
PhotosDB files are retained. Initialization does not reconstruct orphaned media
membership or create empty artwork/photo databases.

Activation follows verified publication and durability. Interrupted publication
retains the existing transaction recovery workflow and never exposes a partial
Active iPod. Restoration can return to the original absent Library; recovery reload
does not automatically initialize it again. A subsequent selection can retry.
Successfully committed transactions are cleaned up using the existing verified
cleanup contract. Empty directories may remain after failure or restoration; they
are harmless and are not recursively deleted. Backup Snapshots are not required.

## Consequences

A restored fourth-generation monochrome iPod can load an empty Library and proceed
through ordinary Library editing and Sync. Existing Libraries retain their exact
bytes. Read-only or unidentified candidates remain blocked, and incomplete signing
evidence or conflicting artifacts produces a selection error before publication.

Tests use virtual Volumes for representative early, Mini, video, Classic, and nano
profiles. They cover read-only discovery, model versions, named Masters, signatures,
CDB/SQLite artifacts, repeated selection, concurrent file and identity changes,
unsafe paths, missing signing material, disconnects, and recovery. Physical firmware
acceptance, including a newly restored iPod 4 mono, remains to be validated on hardware.
