# ADR-0028: Record Library write DEBUG diagnostics

- Status: Accepted
- Date: 2026-09-11
- Extends: ADR-0023

The album-edit investigation showed that phase-only logs could not explain an
unexpected generated Playlist edit or its verification failure. In response to the
request for substantially more verbose DEBUG logging, Library analysis and
preparation now record source/attempt identities, requested and generated changes,
bounded metadata values, resource requirements, native reconciliation decisions,
artifact fingerprints, timings, and complete structured issues.

This extends ADR-0023's logging policy: Library metadata may now appear in the
rotating DEBUG log as well as the explicit inspection report. INFO output remains
concise. Binary documents, image pixels, and signing identity bytes are excluded.
Expensive value formatting and artifact hashing are guarded by the DEBUG level.
Logs remain observations; they do not become a replay format, a second editable
Library Draft, or authority to save. Stage entry and elapsed time do not imply
successful verification.
