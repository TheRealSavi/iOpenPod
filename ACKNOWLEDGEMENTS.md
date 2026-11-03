# Acknowledgements

iOpenPod builds on years of work by the open-source iPod community.
Thank you to the people who made it possible to keep these devices useful.

## Dylan Staley — HASHAB

Special thanks to [Dylan Staley (@dstaley)](https://github.com/dstaley) for
[`hashab`](https://github.com/dstaley/hashab), including its C implementation and
WebAssembly module for the HASHAB calculation used by later iPod nano models.
iOpenPod uses that WebAssembly implementation; this is a direct contribution to
the app's device support.

The bundled `calcHashAB.wasm.b64` encodes the upstream module from commit
`f80d46432204c6238cad7d8ca3b3dd52ea66836b`. Its Unlicense notice is retained beside
the resource as `calcHashAB.NOTICE`.

## libgpod and gtkpod

An honorary thank-you to the authors, maintainers, and contributors of
[libgpod](https://github.com/gtkpod/libgpod) and
[gtkpod](https://github.com/gtkpod/gtkpod). Their implementations, documentation,
and accumulated understanding of iPod databases and device behavior have been
valuable references for iOpenPod. Their work helped establish the open-source
iPod ecosystem this project learns from and hopes to continue.

## dotm5 — Genius-Mix-Research

Thanks to [dotm5](https://github.com/dotm5) for their
[Genius-Mix-Research](https://github.com/dotm5/Genius-Mix-Research) repository. Its
research helped iOpenPod understand native Genius Data formats.

## DJShott — application icon

Thank you to **DJShott** for designing and contributing the application icon and
offering it for future iOpenPod updates. It is used with permission; the creator's
statement and asset-specific scope are preserved in
[`DJShott-icon.txt`](src/iOpenPod/assets/icons/DJShott-icon.txt).

## Olsro — iPod Clickwheel Games Preservation Project

Thanks to [Olsro](https://github.com/Olsro) and the project's contributors for
organizing and preserving iPod click wheel games through the
[iPod Clickwheel Games Preservation Project](https://github.com/Olsro/ipodclickwheelgamespreservationproject).
iOpenPod downloads its game collection from that project's version16 release.

The upstream MIT notice is retained in
[`Olsro-ipodclickwheelgamespreservationproject.txt`](LICENSES/Olsro-ipodclickwheelgamespreservationproject.txt).
It records the repository's license, not permission from the games' rights holders.
The commercial games, their artwork, and Game Authorization Store material are
not relicensed under iOpenPod's GPL grant. See the
[license review](docs/research/click-wheel-games-license-review.md) for the scope
of the upstream grant and unresolved rights questions. Credit does not imply
endorsement by Olsro, contributors, Apple, or game publishers.

## The wider community

The macOS standalone updater uses [Sparkle](https://sparkle-project.org/). Its full
upstream license and component notices are retained in
[`sparkle-2.10.0-NOTICES.txt`](packaging/third-party/notices/sparkle-2.10.0-NOTICES.txt)
and copied into native distributions.

Thank you to the contributors, testers, researchers, translators, and dependency
maintainers who share their work and help keep iPods usable. These acknowledgements
express our gratitude; they do not imply endorsement or replace component license
and attribution notices.
