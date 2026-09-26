# Distribution licensing

iOpenPod uses **GPL-3.0-or-later**; see the [license grant](../COPYING.md) and
[full text](../LICENSE). The owner authorized this choice to retain the current
dependencies while offering a free application with optional donations.
See [ADR-0080](adr/0080-distribute-iopenpod-under-gplv3-or-later.md).

## What this permits

The GPL permits distributing the app for free, charging for copies, and accepting
voluntary support. It also permits recipients to modify and redistribute it.
Distribution of covered binaries brings source and notice obligations. Keeping a
public repository is useful, but the exact released source and required build
materials must remain available. See the [GNU guidance on selling free software](https://www.gnu.org/philosophy/selling.en.html)
and [GPLv3 sections 4-6](https://www.gnu.org/licenses/gpl-3.0.html).

DJShott's application icon uses the creator's separate permission in
by it.
Dependencies and other separately licensed material keep their own terms; this decision does not relicense
them.

## Why GPLv3 fits the current bundle

- [Mutagen](https://mutagen.readthedocs.io/en/latest/) is GPL-2.0-or-later and is
  imported by the application. Its "or later" option permits use under GPLv3.
- PySide6 and Qt have component-specific licensing options. The Windows bundle
  excludes unused Qt PDF and Virtual Keyboard plugins. Applicable open-source
  license texts and upstream third-party attributions are supplied from the
  matching Qt and PySide6 6.11.2 sources, supplementing the incomplete wheel notices.
- GPLv3 for the application does not settle every dependency obligation. Review
  the exact collected components and their GPL-compatible license options. Retain
  BSD, MIT, Apache, MPL, LGPL, and other applicable notices and source obligations.

## Before distributing a binary

1. Record the release commit, version, platform, architecture, dependency inventory,
   and binary SHA-256. Build from that recorded source with the locked environment.
2. Publish corresponding source for the application and covered bundled components,
   including modifications, required build scripts, configuration, and installation
   information where required. Match the actual library binaries and native build
   options. A Python sdist or `uv.lock` alone does not supply the native libraries'
   corresponding source. Prefer downloadable source archives clearly linked with
   the binary release; confirm the distribution arrangement satisfies GPLv3 section
   6 rather than relying on an unmaintained upstream link or an informal promise.
3. Include the full license texts, copyright notices, and required attribution in
   every artifact. The collector in `scripts/package_app.py` is only an inventory
   aid. Resolve missing notices and inspect native libraries, Qt plugins, Python,
   the PyInstaller bootloader, and multimedia codecs as well as Python packages.
4. Verify the provenance and redistribution terms of every bundled library and
   asset. FFmpeg, FFprobe, and Chromaprint's fpcalc executables are user-installed
   and excluded from the package; their binary redistribution is outside this
   release. Qt's FFmpeg playback libraries remain bundled and still require review
   of their exact build configuration, notices, and source obligations. Do not ship
   a nonfree FFmpeg build. See [FFmpeg legal information](https://ffmpeg.org/legal.html).
5. Ensure the installer, store terms, and any DRM do not remove the rights granted
   by the component licenses. The Mac App Store requires a separate compatibility
   review; adopting GPL for this project does not override store restrictions or
   let us relicense third-party GPL code. Qt highlights store-distribution issues
   in its [open-source obligations](https://www.qt.io/development/open-source-lgpl-obligations).

## Windows audit materials

The native bundle includes `licenses/upstream/`, copied from
[`packaging/third-party`](../packaging/third-party). Its pinned source manifest,
extracted full notice texts, and provenance hashes supplement the installed Python
package metadata. This covers the actual Qt FFmpeg 7.1.5 playback build, Qt/PySide6,
PyWinRT, Python and native dependencies, Wasmtime and its Rust dependencies, and
the numerical-analysis runtime. LGPL/GPL source archives accompany the application
source in the prepared Store kit. Runtime and asset exceptions remain separate
from the application's GPL grant.

The SoundFile wheel's static codec provenance could not be established precisely.
The Windows package instead uses a source-built libsndfile 1.2.2 with external
codecs disabled. Its build record, patch, source, compiler inputs, and reproducible
build script are retained. This library supports transitive analysis imports;
iOpenPod's media decoding continues through user-installed FFmpeg. Qt playback
libraries remain included. No FFmpeg, FFprobe, or fpcalc executable is bundled.

Original vector device illustrations replace vendor-extracted device images. The
podcast directory supplies text and feed URLs; newly subscribed artwork comes from
the publisher's feed. DJShott, Dylan Staley, libgpod, and gtkpod receive visible
credit. The icon permission does not assert a broader standalone artwork license.

The release record identifies the exact packaged payload and matching source
archives. Publishing and anonymously verifying those source downloads and public
privacy/support/license pages remains necessary before public binary distribution.
A Windows App Certification Kit pass does not substitute for those obligations.

## Microsoft Store and donations

Set the app price to free. In Partner Center, use **Additional license terms** to
provide a stable public page containing the iOpenPod license grant, full GPL text,
third-party notices, and release-specific source links. Publish and verify that
page before submitting; do not leave a placeholder URL or assume the default
proprietary license terms are suitable. Microsoft documents this field in
[additional information for MSIX apps](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/add-additional-information).

The existing README/website links and **Settings > About > Donate** open Ko-fi for
optional support. No payment or feature unlock is added by this licensing change.
Verify that provider's checkout, disclose the donation link in Partner Center as
required, and keep the donation optional with no digital reward. Review
[Store policy 10.8](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies#108-financial-transactions)
for transaction-provider identification, consent, and payment requirements. Do not
describe personal developer support as a tax-deductible charitable contribution.

These are engineering release requirements, not a guarantee of legal compliance or
store approval. Resolve uncertain distribution terms with qualified legal advice
before release.
