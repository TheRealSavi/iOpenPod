# iOpenPod 2 website

The Jekyll site in this directory describes iOpenPod 2 only. It shares the current
application screenshots with the root README. Existing routes and GitHub Pages
project hosting are retained; `relative_url` keeps links valid under `/iOpenPod`
and when `baseurl` is empty for a custom domain.

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

The Sync showcase alternates three compact screenshot-and-text rows on desktop:
media selection, Sync Review, and conversion settings. On smaller screens each
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
```

This checks every screenshot in both themes, mobile and desktop sizes, keyboard
focus, zoom, all dismissal methods, unwanted downloads, and logo pixel density.

## Migration and FAQ content

The homepage restores migration and FAQ topics from the Original iOpenPod website,
with answers adapted to the current 2.0 behavior and release status. Keep platform,
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

## Activate a release channel

`_data/distribution.json` is the source for platform labels and release channels.
Native Windows, Apple Silicon, Intel Mac, Linux, PyPI, Microsoft Store, Mac App
Store, Flathub, and Snap Store entries start as `planned` with a null URL.

Only set a channel to `available` when its actual **2.x** artifact or listing is
publicly accessible and its packaging acceptance is complete. Set `url` to the
verified artifact or listing URL in the same edit. Both values are required to
render a link. Do not use a generic latest-release redirect that could point at
a 1.x build, or display a store badge for an unpublished listing.

When a channel launches, update the availability copy in both pages, the root
README, and the layout’s structured-data release note. Also update
`release_status` and `status_date` in the data file. Keep unreleased channels
marked planned; a published Windows build does not establish Mac or Linux support.

The Python example uses `iopenpod>=2,<3` and Python 3.12. Preserve that major-version
constraint. The package name stays `iopenpod`; it is one application distribution.

The root README uses absolute screenshot and documentation URLs so the package
description works on PyPI. These URLs and `_config.yml`’s `source_url` name the
`2.0` development branch.
Before publishing, replace that ref with the public 2.x release tag or another
verified, durable ref containing these images. Confirm anonymous access to every
image and to the corresponding source, support, and license pages.

## Refresh screenshots

From the repository root on Windows:

```shell
uv run --locked python -m scripts.capture_store_screenshots --output .scratch/website-iop2-captures
```

This uses real application widgets with isolated settings, a virtual iPod, fictional
media, and original geometric artwork. It does not read a personal library or
write to a physical iPod. Keep complete captures; do not draw replacement UI or
add fake window frames. Convert the seven mapped PNGs to WebP at quality 92,
method 6, retaining their 1920 × 1080 dimensions:

| Capture | Website asset |
| --- | --- |
| `01-album-library.png` | `screenshots/iop2/albums.webp` |
| `02-album-details.png` | `screenshots/iop2/album-details.webp` |
| `03-playlists.png` | `screenshots/iop2/playlists.webp` |
| `04-photo-library.png` | `screenshots/iop2/photos.webp` |
| `05-sync-review.png` | `screenshots/iop2/sync-review.webp` |
| `07-sync-selection.png` | `screenshots/iop2/sync-selection.webp` |
| `08-transcoding-settings.png` | `screenshots/iop2/transcoding-settings.webp` |

Record the capture date, source, dimensions, encoding, and input/output SHA-256
hashes in `screenshots/iop2/manifest.json`. Inspect every image after conversion.
All public pages and the README must reference this IOP2 set. Older screenshot
files remain in the repository for history; exclude them from the published site.

## Product and distribution evidence

Use the current application, [project context](../CONTEXT.md),
[packaging guide](../docs/packaging.md), and
[media-tool setup](../docs/media-tools.md) when updating copy. Do not infer store
approval from a candidate package. FFmpeg/FFprobe remain separately installed;
Chromaprint is optional, and confined packages need independently verified access.
