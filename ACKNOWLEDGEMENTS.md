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

## DJShott — application icon

Thank you to **DJShott** for designing and contributing the application icon and
offering it for future iOpenPod updates. It is used with permission; the creator's
statement and asset-specific scope are preserved in
[`DJShott-icon.txt`](src\iOpenPod\assets\icons\DJShott-icon.txt).

## The wider community

Thank you to the contributors, testers, researchers, translators, and dependency
maintainers who share their work and help keep iPods usable. These acknowledgements
express our gratitude; they do not imply endorsement or replace component license
and attribution notices.
