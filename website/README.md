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

The homepage hero includes a subtle background panel with an outlined heart, a
short development-support message, and a pill-shaped Ko-fi link beside the
introduction. This invitation, the compact Donate link in
the navigation, and the footer support link share `donation_url` in `_config.yml`.

The header’s Shields.io badges show GitHub stars and total release-asset downloads for
the whole iOpenPod project, including earlier releases. Downloads are not unique
or active users. Keep the labels accurate; badge counts
come from Shields.io and depend on that external service and its cache.

`tokens.css` and `theme.css` own the shared colors and typography. `iop2.css`
contains the scoped IOP2 layout and consumes the existing `site.css` foundation.
The layout loads the readable CSS, `theme.js`, and `screenshot-viewer.js` directly;
older `.min.*` assets are retained but are no longer runtime inputs.

The Sync showcase alternates four compact screenshot-and-text rows on desktop:
media folders, media selection, Sync Review, and conversion settings. On smaller screens each
image appears above its description. The other product-tour sections are separate.

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
Navigation checks cover both pages, responsive header links, rounded images,
the direct hero-to-Sync transition, and synchronized header/footer theme controls
with keyboard activation and saved preferences.

## Migration and FAQ content

The homepage restores migration and FAQ topics from the Original iOpenPod website,
with answers adapted to the current behavior and release status. Keep platform,
device, backup, and media-tool claims consistent with the setup guide.

`_data/faq.json` is the single source for the visible FAQ disclosures and the
`FAQPage` JSON-LD in `_layouts/default.html`. The homepage opts in with
`include_faq_schema: true`; pages without the visible FAQs must not opt in.
Keep answers available in the rendered HTML and structured data identical.
Structured data describes the content; it does not guarantee search placement or
FAQ rich results. Google limits those results to qualifying government and health
sites ([Google Search guidance](https://developers.google.com/search/blog/2023/08/howto-faq-changes)).

After building, validate the FAQ content and structured data together:

```shell
uv run python tests/website/check_seo.py .scratch/website-preview/iOpenPod
```

## Maintain download and update instructions

`_data/distribution.json` is the source for platform labels, release channels, and
the latest native release link. Windows x64, Apple Silicon, Intel Mac, and Linux x64
downloads point to [GitHub’s latest release](https://github.com/TheRealSavi/iOpenPod/releases/latest).
Microsoft Store is available at
[the iOpenPod listing](https://apps.microsoft.com/detail/9P2LXCHHWLG9)
(product ID `9P2LXCHHWLG9`). PyPI is available at
[the iOpenPod package page](https://pypi.org/project/iopenpod/).
Mac App Store, Flathub, and Snap Store remain `planned` with a null URL.

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
DMGs, and the complete Linux tar.gz folder. macOS ZIPs remain on the release page
for Sparkle updates and manual archive installs. Document the writable fixed-NTFS
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
