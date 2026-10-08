# ADR-0132: Follow explicitly authorized Host symbolic links

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0074 for explicitly selected Host media and folder enumeration
- Extends: ADR-0063 and ADR-0082

## Context

A user may deliberately choose media through a symbolic link, including a normal
file beneath a linked parent folder. Rejecting every linked path component made
these selections produce an empty Host Media Library. The scanner retained an
issue, but Select Media and Review did not show its explanation.

Automatically traversing every discovered link would broaden a folder selection
and could revisit directories indefinitely. Retaining the existing scan throughput
also matters: alias-heavy libraries must not multiply directory listings or media
inspection.

## Decision

Storage resolves explicitly selected or dropped Host files and folders once at
scan setup. The canonical target becomes the source for enumeration, metadata,
cache identities, lazy reads, and Sync. Retargeting the original selection does not
redirect that in-progress scan. A later scan resolves the user's selection again.
Resolution does not grant read authority: normal Storage observations, pinned
no-link reads, file-fact validation, and Sync captures remain required.

Each Host Media Library folder has a **Follow symbolic links** setting, disabled
by default. Older saved folders retain their settings and default this option to
false. When enabled, links encountered within that folder may contribute supported
files and directories, including targets outside its root. Linked files do not
require recursion; linked
directories are descended only when **Recurse into subfolders** is also enabled.

Each folder's media-type, recursion, and link permissions propagate together.
Overlapping selections combine their independently authorized results; one
selection's link permission cannot widen another selection's media types. The
normal no-link traversal retains its streaming filename-filtered path. Opt-in
traversal uses bounded directory workers and retains filtered directory observations
for that pass, so later arriving permissions can reuse them without relisting.
Already observed filesystem identities stop cycles and repeated directory work;
canonical paths are the fallback where an inode is unavailable. Regular-file
identities deduplicate aliases and hard links before inspection without extra
same-file probes. Known hard-link Playlist references share the selected Track
while preserving Playlist occurrences. Those mappings are not persisted as parsed
Playlist references in the cache.
Resolution reuses ordinary ancestor probes within one selection or enumeration
pass. It never caches read authority or carries that resolver into another pass;
normal Storage observations and pinned reads still reject replaced ancestors.

Each verification pass obtains fresh observations and resolves discovered links
again. Link changes become existing best-effort scan diagnostics; the published
sources retain their original canonical paths. The cache remains an optimization,
with the same documented limits for hostile edits preserving its file facts.

This exception does not apply to indirect Playlist references or Device Paths.
Network/device path syntax, unsupported reparse points, special files, and broken
or cyclic link chains remain rejected. Windows directory junctions are not symbolic
links and remain outside this option. Storage's ordinary file and directory APIs
continue to reject links in every path component.

Select Media and Review retain a scan-issue summary with expandable, bounded plain
text details. The log also records bounded issue details, rather than only a count.
Skipped or rejected media must not appear to be a clean empty scan.

## Consequences

Deliberately selected aliases work without enabling broad recursive traversal.
Users with libraries organized through links can opt in per folder. Graph scans
retain more filtered directory observations than ordinary scans, trading bounded
per-entry memory for avoiding repeated filesystem I/O. Neither path performs extra
media reads on an unchanged warm cache solely because links are present.

Regression coverage includes selected aliases and linked parents, separate
recursion and link settings, overlapping permissions, cycles, hard links and alias
duplicates, warm-cache reuse, broken links, target replacement, source diagnostics,
and retained indirect-reference restrictions. Platform-specific filesystem cases
still require their native test environments.
