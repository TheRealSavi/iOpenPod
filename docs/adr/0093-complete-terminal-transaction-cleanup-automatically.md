# ADR-0093: Complete terminal transaction cleanup automatically

- Status: Accepted
- Date: 2026-09-27
- Amends: ADR-0029's retained recovery lifetime and ADR-0089's terminal cleanup reminders
- Extends: ADR-0076

Successful Library saves retained their committed Operation Journals and original
files without running cleanup. Metadata edits, Playlist changes, and automatic
saves therefore accumulated completed transactions. Selection later surfaced them
as Sync cleanup warnings even though no publication or cleanup had failed. Sync
already attempted cleanup, but only for its own current transaction.

The Application Layer completes terminal cleanup as part of a successful Library
save. Storage still retains originals through staging, publication, verification,
and commit. An ordinary save then releases that transaction's recovery namespace.
Sync explicitly defers this step until its Library Sync Helper update has been
attempted, preserving the existing order of verified Library publication, Sync
Details, and cleanup. A helper failure remains a warning about an already saved
Library and does not require keeping its committed recovery copies indefinitely.

Selection also drains matching committed and restored transactions left by older
saves or an interrupted cleanup. Discovery remains read-only. Before removing any
terminal namespace, selection classifies every active journal on the selected
Volume. Any malformed or nonterminal journal requires the existing recovery choice
first, so enumeration order cannot discard recovery evidence before an unfinished
transaction is handled. Terminal journals with different Physical Device or Volume
identities, and journals explicitly declined through Keep Current Contents, remain
untouched.

Automatic cleanup uses the same Storage authority as Retry Cleanup: exact device
identity, captured journal fingerprint, terminal state, writer lease, safe paths,
and flush. It does not restore files or rehash all media. Only the transaction's
private recovery namespace is removed; current Library and media contents remain.
This lifecycle does not depend on Backup Snapshots or a backup preference.

Successful cleanup produces no warning or user choice. An actual cleanup failure
reports its underlying reason and retained journal location without treating the
committed Library as unsaved. Automatic Library saves open the successful-save
warning diagnostics; reloading the iPod automatically retries cleanup. Sync and
selection failures also expose Retry Cleanup for remaining recovery files. An
unconfirmed final flush after a namespace was removed reports safe-eject guidance
without offering a retry for a journal that no longer exists. Interrupted
publication continues to require restore-or-keep recovery rather than terminal
cleanup.
