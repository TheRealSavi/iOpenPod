# iOpenPod website

The Jekyll site in this directory describes iOpenPod only. It shares the current
application screenshots with the root README. Existing routes and GitHub Pages
project hosting are retained; `relative_url` keeps links valid under `/iOpenPod`
and when `baseurl` is empty for a custom domain.

The website's product name is **iOpenPod**, without a version suffix. Use that
name in visible copy, page titles, metadata, accessibility labels, and image text.
Keep technical version requirements and release references separate from branding.

## Editing and preview

`.github/workflows/pages.yml` builds this directory with Jekyll when website files
change on `main`, on relevant pull requests, and on manual dispatch. It validates
the rendered FAQ and structured data before uploading the Pages artifact. Only
`main` deploys, through the `github-pages` environment. Website deployment is
independent of application builds and tests.

The repository's **Settings → Pages → Build and deployment → Source** must be
**GitHub Actions**, with `main` allowed in the `github-pages` environment. The
previous `1.x` branch's `/docs` source does not build this website. After pushing
the workflow, **Actions → Build and deploy Pages → Run workflow** on `main` can
trigger a deployment without another website edit.

`index.html` is the product tour and download directory. `install-help.html` is
the setup guide. `_includes/` owns the shared navigation, footer, screenshot
figures, and download rows. `_layouts/default.html` owns metadata and asset loading.
`install-help-redirect.html` preserves the older `/install-help.html` URL.

`guides/` contains setup articles and guides for people encountering problems in
Apple Podcasts, Finder, Apple Music, Apple Devices, and iTunes. Answer the Apple
workflow question first, then explain the relevant iOpenPod alternative using
verified released behavior. Cite official instructions and distinguish reported
symptoms from established fixes.
`_data/guides.json` supplies link text and descriptions, a `group` of `start` or
`troubleshooting`, and a `featured` flag for homepage links;
`_layouts/guide.html` supplies the reading layout and download/help actions.
Keep substantive guidance specific to the task instead of duplicating pages for
keyword variants. Screenshots reuse the existing product assets and viewer.

Guide front matter sets a unique `title`, `description`, `heading`, `lead`,
`breadcrumb_title`, and `permalink`, with `layout: guide` and
`body_class: iop2-page guide-page`. Visible breadcrumbs and `BreadcrumbList`
structured data must describe the same path. Use `relative_url` for internal
links, including links with fragments. Set `related_guides` to two or three
relevant catalog URLs. Optional `cta_heading` and `cta_description` explain the
next step for the reader's task; the download and setup links stay shared.
All content pages are discoverable
from ordinary HTML links without JavaScript.

The shared layout escapes HTML metadata and JSON-encodes structured data. Its
SoftwareApplication describes the free price, project source, installation help,
and current release link. It does not invent reviews or ratings, and valid markup
alone does not establish eligibility for Google's software rich results.
The optional Search Console meta setting requires a genuine meta-tag token;
the existing HTML verification filename is not that token. Keep the verification
file available but excluded from the sitemap. `404.html` is also excluded and
marked `noindex`; it offers routes back to useful content.

The introduction explains the application beside a real library screenshot, with
a download link. A short developer note explains the project's two years of
personal research and reverse engineering, with a link to the source and research.
Beside it, `images/ipod-workbench.jpg` is the developer's supplied photograph.
The original image is retained intact; CSS crops its display around the iPods and
exposed parts. A visible caption identifies the workbench. The photograph sits
below the note on smaller screens and is separate from the screenshot viewer.
An in-page index links to that note, features, supported iPods, downloads,
migration, and questions. Keep headings descriptive
and copy practical: name the action or feature and explain any relevant limit.
Use modest type, ordinary links, and compact spacing throughout the site.

Development support appears with the community links near the end of the page.
That invitation, Donate in the navigation, and the footer support link share
`donation_url` in `_config.yml`. A small invitation to star the project sits beside
the installation notes, with a Shields.io image showing the repository's star
count. The badge and prompt link directly to `repository_url`; no extra script is
needed. On smaller screens, the invitation follows the notes.

`tokens.css` and `theme.css` own the shared colors and typography. `iop2.css`
contains the scoped IOP2 layout and consumes the existing `site.css` foundation.
The layout loads the readable CSS, `theme.js`, and `screenshot-viewer.js` directly;
older `.min.*` assets are retained but are no longer runtime inputs.

The shared layout loads `tokens.css` before `site.css`, then `theme.css` and
`iop2.css`. Every local stylesheet and script URL includes the same Jekyll build
timestamp (`?v=...`) so a newly deployed page requests fresh assets even when a
browser still caches files from an earlier deployment. Keep these URLs versioned
and load shared styles through the layout rather than unversioned CSS imports.

The Sync showcase uses two columns on wider screens and one on small screens.
Each explanation sits above its screenshot: media folders, media selection,
Sync Review, and conversion settings. The other product-tour sections are separate.

Screenshot buttons open a native modal dialog. It supports actual-size zoom,
scrolling, Escape, backdrop dismissal, and returning focus to the clicked image.
Screenshot captions remain available to screen readers but are visually hidden
both on the page and in the dialog. Image alternative text is retained.
The header uses `iopenpod-icon-256.png`, an unchanged copy of the application's
256 px master in `src/iOpenPod/assets/icons/`. Keep the existing artwork and its
creator permission recorded in that directory's `DJShott-icon.txt`.

The monochrome platform marks in `_includes/platform-icon.html` use the Microsoft
four-square mark (for Windows 11), Apple, and Linux SVGs from
[Font Awesome Free 6.7.2](https://github.com/FortAwesome/Font-Awesome/tree/6.7.2/svgs/brands)
by Fonticons, Inc., under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Their paths are unchanged; presentation and accessibility attributes are added.
Keep the embedded attribution comments. The SVGs inherit the page's text color
and are decorative because the adjacent headings already name each platform.

With Jekyll and `jekyll-sitemap` installed, run from the repository root:

```shell
jekyll serve --source website --destination .scratch/website-preview
```

Preview `/iOpenPod/` and `/iOpenPod/install-help/`. Check light and dark appearance,
keyboard navigation, disclosure controls, and widths 320, 375, 414, 768, and 1280 px.
For a root-hosted site, override `baseurl` with an empty string and rebuild.

With Playwright available to Node and Google Chrome installed, test the screenshot
viewer against that preview:

```shell
node tests/website/screenshot-viewer.cjs http://127.0.0.1:4000/iOpenPod/
node tests/website/navigation.cjs http://127.0.0.1:4000/iOpenPod/
```

This checks every screenshot in both themes, mobile and desktop sizes, keyboard
focus, zoom, all dismissal methods, unwanted downloads, and logo pixel density.
Navigation checks cover all content pages, responsive header links, rounded images,
single-line control labels, the in-page index, and synchronized theme controls
with keyboard activation and saved preferences.

## Migration and FAQ content

The homepage restores migration and FAQ topics from the Original iOpenPod website,
with answers adapted to the current behavior and release status. Keep platform,
device, backup, and media-tool claims consistent with the setup guide.

`_data/faq.json` is the single source for the visible FAQ disclosures and the
`FAQPage` JSON-LD in `_layouts/default.html`. The homepage opts in with
`include_faq_schema: true`; pages without the visible FAQs must not opt in.
Keep answers available in the rendered HTML and structured data identical.
Structured data describes the content; it does not guarantee search placement.
Google retired FAQ rich results in May 2026
([Search documentation updates](https://developers.google.com/search/updates)).
The visible FAQs remain useful to readers; their matching schema is not an
acquisition promise.

After building, validate the FAQ content and structured data together:

```shell
uv run python tests/website/check_seo.py .scratch/website-preview/iOpenPod
```

This also validates unique metadata, canonical URLs, social-image references,
software and breadcrumb markup, sitemap coverage, robots, local images, and
internal links and fragments. CI builds and checks both the custom-domain site
and an isolated `/iOpenPod` hosting variant, then uploads only the production
build. Run the browser navigation checks after changing links, headings, or layout.

See the [discoverability research](../docs/research/iopenpod-discoverability.md)
for source-backed intent selection and measurement guidance. Keep account exports,
traffic baselines, outreach drafts, and rollout work items in ignored `.scratch/`.
Updating this site or the repository README does not republish the PyPI description;
that follows the normal application release process.

## Maintain download and update instructions

`_data/distribution.json` is the source for platform labels, release channels, and
the latest native release link. Windows x64, Apple Silicon, Intel Mac, and Linux x64
downloads point to [GitHub’s latest release](https://github.com/TheRealSavi/iOpenPod/releases/latest).
Microsoft Store is available at
[the iOpenPod listing](https://apps.microsoft.com/detail/9P2LXCHHWLG9)
(product ID `9P2LXCHHWLG9`). PyPI is available at
[the iOpenPod package page](https://pypi.org/project/iopenpod/).
Mac App Store, Flathub, and Snap Store remain `planned` with a null URL.

The homepage uses Microsoft's hosted `ms-store-badge` component for the Store
channel, with direct launch, automatic theme, large size, English text, and hover
animation, displayed at a compact 161 × 44 pixels. The product ID lives beside the
listing URL in `distribution.json`.
The text link remains available if the component script cannot load or JavaScript
is disabled. The badge scales down to fit narrow screens.

The homepage and setup guide share the native download URLs from this data file.
`native_release.url` and each native channel URL use `/releases/latest` so new
releases do not require link edits. Asset filenames currently include a release
number, so links open the latest release page and instructions identify each
platform's filename ending. Do not construct `/releases/latest/download/` links
unless a matching stable asset name is actually published.

Use “latest” in the README and website instead of naming or pinning an iOpenPod
version, including in installation commands and structured data. OS and Python
requirements may still name their required versions. `release_status` supplies the
structured-data release note; update it and `status_date` when availability changes.

First installs use the Windows ZIP containing only `iOpenPod.exe`, the two macOS
DMGs, and the complete Linux tar.gz folder. Windows archive names use `x86_64`.
macOS ZIPs include `sparkle-update` in their names and are reserved for Sparkle;
direct manual installations to the DMGs. Document the writable fixed-NTFS
location for Windows, Applications for macOS, and the writable complete folder
with its top-level launcher for Linux. Preserve the current OS requirements and
macOS signing guidance from the release notes.

GitHub downloads check at launch and through Settings → About. Windows and Linux
use **Update now**, then **Restart to install**; macOS uses the built-in updater's
prompts. Older builds without working in-app updates need a manual upgrade.
Keep the homepage, setup guide, and `_data/faq.json` consistent with
[Application updates](../docs/app-updates.md). Application update feeds live on
the separate `update-feed` branch; publishing this website does not publish or
renew those feeds.

Only set a channel to `available` when its latest artifact or listing is
publicly accessible and its packaging acceptance is complete. Set `url` to the
verified artifact or listing URL in the same edit. Both values are required to
render a link. Verify the latest release contains each advertised native target;
do not display a store badge for an unpublished listing.

When a channel launches, update the availability copy in both pages, the root
README, FAQ answers, and site/page descriptions. Also update
`release_status` and `status_date` in the data file. Keep unreleased channels
marked planned; a published Windows build does not establish Mac or Linux support.

PyPI instructions link to uv’s installation guide, then show
`uv tool install iopenpod` to select the latest published package. Keep this route
concise; do not duplicate uv’s setup instructions or add alternative installers.
It is one application distribution.

The root README uses absolute screenshot and documentation URLs so the package
description works on PyPI. These URLs and `_config.yml`’s `source_url` name the
`main` development branch. Confirm anonymous access to every
image and to the corresponding source, support, and license pages.

## Refresh screenshots

The current set contains ten user-provided Windows screenshots captured on
2026-10-03. They show a personal iPod and media library, including actual album
artwork and photos. These are not the synthetic store-kit captures.

Use descriptive asset names and lossless WebP encoding (method 6). Keep each
complete capture at its original dimensions; do not resize it, draw replacement
UI, or add fake window frames. Set the matching width and height on each
`product-shot.html` include so the page reserves the correct image proportions.

| Original capture | Website asset |
| --- | --- |
| `Screenshot 2026-10-03 082040.png` | `screenshots/iop2/album-library.webp` |
| `Screenshot 2026-10-03 082421.png` | `screenshots/iop2/media-folders.webp` |
| `Screenshot 2026-10-03 082541.png` | `screenshots/iop2/sync-media-selection.webp` |
| `Screenshot 2026-10-03 082621.png` | `screenshots/iop2/sync-change-review.webp` |
| `Screenshot 2026-10-03 082631.png` | `screenshots/iop2/audio-transcoding-settings.webp` |
| `Screenshot 2026-10-03 082709.png` | `screenshots/iop2/track-metadata.webp` |
| `Screenshot 2026-10-03 082716.png` | `screenshots/iop2/track-artwork.webp` |
| `Screenshot 2026-10-03 082750.png` | `screenshots/iop2/backups.webp` |
| `Screenshot 2026-10-03 082816.png` | `screenshots/iop2/smart-playlist.webp` |
| `Screenshot 2026-10-03 083318.png` | `screenshots/iop2/photo-albums.webp` |

Record the capture date, source, dimensions, encoding, and input/output SHA-256
hashes in `screenshots/iop2/manifest.json`. Inspect every image after conversion.
Use the same assets in the homepage and root README, and keep their alternative
text and captions accurate. The social preview uses `album-library.webp`.
The separate synthetic capture script remains available for store-kit work; it
does not reproduce this personal-library set. Older Original iOpenPod screenshots
remain excluded from the published site.

## Product and distribution evidence

Use the current application, [project context](../CONTEXT.md),
[packaging guide](../docs/packaging.md), and
[media-tool setup](../docs/media-tools.md) when updating copy. Do not infer store
approval from a candidate package. FFmpeg/FFprobe remain separately installed;
Chromaprint is optional, and confined packages need independently verified access.
