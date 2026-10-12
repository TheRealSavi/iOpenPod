# ADR-0140: Find album artwork through explicit provider search

- Status: Accepted
- Date: 2026-10-12
- Extends: ADR-0026, ADR-0033, and ADR-0138

## Context

An Album without artwork currently requires choosing a Host image in the Metadata
Editor. The requested workflow finds covers through the iTunes Store or Discogs
from the Album context menu, following the search-and-preview behavior illustrated
by [iTunes Artwork Finder](https://bendodson.com/projects/itunes-artwork-finder/)
and [Meta](https://www.nightbirdsevolve.com/meta/).

## Decision

One complete Music Album exposes **Find Album Artwork…** in the shared Track menu.
The dialog prefills Album Artist (or Artist) and Album, permits edited search terms,
and offers iTunes Store region selection or Discogs release search. A user starts
each search explicitly; opening the dialog sends no network request. Up to 25
results display provider metadata, with a selected result's cover preview, actual
pixel dimensions, and an external source-page action. Search terms are sent only
to the chosen provider. There is no automatic matching or bulk library scan.

The Application Layer owns typed provider results, HTTPS requests, bounded image
decoding, and cancellable workers. Downloads accept only provider origins and
validate redirects before following them, cap JSON at 2 MiB and images at 32 MiB,
use a 10-second socket timeout and a 30-second streaming deadline, and reject images
larger than 8192 pixels per side or 32 megapixels before decoding. Requests identify
iOpenPod and use the existing certifi trust bundle. Cancellation and newer requests
invalidate earlier results. Closing cancels work without waiting for network I/O;
Application-owned workers remain alive until completion and then release themselves.

The iTunes adapter uses the [Apple Search API](https://performance-partners.apple.com/search-api)
with the album entity. It attempts a 1200-pixel image using the provider's existing
image-size URL convention and falls back to the returned artwork URL if that image
is unavailable or invalid. This convention is best effort, not a resolution
guarantee. Discogs searches releases and uses their returned cover image. Discogs
authentication uses a user-entered personal access token, as described by the
[official client](https://github.com/discogs/discogs_client/blob/master/docs/authentication.md).
The masked field retains it only for the dialog session; the token is sent in an
Authorization header exclusively to the Discogs API and never to image servers.
Credentials are not persisted in Settings, the Library Draft, or device metadata.

**Apply Artwork** submits owned RGB pixels through `LibraryWorkspace.set_artwork`
at the dialog's captured edit revision. If any selected Tracks lack artwork, the
default fills only those Tracks; the user can explicitly replace all Album covers.
Applying changes uses the existing automatic save or manual Draft all changes
policy. Ordinary cover replacement preserves later Artwork Display Times under
ADR-0138. Library changes, locking, switching, and disconnecting invalidate the
dialog. Cancelling, failed requests, and stale results cannot change the Library.

The Metadata Editor's Artwork tab also offers **Find Album Artwork…** for its
selected Tracks. In that entry point, **Use Artwork** invokes the editor's pending
image assignment instead of changing Library Workspace. It replaces the selected
Artwork Display Time entry and retains other pending frames and metadata edits.
Only the Metadata Editor's **Apply** submits the combined revision-bound edit;
**Cancel** discards it. The missing-artwork-only control belongs to direct Album
application and is hidden when returning an image to the Metadata Editor.

## Consequences

The feature adds no dependencies, direct device I/O, metadata lookup changes, or
alternative artwork writer. The dialog and provider errors use the shipped German
and Spanish catalogs, including regenerated compiled translations. Tests cover
provider parsing, authentication scope,
download/image limits, fallback, cancellation, selection, and revision checks.
External catalog availability and physical iPod rendering remain outside the
offline test guarantees. Only returned Discogs release covers are offered; browsing
every release image and persistent account authorization remain future work.
