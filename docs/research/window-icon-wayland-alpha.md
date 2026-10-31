# Wayland window icon color corruption

Investigation date: 2026-10-30. Report:
[GitHub issue 289](https://github.com/TheRealSavi/iOpenPod/issues/289).

## Evidence and reproduction

The reporter's standalone 2.0.16 application on Fedora 44 KDE shows magenta,
green, and black corruption in the title-bar icon at 100% scaling. The bundled
PNG files are square, decode successfully, and render correctly through Qt
directly. Original iOpenPod also registered these same seven PNG representations
with `QIcon.addFile`; replacing that registration does not address the problem.

[Qt 6.11.2's native icon sender](https://github.com/qt/qtbase/blob/v6.11.2/src/plugins/platforms/wayland/plugins/shellintegration/xdg-shell/qwaylandxdgtopleveliconv1.cpp)
paints each available icon representation into a straight-alpha ARGB32 buffer.
The [Qt 6.12.0 sender](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/platforms/wayland/plugins/shellintegration/xdg-shell/qwaylandxdgtopleveliconv1.cpp)
has the same behavior.
[KWin 6.7.5's buffer view](https://github.com/KDE/kwin/blob/v6.7.5/src/core/graphicsbufferview.cpp)
interprets ARGB8888 as premultiplied alpha. This mismatch reproduces the report's
color pattern in a software replay: 105 of 256 pixels change at 16 pixels.
It is consistent with the screenshot; the reporter's active Qt platform plugin
and the complete Fedora compositor path have not been observed directly.

The regression test uses the actual application icon factory, paints its pixmap
into the same Qt image format, then reinterprets those bytes as the receiver does.
Before the fix, this command fails on the 16-pixel icon:

```shell
uv run pytest tests/iOpenPod/GUI/presentation/test_application_icon.py -x -q
```

## Local workaround

`GUI/presentation/application_icon.py` wraps the native window icon in a Qt icon
engine only when the active Qt platform plugin is Wayland and the runtime reports
6.11.2 or 6.12.0. These are inspected versions, not a prediction about later
releases. Reinspect the sender when changing the locked Qt version; remove or
extend the workaround according to the actual buffer format.

The engine supplies already-premultiplied color bytes labeled as straight ARGB32
for native pixmap export. Qt's same-size copy then puts the intended bytes into
the Wayland buffer. `NoFormatConversion` is necessary: allowing the pixmap
conversion to premultiply again introduces rounding errors, which the incorrect
native handoff can amplify. The engine compensates after choosing and scaling
the original representation.

Direct `QIcon.paint` calls delegate to the original icon so Qt client decorations
retain correct colors. This is a window-transport icon; ordinary GUI artwork
should continue using its existing presentation helpers. All original PNG/ICO
files and packaging inputs remain unchanged. No dependency change is needed.

Automated checks compare exact premultiplied pixel bytes at every bundled size,
cover icon copying and new-window inheritance, exercise 1x/1.5x/2x scaling and
direct painting, and verify the version/platform gates. Color-space metadata is
excluded from the buffer comparison because native shared-memory buffers carry
pixel data rather than the PNG's color-space annotation.

On Windows with Python 3.12.14 and Qt 6.11.2, all 43 icon checks pass, along with
the lock, formatting, lint, Markdown, and full Mypy checks. The full test run has
9,834 passes and 47 skips, but three existing update-test modules fail collection:
`tests/iOpenPod/app/version_fixtures.py` computes negative patch offsets from
the project's `2.1.0` version. The failure also reproduces when collecting
`test_python_installation.py` alone; that fixture and the version are unchanged
from HEAD. The eight-worker run reports the same three errors per worker.

## Native acceptance still required

Launch a newly built standalone executable on Fedora KDE under Wayland at 100%
scaling and compare its title-bar icon with the bundled PNG. Also check fractional
and 200% scaling, window switching, and an ordinary dialog. Record the Qt runtime
version and actual platform plugin. The software replay validates the pixel
handoff, not the compositor protocol or a released executable on that Host.
