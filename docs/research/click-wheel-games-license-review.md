# Click wheel games: upstream license and download rights

Reviewed: 2026-11-03. Local baseline:
`acccf7de140867301b1adbad3cbd009747073437`.

## Finding and scope

Olsro's repository has a permissive MIT license. That addresses material its
authors have authority to license; it does not establish permission from the
commercial games' rights holders. The current direct-download feature therefore
cannot be marked legally cleared from that license alone. Bundled artwork and
the Game Authorization Store also need separate rights analysis. This is a
source-based engineering review using United States federal copyright law as
the baseline, not a legal opinion or a finding that upstream infringes. Other
jurisdictions and applicable software agreements need separate consideration.

The review covers the upstream license, README, release metadata, repository
file inventory, and the local download, asset, attribution, and packaging paths.
It does not audit every game EULA or publisher's rights chain, inspect notices
inside the 1.8 GB release archive, or audit a native distribution. No new game
archive was downloaded. Absence of permission in the reviewed evidence does not
prove that no permission exists elsewhere.

## Upstream evidence

The reviewed `main` and `version16` tag both resolve to
[`173fa133b67860475c89a7b22bbb04744a630672`][upstream-tree].
The [LICENSE][upstream-license] names Olsro, copyright 2024, and uses standard
MIT terms. It permits use, modification, redistribution, sublicensing, and sale,
conditioned on retaining the copyright and permission notice in copies or
substantial portions. The disclaimer is also retained in our complete copy.
There is no noncommercial, no-downloader, or separate-approval clause in that
license. The FSF identifies this MIT/Expat form as
[GPL-compatible][fsf-mit], so it does not inherently conflict with iOpenPod's
GPL-3.0-or-later code.

The [README][upstream-readme] directs users to download the game archives and
describes the games as unavailable for purchase and abandonware. The
[version16 release][upstream-release] supplies the asset used by iOpenPod and an
Internet Archive alternative. Neither text supplies a title-by-title publisher
license. No separate game-redistribution grant was identified in those texts or
the repository's named license files. The README's preservation rationale is
not itself a grant by Apple or the game publishers.

The [release API record][release-api] reports:

| Field | Observed value |
| --- | --- |
| Asset | `iPod.Games.Files.7z` |
| Release | `version16`, published 2025-10-03 |
| Size | 1,800,542,124 bytes |
| SHA-256 | `c532208b700e10edf621ec65cf188d546a2a4f043106bad3dd53caf9ed14df06` |

These match the local [download manifest][download-manifest]. This is integrity
and source-provenance evidence, not rights evidence. GitHub's
[terms, sections C and D][github-terms], require lawful use and authority for
third-party content; public availability does not establish such authority.

Merely linking to a release is different from copying upstream MIT-covered
code or documentation. This audit did not establish that the existing download
link alone triggered MIT notice obligations. Retaining the complete notice is
prudent provenance housekeeping; a credit line alone would not satisfy MIT
where covered material is copied. Separate approval is not required by MIT for
uses within its grant. Confirmation of automated-download expectations can still
help with upstream coordination, but cannot supply publishers' missing rights.

## What iOpenPod currently does

| Area | Observed implementation | Licensing implication |
| --- | --- | --- |
| Collection download | [Manifest][download-manifest] and [transport][download-code] fetch the whole pinned upstream archive into persistent Host storage after Install Games. | Direct hosting avoids bundling the executables; it still causes copies to be made. |
| Download hygiene | The transport identifies `iOpenPod-Games/1`, bounds URLs and sizes, verifies SHA-256, resumes partial downloads, and reuses a completed cache. | Useful source and bandwidth controls, without a copyright grant. |
| Cover artwork | [Catalog loader][catalog-code] decodes embedded `ArtworkBase64` from the bundled catalog's 56 entries. | Game artwork is shipped with the app and needs its own provenance and permission or other legal basis. |
| Game Authorization Store | [Source loader][authorization-code] loads `classic65-IC-Info.sidb`; [source metadata][authorization-metadata] records device identity, firmware, and a digest. | Those fields establish technical origin/integrity, not permission to distribute account/key material. |
| Packaging | [Python build configuration][build-config] and [native spec][native-spec] exclude game archives but retain the catalog and source store. | The current asset directory has four files: catalog, download manifest, store, and store metadata. Archive exclusion is not an audit of every third-party asset. |
| Credit before this review | [README][local-readme] and [Settings About][settings-code] name Olsro, link the project, and identify the download source. | Existing credit is useful. The central acknowledgements and license materials lacked this upstream notice and an explicit game-material scope statement. |

[ADR-0208][adr-0208] accepts the bundled authorization source and standalone
codec; [ADR-0211][adr-0211] accepts whole-collection downloading with executable
payloads outside the distribution. The code follows those decisions. Neither ADR
records publisher permission or an access-control legal analysis. This is an
unresolved licensing question alongside the accepted implementation, not a code
versus architecture discrepancy. Technical Game Authorization Store preparation
does not establish that a recipient legally owns a game.

## Ownership and abandonware

Preserving a copy does not transfer its copyright. Ownership of a copy and
copyright are distinct under [17 U.S.C. 202][usc-202]. Olsro can have rights in
original documentation, scripts, and qualifying original selection or arrangement.
[Section 103][usc-103] limits compilation/derivative rights to contributed
material and leaves underlying rights separate. Thus neither ownership of the
games by Olsro nor an absence of rights in his own work should be assumed.

The games' rights holders retain reproduction and distribution rights subject
to legal limitations under [section 106][usc-106]. Commercial withdrawal does
not expire the copyright terms in [section 302][usc-302]. Calling a title
abandonware, or its developer becoming defunct, is insufficient evidence that
it is public domain. The present rights holder may require further research.

[Section 117][usc-117] provides conditional essential-use and archival copying
rights for an owner of a computer-program copy. The Copyright Office's
[backup FAQ][backup-faq] distinguishes those rights from public distribution
of backup copies. Prior purchase or an ownership checkbox is not, by itself,
evidence that an unrelated download source is authorized. Fair use is a separate,
fact-specific analysis under [section 107][usc-107]; preservation intent, free
distribution, donations, or disclaimers do not decide it on their own.

## Preservation and access controls

The published [37 C.F.R. 201.40(b)(19)][preservation-rule] exemption requires
lawfully acquired complete games. It permits certain restoration for personal,
local gameplay after necessary authentication servers cease operation. Its
institutional preservation routes require eligible libraries, archives, or
museums and restrict availability outside their physical premises. It does not
provide a general consumer permission to download a preserved collection.
Whether iPod authentication and a particular use qualify requires factual review.

These exemptions concern section 1201(a)(1) circumvention acts. They are not game
distribution licenses and do not generally exempt distribution of enabling
technology or services under sections 1201(a)(2) and (b). The bundled store, key
material, and transfer mechanism consequently require analysis distinct from the
game binaries. Interoperability under section 1201(f) is also conditional, not
automatic clearance for this workflow. See [17 U.S.C. 1201][usc-1201].

## Disposition and evidence still needed

This review retains the complete upstream MIT notice through the existing
`LICENSES/*.txt` distribution path, adds central credit, and explicitly excludes
third-party game material from iOpenPod's GPL grant. It changes no download,
installation, or authorization behavior and accepts no new architecture.

The existing [distribution licensing guide][licensing] requires asset provenance
review before release. For this feature, the missing evidence is specific:

1. **Game copies:** publisher/rightsholder permission covering the intended
   downloading and copying, or a documented legal assessment of another basis for
   this exact public workflow. Review relevant archive notices and title terms.
2. **Artwork:** source and rights evidence for the embedded covers, including
   display and redistribution. A catalog containing game names does not supply
   rights to the accompanying images.
3. **Authorization material and mechanism:** provenance, authority to distribute
   and use the supplied store, and an assessment of access-control law and
   applicable agreements. No key values or account contents are reproduced here.
4. **Upstream coordination:** if clarification is sought, distinguish Olsro's
   own contributions and hosting expectations from any actual authority to
   sublicense third-party games. No upstream contact was made for this review.

Until those questions are resolved, the defensible status is **upstream notice
retained; game-download and authorization rights unverified**. Keeping executables
external, giving credit, or adding a disclaimer does not close that gap. A
user-supplied lawful-copy workflow is a possible scope reduction to evaluate,
but would still need an authorization analysis and an explicit product/ADR
decision; it is not implemented or treated as automatic legal clearance here.

## Validation of the notice changes

The retained MIT text matches the fetched upstream LICENSE exactly. Targeted
Markdown lint and whitespace checks passed. A fresh wheel built successfully,
passed the existing `scripts/check_wheel.py` resource check, and contains the
exact new notice and updated licensing files. Native notice collection was
checked in source: `scripts/package_app.py` copies the project's `license-files`
patterns, including `LICENSES/*.txt`. No native installer was rebuilt, and
application behavior tests were not needed for these documentation/notice changes.

[upstream-tree]: https://github.com/Olsro/ipodclickwheelgamespreservationproject/tree/173fa133b67860475c89a7b22bbb04744a630672
[upstream-license]: https://github.com/Olsro/ipodclickwheelgamespreservationproject/blob/173fa133b67860475c89a7b22bbb04744a630672/LICENSE
[upstream-readme]: https://github.com/Olsro/ipodclickwheelgamespreservationproject/blob/173fa133b67860475c89a7b22bbb04744a630672/README.md
[upstream-release]: https://github.com/Olsro/ipodclickwheelgamespreservationproject/releases/tag/version16
[release-api]: https://api.github.com/repos/Olsro/ipodclickwheelgamespreservationproject/releases/tags/version16
[fsf-mit]: https://www.gnu.org/licenses/license-list.html#Expat
[github-terms]: https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#d-user-generated-content
[usc-103]: https://uscode.house.gov/us/usc/119-120/t17/s103/
[usc-106]: https://uscode.house.gov/us/usc/119-120/t17/s106/
[usc-107]: https://uscode.house.gov/us/usc/119-120/t17/s107/
[usc-117]: https://uscode.house.gov/us/usc/119-120/t17/s117/
[usc-202]: https://uscode.house.gov/us/usc/119-120/t17/s202/
[usc-302]: https://uscode.house.gov/us/usc/119-120/t17/s302/
[usc-1201]: https://www.copyright.gov/title17/92chap12.html
[backup-faq]: https://www.copyright.gov/help/faq/faq-digital.html
[preservation-rule]: https://copyright.gov/title37/201/37cfr201-40.html
[download-manifest]: ../../src/iOpenPod/assets/games/game-downloads.json
[download-code]: ../../src/iOpenPod/app/services/game_download.py
[catalog-code]: ../../src/iOpenPod/app/services/game_catalog.py
[authorization-code]: ../../src/iOpenPod/app/services/games.py
[authorization-metadata]: ../../src/iOpenPod/assets/games/source.json
[build-config]: ../../pyproject.toml
[native-spec]: ../../packaging/iOpenPod.spec
[local-readme]: ../../README.md
[settings-code]: ../../src/iOpenPod/GUI/pages/settings_page.py
[adr-0208]: ../adr/0208-prepare-game-authorizations-with-a-standalone-codec.md
[adr-0211]: ../adr/0211-download-the-game-collection-on-demand.md
[licensing]: ../licensing.md
