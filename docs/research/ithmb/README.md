# iTHMB research

Research date: **2026-10-11**. This is a research dossier, not an Apple
specification or an accepted change to iOpenPod's writing policy.

## Scope and principal findings

iTHMB is the repository's term for a device-specific image file containing packed
cover or Photo pixels referenced by ArtworkDB or PhotosDB byte ranges. The main
scope here is the filesystem-accessible iPod Photo, Video, Classic, and Nano
families. Early iPhone/iPod touch formats are included where the same historical
sources discuss them, with their different scope identified. Modern iOS or macOS
thumbnail caches are not established by these findings merely because their
filenames also end in `.ithmb`.

The starting point is [issue #178's supplied research
comment](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456).
It reports useful measurements, especially a 6,160-byte F1061 slot and
500 MiB F1060 shards. Its samples and measurement script were not supplied in that
comment. It cannot establish a rule for every device of the reported model, every
firmware, or every writer. The [issue evidence](issue-evidence.md) records both
supporting and conflicting reports.

The strongest general model is an **external index plus device-specific image
representations**, not a self-describing image container. Database records give
the path, offset, lengths, format ID, and geometric fields; a format descriptor
supplies the missing interpretation. An ordinary raw iTHMB payload has no universal
magic number, per-image header, or embedded format ID. See the
[container and index](container-and-index.md) evidence.

The evidence does **not** justify a global `format_id -> layout` truth table.
Source implementations already provide device-specific overrides, while F1061
has conflicting 55-row and 56-row interpretations. Model, firmware, source of
metadata, producing software, representation purpose, and actual bytes matter.
Neither “all 1061 is 6,160 bytes” nor “all 1061 is 6,272 bytes” is established.
See [Device Profiles](device-profiles.md) and the
[remaining questions](validation-and-open-questions.md).

## Reading guide

| Document | Contents |
| --- | --- |
| [Container and index](container-and-index.md) | Files, paths, ArtworkDB/PhotosDB relationships, MHNI/MHIF fields, lengths, allocation, sharing, rollover, and bounded decoding. |
| [Pixel formats](pixel-formats.md) | Packed RGB, byte order, recursive layouts, rotation, UYVY fields, I420 planes and tails, scaling, padding, and codec limits. |
| [Device Profiles](device-profiles.md) | Historical per-family format IDs, dimensions and encodings, metadata interpretation, Original iOpenPod, and sample provenance. |
| [Issue evidence](issue-evidence.md) | The starting report, relevant closed issues, exact comment links, confounders, and limits of reported success. |
| [Validation and open questions](validation-and-open-questions.md) | Confidence rules, F1061 competing hypotheses, reproducible sample collection, controlled experiments, and unresolved areas. |
| [Repository implications](repository-implications.md) | Present implementation versus research, existing ADRs, documentation disagreements, and questions for a later implementation decision. |

## How to interpret evidence

These categories describe provenance, not an automatic ranking of correctness:

| Category | What it establishes | What it does not establish |
| --- | --- | --- |
| Measured artifact | A stated procedure produced stated results for bytes with identified provenance. | That a device displayed those bytes correctly, or that another firmware behaves identically. |
| First-person device report | A reporter says a named setup produced a particular observation. | Independent reproduction or control of unstated variables. |
| Source implementation | The pinned program reads, writes, or assumes the stated layout. | That Apple firmware accepts every output, or that a comment is accurate. |
| Synthetic regression | The software handles a constructed case as asserted. | That the case occurs on a physical iPod or is firmware-compatible. |
| Inference or proposal | A hypothesis follows from cited observations, or an experiment could discriminate it. | A newly discovered format fact or accepted architecture decision. |

Multiple files, forks, ports, or tables descended from one implementation are one
source family. Repetition is not independent corroboration. In particular,
projects which cite iOpenPod's tables cannot be used to independently validate
those same tables. A closed issue denotes workflow state, not experimental proof.
Unknown Data is retained evidence, not automatically corruption.

## Source map and reproducibility

Specific claims link to their sources in the individual notes. These revisions
make the main source inspections reproducible:

| Source family | Revision or reference | Use and limitations |
| --- | --- | --- |
| [libgpod](https://github.com/gtkpod/libgpod/tree/7982c5554f78dde47fd006afbeff659201d6db3d) | `7982c5554f78dde47fd006afbeff659201d6db3d` | Mature readers, writers, format tables, and SysInfoExtended parser. Contains unresolved comments and implementation mistakes; not an Apple specification. |
| [foo_dop / ipod_manager](https://github.com/reupen/ipod_manager/tree/08e0657b5ee09bd05cdb60273e1a139205d4d3f6) | `08e0657b5ee09bd05cdb60273e1a139205d4d3f6` | Separate data/allocation lengths, offset alignment, geometry, and file-list behavior. Writer choices remain writer evidence. |
| [Keith's iPod Photo Reader](https://github.com/kebwi/Keiths_iPod_Photo_Reader/tree/c15481b7abeb5750d6264ba9d1800787977294d8) | `c15481b7abeb5750d6264ba9d1800787977294d8` | Original reverse-engineering observations and executable decoding. Coverage and uncertainty are stated by its author. |
| [ithmbrdr](https://github.com/cyianor/ithmbrdr/tree/d9de0d2cadd2ba116f20eef2a203a40ca6fb3f5c) | `d9de0d2cadd2ba116f20eef2a203a40ca6fb3f5c` | Nano 3 observation and F1067 decoder. Credits Keith's format research; algorithm agreement is not wholly independent. |
| [Original iOpenPod](https://github.com/TheRealSavi/iOpenPod/tree/a20242428b93b672d14b37230772dbad75139c69) | `a20242428b93b672d14b37230772dbad75139c69`, local `origin/1.x` | Required behavioral baseline; shared ancestry with current code means it is not independent confirmation. |
| iOpenPod 2.0 | Local HEAD `e6fa69065edc5858277b818fe5ccee1925566eeb` | Implementation and accepted-policy comparison, not a source of new physical-device validation. |
| [iOpenPod issues](https://github.com/TheRealSavi/iOpenPod/issues/178) | Retrieved 2026-10-11; individual permalinks in issue evidence | First-person reports and historical investigation. Comments can subsequently be edited; raw attachments were not automatically validated by reading them. |

The older [ArtworkDB notes](../artworkdb-format.md),
[PhotosDB notes](../photosdb-format.md), [UYVY investigation](../ithmb-uyvy-format.md),
and [Photo sharding research](../photo-sharding-2026-10-08.md) remain useful local
context. Their prior device experiments are attributed historical evidence, not
experiments repeated during this investigation. Relevant disagreements are called
out in [Repository implications](repository-implications.md).

The historical iPodLinux iTunesDB page could not be retrieved during this pass;
its claims are not silently reconstructed from search snippets. Source readers
and writers provide the inspectable binary evidence instead. This collection
covers the known format layers and explicitly identifies remaining gaps; it does
not claim that the entire family has been reverse engineered.
