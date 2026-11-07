# ADR-0162: Bound Host reads to observed file size

- Status: Accepted
- Date: 2026-10-21
- Extends: ADR-0031, ADR-0082, and ADR-0136

## Context

[Issue #243](https://github.com/TheRealSavi/iOpenPod/issues/243) reports unchanged
media on a macOS WebDAV mount failing metadata reads and Sync capture with false
file-growth errors. The same library works on a local disk. Storage requested one
extra byte during metadata reads and read full chunks until EOF during capture.
Python's buffering could also request bytes beyond the observed file size.

Apple's published
[WebDAV read implementation](https://github.com/apple-oss-distributions/webdavfs/blob/main/webdav_fs.kextproj/webdav_fs.kmodproj/webdav_vnops.c)
has an uncached range-read path in `webdav_read_bytes` that transfers the requested
count. `webdav_rdwr` can return through that path before its ordinary EOF clamp.
This supports a concrete explanation for the intermittent failures: a request
crossing EOF can return surplus bytes while the file's stat facts remain unchanged.
Tests model that behavior and reproduce both reported growth messages. They do not
establish the exact driver implementation running on the reporter's machine.

A Windows scan also reported 192 changed directories on its first enumeration,
then zero on its final enumeration with identical listing and file counts. Repeated
read-only traversals of those folders subsequently produced no warnings. The old
comparison treated directory allocation size as content evidence. An isolated
size-only change reproduces the warning without changing entries, identity, or
timestamps. The original log lacks field values, so the specific native field
behind those Windows warnings remains unconfirmed.
Subsequent directory-change diagnostics log the compared modification and change
times at debug level to make that distinction observable.

## Decision

Storage bounds every Host source read to the observed file size **below** Python's
buffering. This applies to seekable metadata and artwork streams, bounded byte
reads, private captures, and the shared capture used for media preparation.
Seeking relative to EOF uses the observed size. No physical read is issued at or
beyond that boundary, including for empty files and buffered read-ahead.

Growth detection uses the existing final descriptor and path observations rather
than an extra-byte read. Identity, file size, modification time, same-API change
time, no-link checks, cancellation, capture byte counts, and content hashing remain
in force. A provider returning EOF before the observed size fails even when its
stat information is stale. Changed files are rejected; this does not retry against
new file facts or silently authorize a newer source.

Directory observations retain their reported size for inspection, but exclude it
from equality. Directory size describes filesystem allocation or caching rather
than the collection's content. Identity and modification-time comparisons remain,
as do same-operation change-time checks and pinned no-link enumeration. Genuine
directory churn still fails strict enumeration or reports a best-effort scan issue.

## Consequences

Host reads do not use provider-specific over-EOF behavior as a content-change
signal. As with the existing checks, a provider that hides actual writes behind
unchanged identity and timestamps cannot provide a guaranteed consistent snapshot;
capture hashes bind the bytes actually accepted. Device Filesystem Session read
and mutation policy is unchanged.

Regression coverage exercises buffered footer reads, line and buffer reads, empty
and multichunk sources, both capture paths, and directory allocation changes. It
also retains rejection of changed source metadata, short content, replacement,
links, cancellation, and incomplete captures. Validation on the affected native
WebDAV mount remains necessary to confirm the complete reported scenario.
