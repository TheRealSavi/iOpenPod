# ADR-0055: Export Photos through the Active Filesystem Session

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0005, ADR-0041, and ADR-0054

## Context

The Photos browser can select semantic Photos and Photo Albums, and the Application
Layer can already read generation-bound Photo thumbnails. Host export must preserve
the Track and Playlist export guarantees without giving the GUI a Mount Point or
letting presentation code read device files directly.

Some iPods retain an ordinary full-resolution image for a Photo. Others expose only
packed iTHMB representations. Photo Album export also needs a portable Host shape;
there is no interoperable document format that preserves the iPod-specific slideshow
fields.

## Decision

- Selected Photos and complete Photo Albums use the existing serialized,
  background Host-export controller. Export reports per-file progress, supports
  cooperative cancellation between files, and is cancelled when the Active iPod
  changes.
- `DeviceCoordinator` resolves each semantic Photo against the current Active iPod.
  Before output is planned, Storage must prove that the selected Host folder is on
  another Physical Device.
  A readable full-resolution reference must remain beneath `Photos/`, must name a
  regular non-empty file, and is pinned between naming and copying. Storage streams
  that exact file through the identity-bound Filesystem Session into a create-only
  Host destination.
- For every Photo, the Application Layer requests each distinct retained Photo
  thumbnail format through the same exact-format iTHMB read path used by browsing.
  Every format must be supported by the current Device Profile and readable; its
  owned RGB888 pixels are encoded as a separately named ordinary quality-95 JPEG
  before create-only publication. An unreadable format fails the export rather than
  silently producing an incomplete Photo folder.
- Export names prefer the retained full-resolution basename and otherwise use the
  stable semantic Photo identity. Invalid Host filename characters and Windows
  reserved names are sanitized through the same naming policy as Track and Playlist
  export. Existing files are never replaced; name collisions receive a numeric
  suffix, and in-operation collision checks are case-insensitive.
- Every distinct Photo receives one uniquely named child folder containing its
  readable full-resolution file, when available, and one JPEG named by format ID and
  decoded dimensions for every retained iTHMB format. Selected Photos create those
  folders directly beneath the user-selected Host folder. Exporting a Photo Album or
  All Photos first creates one uniquely named collection folder and then exports each
  distinct member folder once in retained membership order. The collection folder
  represents the collection name and membership only; iPod-specific slideshow
  settings are not serialized.
- Cancellation or failure leaves already published files, and any allocated Photo
  Album folder, visible for the user. No partial file is published and no completed
  output is removed automatically.

## Consequences

Photo export remains a read-only iPod-to-Host workflow and can run during Backup
capture. The GUI handles only semantic Photos, a chosen Host folder, progress, and
terminal outcomes; it never receives a Device Path or Filesystem Session.

Full-resolution images retain their original bytes and extension. Every decodable
iTHMB rendition remains independently visible and identifiable by its format ID and
dimensions, but its Host JPEG contains only the decoded device resolution and cannot
recreate unavailable original pixels or metadata. Photo Album slideshow settings
would require a separate documented interchange format if they are ever exported.
