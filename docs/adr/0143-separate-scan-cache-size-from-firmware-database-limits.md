# ADR-0143: Separate scan cache size from firmware database limits

- Status: Accepted
- Date: 2026-10-14
- Amends: ADR-0123's aggregate catalog byte limits

## Context

A Host Media Scan of 21,558 files completed inspection but could not persist its
Host Media Scan Cache because the encoded catalog exceeded 64 MiB. The same ceiling
also rejected large Library Sync Helpers and evicted reusable iPod Analysis Cache
records. A separate 256 MiB total for decoded Acoustic Fingerprints imposed another
Library-size restriction. These application catalogs are not firmware databases.

## Decision

Remove both aggregate byte ceilings from reading and writing the Host Media Scan
Cache, iPod Analysis Cache, and Library Sync Helper. Analysis records are no longer
evicted to satisfy a byte ceiling. Keep their existing formats, checksums, schema
validation, record-count limits, and bounded decoding of individual Acoustic
Fingerprints. Preserve identity and source-freshness checks, atomic publication,
retryable cache failures, and protection of invalid existing Library Sync Helpers.

Device Registry's model-specific 32 MiB or 64 MiB limit continues to constrain
prepared firmware database writes. It does not constrain application catalogs,
including the Library Sync Helper stored on the iPod. Transient image-cache memory
budgets remain separate resource-management policies.

## Consequences

Valid catalogs can be saved and reused after restart when they exceed the former
byte ceilings. No format migration or cache deletion is required. Serialization
and parsing still hold whole catalogs in Host memory, so memory and disk use grow
with Library size; this decision does not introduce streaming persistence.
