# Windows Store submission requirements

Researched September 25, 2026 against Microsoft documentation and current source.
Scope: iOpenPod, x64 MSIX, Windows PC, free with optional external donations.

## Submission content

MSIX listing limits: description 10,000 characters; short description 1,000
(prefer under 270); first-submission release notes blank; up to 20 features at 200
characters each; up to 11 additional requirements per class, 200 characters each.
At least one screenshot is required.
[Microsoft listing fields](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/add-and-edit-store-listing-info)

Seven search terms are allowed, each at most 40 characters, with at most 21 words
total. Copyright/trademark info is limited to 200 characters. Custom license
terms accept plain text up to 10,000 characters or a single URL. An empty license
field selects Microsoft's standard terms; iOpenPod supplies its own GPL terms.
[Microsoft additional information](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/add-additional-information)

Desktop screenshots: PNG, at least 1366×768, at most 50 MB, up to ten images.
Use actual UI without added marketing overlays; captions can be 200 characters.
Microsoft recommends several screenshots and a 300×300 app tile. Games' poster
and box-art requirements do not imply this PC music app needs Xbox/game assets.
[Microsoft screenshot requirements](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/screenshots-and-images)

The prepared primary category is Music and secondary category Utilities + tools,
with no subcategory. These match playback and device-library management.
[Microsoft categories](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/categories-and-subcategories)

## Policy decisions

Microsoft policy 10.2.4 permits external software dependencies when disclosed at
the start of the description. The copy names FFmpeg, FFprobe, and Chromaprint.
Policy 10.5 requires an accurate privacy policy for Win32 apps. Policy 10.8
requires secure donation processing and third-party payment disclosure. The
optional Ko-fi browser flow gives no paid benefits. Capability use must match
the app. These are implementation choices, not a guarantee of approval.
[Microsoft Store policies, version 7.20](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies-and-code-of-conduct)

Partner Center accepts privacy policy text where available, or a hosted URL;
support can be a web page or email. The existing author address is used for
support. An unverified prospective page URL must not be presented as published.
[Microsoft privacy and support fields](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/support-info)

Declare the external donation flow. Leave the formal accessibility declaration
unchecked until required assistive-technology checks are complete. The prepared
data-backup declaration is disabled; this does not prevent users from backing up
files independently. No game, pen/ink, mixed reality, or generative-AI claims.
[Microsoft product declarations](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/product-declarations)

The IARC questionnaire generates regional ratings. The app's local content and
public podcast directory must be disclosed honestly. It is not valid to invent
an Everyone/3+ rating because the shell itself has no mature content. Exact
answers depend on the live questionnaire and its help text.
[Microsoft age-rating process](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/age-ratings)

The `runFullTrust` explanation describes selected local/removable media,
Win32 APIs, local helper subprocesses, and an asInvoker desktop process.
Submission notes include hardware and helper setup. The prepared release choice
holds publication for the owner, rather than using automatic publication after
certification.
[Microsoft submission options](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/manage-submission-options)

Account identity and any trader/business verification must use the owner's real
records. A free price or donation button alone cannot determine a legal trader
classification. Do not fabricate account details to enable markets.
[Microsoft company-account verification](https://learn.microsoft.com/en-us/windows/apps/publish/store-business-verification-reqs)

## Privacy evidence from the application

| Behavior | Source evidence |
| --- | --- |
| Apple's public directory receives search words; user-agent identifies iOpenPod | `src/iOpenPod/app/podcasts/feed_client.py`, `ApplePodcastDirectoryClient.search`, `_request_bytes` |
| Feed and artwork requests accept HTTP/HTTPS and follow redirects | `feed_client.py`, `FeedparserPodcastClient`, `HttpPodcastArtworkLoader`; `podcasts/identity.py` |
| Opening podcast pages can refresh automatically | `src/iOpenPod/GUI/pages/podcast_page.py`, `_schedule_open_refresh`, `_refresh_open_source` |
| Podcast artwork requests are made as images become visible | `src/iOpenPod/app/podcasts/artwork_controller.py`, `request` |
| Subscriptions and listening state stay on the selected iPod | `src/iOpenPod/app/podcasts/store.py`, `SUBSCRIPTIONS_PATH`, `HISTORY_PATH` |
| Settings store preferences, selected folders and last volume | `src/iOpenPod/app/core/settings/definitions.py`, `stores.py`; `src/storage/host_files.py` |
| Scan cache is local | `src/iOpenPod/app/context.py`, `host-media-library-v7.json` |
| Logging is local, rotating, with exception details; issue reporting is a suggestion | `src/iOpenPod/app/core/logging.py`; `src/iopenpod_launcher.py` |
| Track metadata/artwork go to Windows media controls | `src/iOpenPod/app/playback/system_media/bridge.py`, `windows.py` |
| Support and Ko-fi open external pages | `src/iOpenPod/GUI/pages/settings_page.py` |
| No built-in telemetry, updater, or crash upload found | Source-wide review of HTTP/network/telemetry/update/crash references; direct networking is the podcast client |

The privacy policy deliberately does not say that no data ever leaves the
computer. It describes local paths and caches, network recipients, optional
support/donations, operating-system processing, and deletion controls. Local
files are not claimed to be encrypted. This is a source audit, not a packet
capture or an audit of third-party services' internal data practices.

## Podcast-directory asset terms

Apple's current Search API page includes podcasts and allows metadata lookup.
Its promotional-asset terms require an approved nearby store badge/deep link
and constrain how artwork/previews are used. It does not state a separate
podcast-artwork exemption. The release preparation removes directory artwork
from search results and the saved-subscription fallback. Textual search metadata
and feed URLs remain. Publisher-feed artwork is fetched only through the feed
workflow. Previously saved URLs are not deleted by an ambiguous hostname rule;
a normal feed refresh updates that metadata. This finding is not a claim that
the app's text-only lookup is prohibited.
[Apple Search API and legal terms](https://performance-partners.apple.com/search-api)

## Prepared materials

See `packaging/windows/store/listing.md`, `submission-fields.json`,
`privacy.md`/`privacy.html`, `support.md`/`support.html`, and
`certification-notes.md`. The public pages contain no analytics, remote fonts,
scripts, or embedded external resources. Screenshots are prepared separately.

## Offline import and API scope

Partner Center exports a UTF-8 CSV with `Field`, `ID`, `Type`, `default`, and
language columns. The first three columns must remain unchanged. Values can be
filled from the prepared JSON. New images can be imported with the CSV in one
folder; their paths include the root folder's name. A generated CSV with guessed
field IDs is not a valid substitute for this export.
[Microsoft MSIX listing import/export](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/import-and-export-store-listings)

The MSIX submission API requires an existing app and an initial submission
created in Partner Center. API-created submissions should subsequently be edited
through the API only; mixing portal edits can invalidate that workflow. Therefore
the prepared JSON is deliberately a field manifest, not an account-specific
API payload. Context7 did not expose relevant Store-submission documentation;
the Microsoft-owned API reference supplies the primary evidence.
[Microsoft Store submission API](https://learn.microsoft.com/en-us/windows/uwp/monetize/manage-app-submissions)

Completion requires account-side acceptance of the package, policy/support
availability, generated IARC ratings, and final exact-build validation. A local
document or older WACK pass cannot stand in for those facts.
