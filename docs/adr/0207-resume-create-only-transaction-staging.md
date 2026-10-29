# ADR-0207: Resume create-only transaction staging

- Status: Accepted
- Date: 2026-10-29
- Extends: ADR-0029

A disconnected device can retain thousands of verified staged files. Restarting
staging wastes successful transfers and is unnecessary when publication has not
begun.

Storage exposes explicit staging resumption for create-only transactions. A new
Filesystem Session must identify the original Physical Device and Volume. The
retained Operation Journal must exactly match the supplied plan and still have
state `staging`. Existing staged files are fingerprinted and reused only when
their lengths and hashes match the captured content. Missing stages are copied;
damaged stages are retained within the transaction namespace and replaced.

Resumption uses the existing verification, publication, commit and cleanup path.
Replacements, removals, external recovery, individual staging, and interrupted
publication remain outside this interface and require their existing recovery
workflows. Unrelated files are never overwritten to make a resume succeed.

Regression tests reconnect through a new session, remove a Host source to prove
its valid staged file is reused, reject changed plans, and replace only a damaged
stage.
