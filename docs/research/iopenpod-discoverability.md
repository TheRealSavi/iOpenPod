# iOpenPod discoverability research

Research date: 2026-10-18. This records the initial public-site and source audit,
before the accompanying optimization changes. Priorities are hypotheses based on
product fit and observed content gaps, not measured search volume or ranking
difficulty. No private Search Console, Bing Webmaster Tools, analytics, or store
acquisition data was available to this research pass.

## Findings that affect the work

1. **Explain the product before asking visitors to explore it.** The initial
   homepage title and H1 use the slogan; the first paragraph promises any file
   format. Replace that absolute claim with the actual iPod manager, supported
   media, platform, and conversion proposition. Keep the slogan as supporting
   branding. Google recommends distinct, descriptive titles and warns against
   keyword repetition. Source: [initial homepage](https://iopenpod.com/) and
   [Google title guidance](https://developers.google.com/search/docs/appearance/title-link).
2. **Useful acquisition content is the largest visible gap.** At the start of the
   audit, `website/` contains two substantive published pages: the product tour
   and install help. Sync without iTunes, FLAC conversion, and device compatibility
   are mostly homepage FAQ answers or sections. Give those distinct tasks useful
   pages with real workflow screenshots, constraints, and a route to installation.
   Do not create a near-identical page for every device, platform, or keyword.
   Sources: [site source](https://github.com/TheRealSavi/iOpenPod/tree/main/website)
   and [Google content guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide).
3. **Trust depends on precise compatibility evidence.** Public downloads and
   extensive implemented workflows coexist with the foundation-stage wording in
   `CONTEXT.md`. The product target is not a certification that every device,
   firmware, feature, and operating-system combination has been physically tested.
   Preserve this distinction in acquisition copy. The reviewed source explicitly
   excludes iPod touch and shuffle, leaves macOS 12.3 execution validation pending,
   and requires model-aware conversion. Sources: [project context](../../CONTEXT.md),
   [Sync execution](../adr/0076-execute-reviewed-sync-through-storage.md),
   [current transcoding](../../src/iOpenPod/app/media/transcoding.py), and
   [late-device compatibility decision](../adr/0147-restore-late-ipod-firmware-write-compatibility.md).
4. **The FAQ rich-result guidance needs updating.** Google stopped showing FAQ rich
   results on May 7, 2026 and removed the documentation in June. The earlier
   government/health-only explanation in `website/README.md` is stale. Keep useful
   visible FAQs; maintaining accurate FAQ markup is a separate choice, not a
   Google rich-result growth strategy.
   Source: [Google documentation changelog](https://developers.google.com/search/updates).

## Observed public baseline

Public searches for `iOpenPod`, `iOpenPod iTunes`, and `TheRealSavi/iOpenPod`
returned the product website, GitHub repository, PyPI package, and existing
community discussion. This establishes discoverability in the search tool's
sample, not an engine-specific rank, complete index inventory, or traffic total.
Some results still surfaced the older `docs/index.html` and older installation
details. Keep current installation pages internally prominent and request recrawls
after deployment; a search excerpt alone does not establish that a live page is
still wrong. Sources: [website](https://iopenpod.com/),
[repository](https://github.com/TheRealSavi/iOpenPod),
[PyPI](https://pypi.org/project/iopenpod/), and
[historical source URL](https://github.com/TheRealSavi/iOpenPod/blob/main/docs/index.html).

The old [GitHub Pages URL](https://therealsavi.github.io/iOpenPod/) resolved to the
custom domain in the research browser. Source already configures canonical URLs,
Open Graph, Twitter cards, WebSite/SoftwareApplication/WebPage markup, a sitemap
plugin, descriptive screenshot alternatives, and an allow-all robots file with a
sitemap reference. These are existing foundations, not new achievements. The web
research tool could not fetch the live XML sitemap or robots file; their deployed
status requires a direct browser or HTTP check. A verification file in source
does not prove that a Search Console property is currently verified.

Source evidence: [layout](../../website/_layouts/default.html),
[configuration](../../website/_config.yml), [robots](../../website/robots.txt),
[website guide](../../website/README.md).

## Intent map

Priority reflects closeness to the product's actual capabilities. Query phrases
are editorial targets to validate with Search Console, not volume estimates.

| Priority | Search intent and example phrases | Useful destination and proof | Visitor's next action |
| --- | --- | --- | --- |
| First | `iPod manager`, `iTunes alternative for iPod`, `iOpenPod download` | Homepage: clear category, platforms, existing screenshots, supported families, free/open-source identity | Choose an available download |
| First | `sync iPod without iTunes`, `add music to iPod without erasing` | [First-Sync guide](../../website/guides/sync-ipod-without-itunes.md): mounted device, Backup Snapshot, selection, Sync Review, unchecked removals, safe eject; distinguish automatic Library edits from reviewed Sync | Follow installation and first Sync |
| First | `FLAC to iPod`, `FLAC to ALAC iPod` | [Conversion guide](../../website/guides/flac-to-ipod.md): supported source inspection, model-dependent output, FFmpeg/FFprobe requirement, actual settings screenshot; distinguish conversion from native firmware playback | Configure media tools and conversion |
| First | `iPod classic software`, `iPod nano sync`, `iPod mini manager` | [Compatibility guide](../../website/guides/ipod-compatibility.md): device families, excluded devices, feature variation, OS requirements, how to report tested model/firmware/version | Confirm fit before downloading |
| Next | `Linux iPod sync`, `iPod manager Windows 11`, `iPod manager Mac` | [Platform selection guide](../../website/guides/ipod-manager-windows-mac-linux.md): one comparison of installation routes and requirements, linked to detailed install help | Complete installation |
| Next | `iPod not detected`, `iOpenPod Mac cannot open`, `iPod sync missing FFmpeg` | [Detection guide](../../website/guides/ipod-not-detected.md) and installation troubleshooting, grounded in current app behavior and official OS guidance | Resolve setup or submit a useful issue |
| Later | `iPod scrobble Last.fm`, `ListenBrainz iPod`, `iPod podcasts without iTunes` | Feature guides with evidenced workflow, service-specific limits, and fresh screenshots | Try a supported feature |

The first-Sync and conversion topics have implementation evidence in
[install help](https://iopenpod.com/install-help/),
[Sync execution](../adr/0076-execute-reviewed-sync-through-storage.md), and
[current media preparation](../../src/iOpenPod/app/media/transcoding.py). Scrobbling has a distinct
[documented contract](../scrobbling.md). Do not advertise Spotify/Apple Music
subscription extraction, DRM removal, iPhone management, or unsupported firmware
playback as solutions to adjacent queries.

The accompanying source changes add the [guide directory](../../website/guides/index.html)
and these five canonical routes. Source creation does not establish deployment,
indexing, or availability of a newly documented behavior in the latest binary:

- `/guides/sync-ipod-without-itunes/`
- `/guides/flac-to-ipod/`
- `/guides/ipod-compatibility/`
- `/guides/ipod-manager-windows-mac-linux/`
- `/guides/ipod-not-detected/`

Check the published guides and the current release separately before referring to
them in announcements. Website documentation updates are not an application release.

## Positioning and acquisition

Apple's current support directs users to Finder, iTunes, or Apple Devices according
to the host system. Therefore, position iOpenPod around a specific iPod workflow,
cross-platform availability, and user-reviewed media selection; do not claim Apple
offers no way to sync an iPod. Source:
[Apple sync guidance](https://support.apple.com/en-au/108311).

Strawberry describes itself as a music player and collection organizer for
collectors; Clementine also emphasizes cross-platform music playback and library
features. Their own sites support an audience distinction, not claims that they
are universally broken or abandoned. Emphasize iOpenPod's iPod-specific workflow
and its own iPodDB implementation without implying automatic migration of another
manager's databases or settings. Sources:
[Strawberry](https://www.strawberrymusicplayer.org/),
[Clementine](https://www.clementine-player.org/), and
[iOpenPod architecture](../source_architecture.md).

Recommended acquisition work, with expected benefit still to be measured:

- **Strengthen existing discovery surfaces.** Keep GitHub About, topics, README,
  PyPI description, website, release notes, and available store listing consistent
  about devices, platforms, free licensing, and setup. Existing repository topics
  already include core iPod and iTunes-alternative terms; improve relevance rather
  than adding every adjacent technology. GitHub documents topics as a discovery
  mechanism: [repository topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).
- **Correct the existing AlternativeTo record.** Its public
  [iOpenPod information page](https://alternativeto.net/software/iopenpod/about/)
  still displayed MIT licensing, the old GitHub Pages address, and an unbounded
  conversion claim during this audit. Use GPL-3.0-or-later, the canonical product
  website, and model-dependent conversion wording, backed by the
  [license decision](../adr/0080-distribute-iopenpod-under-gplv3-or-later.md).
  Update the existing record rather than submitting another one. AlternativeTo's
  [FAQ](https://alternativeto.net/faq/) documents editing, excludes URLs from
  description text, and asks for clean official links without tracking parameters.
- **Publish original evidence.** A short screen recording of a first Sync and a
  maintained table of physically tested model/firmware/app-version combinations
  would help owners make a decision and give communities something worth citing.
  Separate reported, reproduced, and automated-only evidence. This is an editorial
  recommendation, not a claim that such a table already exists.
- **Answer real community questions.** Existing
  [iPod community discussion](https://www.reddit.com/r/ipod/comments/1rierq6/i_built_an_open_source_alternative_to_itunes/)
  contains questions about setup and device support. Treat comments as individual,
  dated reports, not product-wide test results. A maintainer can share the guide
  that answers a specific question, disclose involvement, and follow community
  rules. This research did not post messages or contact anyone.
- **Earn relevant references.** Offer tested workflow material to iPod restoration
  guides and open-source software catalog editors when it answers their readers'
  needs. Do not buy links, mass-post announcements, fabricate reviews, or produce
  duplicate comparison pages. Google's
  [spam policies](https://developers.google.com/search/docs/essentials/spam-policies)
  and [AI optimization guide](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
  favor useful original content over scaled variations and inauthentic mentions.

## Technical decisions worth preserving

- Give each substantive page its own title, description, canonical URL, visible
  main heading, and relevant internal links. Keep redirect and verification files
  out of the sitemap. Submit the canonical sitemap in both search consoles after
  deployment and inspect the new URLs. A sitemap is a discovery hint, not an
  indexing guarantee. Sources:
  [Google sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
  and [Bing sitemaps](https://www2.bing.com/webmasters/help/sitemaps-3b5cf6ed).
- SoftwareApplication markup can accurately include a free-price Offer and
  operating systems. Google's software rich-result eligibility also requires a
  real review or aggregate rating. Never reinterpret GitHub stars or download
  counts as ratings, invent reviewers, or promise rich results from schema alone.
  Source: [Google software markup](https://developers.google.com/search/docs/appearance/structured-data/software-app).
- Spend effort on readable, useful pages and discoverable links rather than meta
  keywords or `llms.txt`. Google does not use meta keywords, and its current AI
  guide says `llms.txt` does not improve or harm Google rankings. Sources:
  [SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)
  and [AI guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide).
- Preserve real screenshots and responsive layouts. Measure performance before
  making performance claims; this research did not collect Core Web Vitals or a
  reproducible Lighthouse score. No score or speed gain is inferred from source.
- Bing recommends IndexNow for changed URLs. It is an optional future publishing
  integration after ownership and deployment are established, not a prerequisite
  for this small site. Source:
  [Bing URL submission](https://www.bing.com/webmasters/help/URL-Submission-62f2860b).

## Measurement contract

Record the deployment date, then save a baseline of the preceding 28 complete
days in Google Search Console and Bing Webmaster Tools. Compare equivalent
28-day windows after recrawling, with device, country, and query group kept
consistent. At low volumes, retain raw counts and avoid interpreting tiny CTR
changes as reliable effects. Google defines impressions, clicks, CTR, and position
in its [measurement documentation](https://support.google.com/webmasters/answer/7042828).

| Question | Metric or evidence | Interpretation |
| --- | --- | --- |
| Can engines discover the guides? | Sitemap processing, URL inspection, selected canonical, indexed status | Deployment and submission do not prove indexing |
| Are new people finding the product? | Non-brand clicks and impressions, grouped by the intents above | Separate brand searches containing iOpenPod or TheRealSavi |
| Are relevant results appealing? | Page/query CTR alongside impressions and average position | Compare like-for-like queries; position and query mix influence CTR |
| Are visitors progressing? | Download/store outbound clicks, if deliberately instrumented | Clicks are not completed downloads or installations |
| Are downloads increasing? | Per-release, per-platform asset counts; store acquisition data if available | Exclude update-only assets where possible; downloads are not unique users |
| Is activation improving? | Voluntary setup feedback and categorized installation issues | Successful first Sync cannot be inferred from website traffic |

Do not add app telemetry as part of an SEO change. Search-console measurement can
start without it. Any future website analytics should have an explicit collection
scope and implementation decision. Review useful query/page evidence after four
weeks; revise weak titles or unclear instructions before creating more pages.
Search effects can take weeks or longer, and no ranking or user-growth outcome is
guaranteed: [Google assessment guidance](https://developers.google.com/search/docs/fundamentals/seo-starter-guide).
