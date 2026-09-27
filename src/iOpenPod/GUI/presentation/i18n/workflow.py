"""Translate application-owned display copy at the presentation boundary."""

from PySide6.QtCore import QCoreApplication

from iOpenPod.app.display_text import SourceText


def workflow_text(source: str) -> str:
    """Render a workflow message without changing its stable application value.

    The translation updater collects literal message sources from the typed
    application contracts. Paths, external error details, and user metadata have
    no catalog entries and pass through unchanged.
    """

    if isinstance(source, SourceText):
        translated = QCoreApplication.translate("Workflow", source.source)
        return translated.format(
            **{
                key: workflow_text(value) if isinstance(value, SourceText) else value
                for key, value in source.parameters
            }
        )
    return QCoreApplication.translate("Workflow", source)
