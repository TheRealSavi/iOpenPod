# Development typing

Keep both Pylance and Mypy enabled. macOS uses PySide6 6.9.3 for runtime compatibility,
while Windows and Linux use newer Qt versions with better bundled type information.

After `uv sync --locked`, run:

```shell
uv run python scripts/prepare_qt_typing.py
```

VS Code's **Environment: Sync** and **Typecheck: Mypy** tasks also run this command.
If the editor retains old diagnostics, run **Developer: Reload Window**.

The command copies installed `.pyi` files into the ignored `PySide6/` directory and
merges the reviewed fragments under `patches/`. Both checkers resolve those same
files through `pyproject.toml`. Nothing is installed, downloaded, or changed in
site-packages. Only annotations are affected; the application still runs Qt 6.9.3.
On other versions the command removes its own stale generated output and uses the
bundled annotations. Rerun it after recreating the environment or changing Qt.

The fragments backport the corresponding declarations from the official PySide6
6.11.2 stubs for existing 6.9.3 APIs: widget/style/QRhi fields, signature-preserving
Slot decoration, optional object returns, message handlers, and locale formatting.
They do not expose Qt 6.10/6.11-only methods. Public fields follow upstream's types
and initialized-object assumptions. Generated files preserve the upstream copyright
and license headers. The correction declarations use the same LGPL-3.0-only option;
see the [LGPL 3.0 license](https://www.gnu.org/licenses/lgpl-3.0.html).

References: [Qt release notes](https://doc.qt.io/qtforpython-6/release_notes/pyside6_release_notes.html),
[official 6.11.2 artifacts](https://pypi.org/project/PySide6-Essentials/6.11.2/#files),
and [ADR-0170](../docs/adr/0170-correct-development-qt-typing.md).

Mypy normally does not report diagnostics inside installed third-party stubs. Its
`PySide6.*` override preserves that treatment for the generated copies; application
uses are still checked, including invalid Qt arguments and field assignments.

Native-platform typing is handled in the platform infrastructure separately from
Qt. Windows/Linux-only exports such as `ctypes.WinDLL` and `os.pidfd_open` are
resolved when called, with explicit signatures that both checkers can use on macOS.
The development environment includes PyInstaller so packaging hook imports also
resolve. These annotations do not add native APIs to macOS; native behavior still
requires tests on the corresponding operating system.
