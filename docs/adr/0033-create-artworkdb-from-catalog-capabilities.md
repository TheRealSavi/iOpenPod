# ADR-0033: Create ArtworkDB from catalog capabilities

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0021, ADR-0030 and ADR-0032

## Context

The first cover could not be prepared because the application supplied cover
formats but no ArtworkDB root value. Requiring additional files to establish that
value prevented creation on an otherwise identified iPod with an empty Artwork
directory. The user requested creation without that additional evidence.

Original iOpenPod's album-art writer uses 6 at MHFD offset 0x10 without a reference
database, begins image identities at 100, and includes an empty type-6 MHAF body.
Local Nano 5 and Nano 7 captures contain that root value and the same empty body.
The [libgpod writer](https://github.com/fadingred/libgpod/blob/master/src/db-artwork-writer.c)
uses root value 2 and begins album-art identities at 100. These are compatibility
policies, not proof of a universal meaning for the root field.

## Decision

Known cover-capable Device Profiles carry an explicit ArtworkDB creation value of
6, following Original iOpenPod. The Application Layer passes this and sparse-artwork
support through `WriteTarget`. Additional ArtworkDB, iTHMB, SysInfoExtended, or
photo files are unnecessary. The format builder still takes explicit root values;
unidentified callers cannot establish a write target by guessing a format ID.

iPodDB creates the three standard datasets, starts fresh image IDs at 100, writes
every declared cover format, and adds the evidenced empty type-6 body to new image
records. The type-6 MHAF body remains opaque within its MHOD extent: its inner size
words are not interpreted as generic Chunk lengths. The previously supported type-6
MHNI representation continues to use the typed container path. Retained roots,
auxiliary bodies, image ranges, and photo data remain authoritative.

Older Track headers and profiles without sparse-artwork support use individual
MHII reverse Track links. Shared pixels can share retained byte ranges, but each
required owner receives a distinct image identity. `IdentityMapping.track_id`
qualifies an artwork mapping when the same requested asset produces different
per-Track identities. Longer supported Track headers also receive their direct link.
Existing header lengths are preserved.
Allocation also reserves dangling iTunesDB artwork references. Attaching the first
Artwork Index can resolve those previously unverified display associations to no
image, with a warning; their native fields remain unchanged and cannot capture a
newly allocated cover.

New fixed-size images begin at frame-aligned offsets after verified retained
prefixes. Missing or ambiguous affected datasets and conflicting MHIF image sizes
block preparation. Independent verification checks native Track artwork fields,
root identity allocation, target formats, dimensions, padding, image sizes, MHIF
entries, ranges, and decode dimensions. Storage publishes thumbnails, ArtworkDB,
and iTunesDB through the existing reviewed transaction and retains recovery data.

## Consequences

An identified, writable iPod can receive its first cover without a template
database. Catalog-wide raster tests and cover-creation tests cover the declared
layouts, including Nano 7's padded 57-pixel row. Rotated rectangular RGB565 and
the catalog's aggregate I420 row size are supported by the byte-only codec.

This does not enable photo-management workflows, unsupported iTunesDB signatures,
compressed databases, or SQLite companions. Virtual-volume save/recovery tests and
captured-file round trips establish software behavior; they do not claim playback
on every firmware. Existing accepted ADRs remain historical records.
