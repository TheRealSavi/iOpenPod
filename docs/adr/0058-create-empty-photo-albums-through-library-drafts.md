# ADR-0058: Create empty Photo Albums through Library Drafts

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0053, ADR-0054, and ADR-0057

## Context

The Photos browser can edit retained user Photo Albums, but it cannot create one.
Original iOpenPod places a **New Album** action in the Photos header and writes
ordinary albums with MHBA type 2 on most supported devices or type 6 on iPod Nano
6th and 7th generation devices. iOpenPod 2 must preserve its draft, device-capability,
and lossless PhotosDB boundaries rather than letting the GUI construct binary rows or
write immediately.

## Decision

- The Photos header exposes one primary **New Album** action. It is enabled only
  while a readable Photo Database is loaded and the Library Workspace is editable.
  The action collects a name, creates an empty album, selects it in the source list,
  and leaves the change in the current Library Draft.
- `LibraryWorkspace.create_photo_album` validates the current edit revision and a
  nonempty, encodable name. It appends an ordinary album with an identity one greater
  than every retained Photo and Photo Album identity, starting at 100, and records
  the compatible preceding-album position value.
- Device Registry owns Photo Album creation policy. Photo-capable profiles declare a
  non-master MHBA type: 2 ordinarily and 6 for iPod Nano 6th and 7th generation
  devices. A retained user album can provide the same policy when a source-neutral
  workspace is exercised without an Active iPod.
- iPodDB analysis independently requires a unique unsigned 32-bit album identity,
  an ordinary album role, valid semantic values, and an explicit non-master unsigned
  8-bit album type. The PhotosDB reconciler appends a typed MHBA with its name MHOD
  and any requested MHIA membership while preserving retained albums and Unknown
  Data.
- Creation uses the existing analyze, prepare, reparse verification, review, and
  recoverable Storage Transaction path. It does not authorize a direct device write
  or broaden Photo asset mutation.

## Consequences

Users can create an empty Photo Album from the page header and then manage its Photo
membership with the existing dialog. New albums use an evidenced, device-specific
binary policy and remain undoable until saved. Photo creation/removal, Master Photo
Album editing or deletion, representation changes, and file-format changes remain
blocked.
