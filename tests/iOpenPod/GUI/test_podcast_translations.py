"""Podcast paint paths translate interface copy while preserving feed metadata."""

from PySide6.QtCore import QDate, QLocale, QPoint, QRect, QTranslator
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.models.podcast_list_models import (
    PodcastEpisodeListModel,
    PodcastSearchResultListModel,
)
from iOpenPod.app.podcasts.models import PodcastEpisode, PodcastSearchResult
from iOpenPod.GUI.delegates.podcast_delegates import (
    PodcastEpisodeDelegate,
    PodcastSearchResultDelegate,
    _episode_meta,  # pyright: ignore[reportPrivateUsage]
    episode_status_text,
)
from iOpenPod.GUI.presentation.i18n.text import episode_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class _Translator(QTranslator):
    def __init__(self) -> None:
        super().__init__()
        self.lookups: set[tuple[str, str]] = set()

    def isEmpty(self) -> bool:
        return False

    def translate(
        self,
        context: str,
        source_text: str,
        /,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str | None:
        del disambiguation
        self.lookups.add((context, source_text))
        if context == "Counts" and source_text == "%n episode(s)":
            return "%n Folge" if n == 1 else "%n Folgen"
        if context != "PodcastPresentation":
            return None
        return {
            "Add to iPod": "Zum iPod hinzufügen",
            "Unavailable": "Nicht verfügbar",
            "ON IPOD": "AUF DEM IPOD",
            "LISTENED": "ANGEHÖRT",
            "Episode %1": "Folge %1",
            "Episode": "Folge",
            "%1 hr %2 min": "%1 Std. %2 Min.",
            "%1 min": "%1 Min.",
            "Unknown publisher": "Unbekannter Herausgeber",
            "Untitled Episode": "Unbenannte Folge",
            "No episode notes are available.": "Keine Episodennotizen verfügbar.",
        }.get(source_text)


def test_podcast_state_metadata_and_counts_translate_at_display_time() -> None:
    translator = _Translator()
    original_locale = QLocale()
    QLocale.setDefault(QLocale("de_DE"))
    assert APPLICATION.installTranslator(translator)
    try:
        assert (
            episode_status_text(
                PodcastEpisode(
                    "download", enclosure_url="https://example.test/media.mp3"
                )
            )
            == "Zum iPod hinzufügen"
        )
        assert episode_status_text(PodcastEpisode("missing")) == "Nicht verfügbar"
        assert (
            episode_status_text(
                PodcastEpisode("heard", on_device=True, track_id=1, listened=True)
            )
            == "AUF DEM IPOD · ANGEHÖRT"
        )
        episode = PodcastEpisode(
            "meta", published_at=1, duration_seconds=3660, episode_number=7
        )
        expected_date = QLocale().toString(
            QDate(1970, 1, 1), QLocale.FormatType.ShortFormat
        )
        assert (
            _episode_meta(episode, "User show title")
            == f"User show title · {expected_date} · 1 Std. 1 Min. · Folge 7"
        )
        assert _episode_meta(PodcastEpisode("empty")) == "Folge"
        assert episode_count_text(1) == "1 Folge"
        assert episode_count_text(2) == "2 Folgen"
    finally:
        APPLICATION.removeTranslator(translator)
        QLocale.setDefault(original_locale)


def test_podcast_delegates_request_translations_for_painted_fallbacks_only() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    episode_model = PodcastEpisodeListModel()
    episode_model.replace("show", (PodcastEpisode("empty"),))
    search_model = PodcastSearchResultListModel()
    search_model.replace(
        (
            PodcastSearchResult(
                "User show title", "", "https://example.test/feed", episode_count=2
            ),
        )
    )
    delegates = (PodcastEpisodeDelegate(theme), PodcastSearchResultDelegate(theme))
    try:
        for delegate, model in zip(
            delegates, (episode_model, search_model), strict=True
        ):
            index = model.index(0, 0)
            option = QStyleOptionViewItem()
            size = delegate.sizeHint(option, index)
            option.rect = QRect(QPoint(), size)
            image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            try:
                delegate.paint(painter, option, index)
            finally:
                painter.end()
        assert {
            ("PodcastPresentation", "Untitled Episode"),
            ("PodcastPresentation", "No episode notes are available."),
            ("PodcastPresentation", "Unknown publisher"),
            ("Counts", "%n episode(s)"),
        } <= translator.lookups
        assert not any(source == "User show title" for _, source in translator.lookups)
    finally:
        APPLICATION.removeTranslator(translator)
        theme.close()
