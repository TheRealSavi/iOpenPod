"""Shared presentation copy with one catalog entry per meaning."""

from PySide6.QtCore import QCoreApplication, QLocale


class Counts:
    """Typed context facade whose tr calls Qt's Python extractor recognizes."""

    @staticmethod
    def tr(source: str, disambiguation: str, count: int) -> str:
        return QCoreApplication.translate("Counts", source, disambiguation, count)


def track_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n track(s)", "", count),
        "%n track(s)",
        count,
    )


def album_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n album(s)", "", count),
        "%n album(s)",
        count,
    )


def item_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n item(s)", "", count),
        "%n item(s)",
        count,
    )


def photo_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n photo(s)", "", count),
        "%n photo(s)",
        count,
    )


def episode_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n episode(s)", "", count),
        "%n episode(s)",
        count,
    )


def device_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n device(s) found", "", count), "%n device(s) found", count
    )


def show_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(Counts.tr("%n show(s)", "", count), "%n show(s)", count)


def result_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(Counts.tr("%n result(s)", "", count), "%n result(s)", count)


def podcasts_found_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n Podcast(s) found.", "", count), "%n Podcast(s) found.", count
    )


def format_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n format(s)", "", count),
        "%n format(s)",
        count,
    )


def remove_tracks_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("Remove %n Track(s) from iPod", "", count),
        "Remove %n Track(s) from iPod",
        count,
    )


def tag_changes_available_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%Ln tag change(s) available", "", count),
        "%Ln tag change(s) available",
        count,
    )


def planned_change_count_text(count: int) -> str:
    count = max(0, count)
    return _count_fallback(
        Counts.tr("%n planned change(s)", "", count),
        "%n planned change(s)",
        count,
    )


def changed_field_count_text(count: int, *, artwork: bool = False) -> str:
    count = max(0, count)
    if artwork:
        return _count_fallback(
            Counts.tr("%n changed field(s) + artwork", "", count),
            "%n changed field(s) + artwork",
            count,
        )
    return _count_fallback(
        Counts.tr("%n changed field(s)", "", count),
        "%n changed field(s)",
        count,
    )


def visible_track_count_text(shown: int, total: int) -> str:
    total = max(0, total)
    return _count_fallback(
        Counts.tr("{shown} of %n track(s)", "", total),
        "{shown} of %n track(s)",
        total,
    ).format(shown=shown)


def _count_fallback(translated: str, source: str, count: int) -> str:
    return english_count_fallback(source, translated, count)


def english_count_fallback(source: str, translated: str, count: int) -> str:
    """Expand Qt's English plural notation only when no translation was found."""

    count = max(0, count)
    if translated == source.replace("%Ln", QLocale().toString(count)).replace(
        "%n", str(count)
    ):
        return translated.replace("(s)", "" if count == 1 else "s")
    return translated
