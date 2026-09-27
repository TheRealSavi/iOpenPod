# Translation maintenance

The GUI loads Qt `.qm` catalogs from
`src/iOpenPod/GUI/presentation/i18n/translations/`. English is the source language.
Spanish (`es`) ships as a reviewed source catalog and a compiled catalog. Select
**Español de España** in **Settings → Appearance → Language**; system-default Spanish also
loads it, including regional locales such as `es_ES` and `es_MX`.

German (`de`) also ships as a complete source catalog and a compiled catalog. Select
**Deutsch** in **Settings → Appearance → Language**. System-default German and
regional locales such as `de_DE`, `de_AT`, and `de_CH` load the same catalog.

The German copy uses a professional, simple, friendly tone, with concise action
labels and polite `Sie` in direct instructions. Keep `Computer` for Host,
`Mediathek` for Library, `Titel` for Track, `Wiedergabeliste` for Playlist, `Cover`
for Track artwork, and `Backup` for Backup Snapshot. Use `Sicherheitsbackup` for
the safety snapshot created before a restore. Preserve the meaning of device
safety warnings, product names, file paths, identifiers, and user metadata.

The Spanish copy uses a professional, friendly tone, direct instructions, and
familiar language. Keep `equipo` for Host, `pista` for Track, `lista de reproducción`
for Playlist, `portada` for Track artwork, and `copia de seguridad` for Backup
Snapshot. Use `copia de protección` for the safety snapshot created before a restore.
Keep product names, file paths, identifiers, and user-supplied metadata intact.

## Update a language

From the repository root, use the locked environment:

```shell
uv run python scripts/update_translations.py es
uv run pyside6-linguist src/iOpenPod/GUI/presentation/i18n/translations/iopenpod_es.ts
uv run pyside6-lrelease src/iOpenPod/GUI/presentation/i18n/translations/iopenpod_es.ts
```

Pass several language tags to update several catalogs. The updater retains existing
translations and Qt's unfinished/vanished flags for translator review. Commit the
reviewed `.ts` sources and compiled `.qm` catalogs when adding a language. The language
picker discovers compiled catalogs automatically.

Use the updater rather than a bare directory invocation of `pyside6-lupdate`:
directory scans can silently skip Python files. The updater passes an explicit file
list and generates temporary extraction markers for application-owned message
sources, metadata field labels, and table column groups. Those markers are derived
from the source contracts; there is no separately maintained English message list.

## Authoring copy

- Keep complete sentences together and substitute data after translation. Never
  pass an f-string, concatenated sentence, or conditional expression directly to
  `tr()`. A translation tool needs a literal source and the runtime context.
- Use `QCoreApplication.translate("Context", "Literal")` in free functions.
  `dialog.tr()` and `model.tr()` in helpers can be extracted under the variable
  name instead of the object's runtime class.
- Mark dictionary-held GUI text with `QT_TRANSLATE_NOOP` using the same context as
  its eventual lookup. The marker does not translate at import time.
- Reuse the `CommonActions`, `LibraryLabels`, `EditorLabels`, and `MetadataFields`
  contexts for the existing shared meanings. Similar English words with different
  grammatical roles or domain meanings should keep separate contexts.
- Use the shared count functions in `GUI/presentation/i18n/text.py`. Their single
  numerus entries let Qt choose the language's plural form. The English `(s)`
  notation is expanded only when no translation was found. The typed `Counts.tr`
  and `BackupMessages.tr` context facades also work around the locked Python
  extractor's failure to mark variable-count `QCoreApplication.translate` calls as
  numerus messages.
- Application workflows keep locale-independent strings. For formatted display
  copy, use `app.display_text.source_text("Downloading {title}…", title=title)`.
  It remains an immutable English `str` for existing contracts while retaining its
  template and named parameters. Render it with `workflow_text()` before joining
  it to other text; ordinary string concatenation drops the retained template.
  Capture exceptions with `exception_text()` when their message may carry a
  template, and use object-valued Qt signals to preserve that message across
  controller boundaries. A `Signal(str)` coerces it to an ordinary string.
  Identifiers, paths, user metadata, and native diagnostic details are parameters,
  not translation keys. New message-contract forwarding helpers must also be
  included in the updater's source collection.
- Retranslate visible model data and retained workflow state without resetting
  pending edits, selections, elapsed progress, cancellation, or recovery choices.
  Qt owns the translation of standard native dialog buttons.

## Verification

```shell
uv run pytest tests/iOpenPod/GUI/presentation/test_translation_catalog.py
uv run pytest tests/iOpenPod/GUI/presentation/test_spanish_catalog.py
uv run pytest tests/iOpenPod/GUI/presentation/test_german_catalog.py
uv run pytest tests/iOpenPod/GUI/test_widget_translations.py
```

The catalog test runs real extraction and compilation, checks runtime contexts and
plural metadata, and installs the compiled catalog to verify actual lookup,
parameter substitution, and English fallback. Other GUI tests exercise language
changes with edits and workflows in progress.
The Spanish catalog tests check source coverage, finished translations, placeholder
preservation, compiled-catalog consistency, regional fallback, and the live Settings
language picker.
The German catalog tests cover the same integration, plus preservation of rich-text
markup, file filters, and line breaks.

## Audit scope

The September 2026 pass corrected missing metadata/editor/menu/accessibility text,
Podcast cards, Backup outcomes, ETA and Playlist helper extraction, Sync
stage/progress copy, dynamic field catalogs, and application failure messages.
Shared labels and count phrases reduce repeated translator work; Qt numerus entries
handle languages with more plural forms than English.

Device and Host identifiers and user-supplied titles remain untouched. Raw
operating-system, third-party, and binary-format diagnostic details remain in their
original form. Cached Host Media Scan warnings are also plain English strings;
these diagnostics are not currently exposed by the GUI. Their cache format retains
neither templates nor parameter boundaries, so translating them reliably requires
structured warning data rather than reconstructing messages from persisted English.

Modal editors that cannot expose the language setting while open translate on
construction; they do not all support an externally forced language switch during
the modal session.
