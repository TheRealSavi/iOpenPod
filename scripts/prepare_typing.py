"""Prepare the shared development stubs with ``python -m scripts.prepare_typing``."""

from scripts.prepare_qt_typing import prepare_qt_typing
from scripts.prepare_whenever_typing import prepare_whenever_typing


def main() -> None:
    qt = prepare_qt_typing()
    whenever = prepare_whenever_typing()
    print(
        f"Development typing ready: Qt {'corrected' if qt else 'bundled'}, "
        f"Whenever {'corrected' if whenever else 'bundled'}."
    )


if __name__ == "__main__":
    main()
