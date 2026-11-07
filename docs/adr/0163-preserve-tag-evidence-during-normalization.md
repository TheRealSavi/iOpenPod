# ADR-0163: Preserve tag evidence during normalization

- Status: Accepted
- Date: 2026-10-21
- Amends: ADR-0026 normalization rules; draft and review guarantees are unchanged

## Context

[Issue #223](https://github.com/TheRealSavi/iOpenPod/issues/223) reports featured
artists crossing between Tracks' Sort Artist suggestions. The current normalizer
reproduces it: `Lead/Guest A` and `Lead/Guest B` become Artist `Lead`, after which
the sort pass chooses one collaboration's Sort Artist for both Tracks. This is a
policy error, not shared mutable state or incorrect Track identities.

Original iOpenPod's `src/iopenpod/gui/widgets/ipodTagNormalizer.py` on `1.x` uses
the same ordered passes. Its unconditional Album Artist unification also removes
unrelated artist credits, its prefix test misreads names such as `Lead Orchestra`
as collaborations, and its compilation inference treats same-name albums as one
release. Strict parity would preserve these mistakes. Supplied sort tags and
credits provide stronger evidence than a majority or alphabetical tie-break.

## Decision

Keep normalization pure, deterministic, cancellable, and bound to immutable Track
identities. The shared policy applies to Normalize Tags previews and optional Sync
normalization. Deliberately narrow the Original rules as follows:

- Preserve each nonempty custom sort value after whitespace cleanup. Article
  handling may change a redundant sort equal to its display value. Missing sorts
  may reuse exactly one distinct custom value for the same identity; conflicting
  values fall back to an article-aware display sort, without outvoting either
  supplied value. Sort Album evidence is scoped by Album Artist (or Artist when
  absent), and sort evidence never crosses media categories.
- A changed display identity cannot donate its former sort value to another
  Track. Artist sorts from titles carrying featured credits cannot donate either,
  including on subsequent scans after Artist has been simplified. This prevents
  collaboration-specific sorts from spreading to solo or other featured Tracks.
- On profiles that group by Artist, simplify a collaboration only when Album
  Artist is the complete leading credit followed by `feat`, `ft`, `featuring`,
  `with`, or an explicit `/`, `,`, `;`, `+`, or `&` separator. Bracketed markers are
  supported. Move the guest text intact into a nonempty Title, or reuse a matching
  existing featured credit. Preserve Artist if an existing featured Title differs,
  the Title is empty, or the relationship is unproven. Case-equivalent Album Artist
  spelling uses a deterministic frequency and lexical choice.
- A compilation requires an explicit compilation flag or a recognized Various
  Artists Album Artist. Propagate only inside the same named album and owner.
  Preserve a supplied named Album Artist; fill absent values or normalize Various
  Artists aliases where compilation evidence exists. A shared title alone and
  missing album titles never establish compilation membership.
- Disambiguate colliding album titles only when every involved Track supplies an
  Album Artist and there are multiple case-insensitively distinct owners. Do not
  invent an Unknown Artist suffix from missing evidence.
- Apply music grouping, compilation, and featured-credit rules only to Music.
  Podcasts, Audiobooks, and video still receive text and sort cleanup, without
  applying music album inference to their credits or titles.

## Consequences

Ambiguous tags can remain inconsistent until the user edits them. This trades some
automatic grouping for preservation of supplied metadata. Existing corruption
cannot be reliably reconstructed from a normalized Library; this change prevents
new guesses rather than inventing missing original credits.

The fourteen captured Original cases remain unchanged as historical evidence.
Four intentional differences are listed separately in
`tests/fixtures/normalization/safety-corrections.json`. Regression tests cover the
reported collaboration leak, preservation of unrelated credits and custom sorts,
compilation boundaries, profile differences, deterministic ordering, and repeated
normalization. Device persistence remains a separate reviewed Storage workflow.
