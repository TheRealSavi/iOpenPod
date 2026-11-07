"""Host defaults copied into newly added Podcast Subscriptions."""

from iOpenPod.app.core.settings.definitions import SettingDefinition
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.podcasts.documents import decode_sync_settings, encode_sync_settings
from iOpenPod.app.podcasts.models import PodcastSyncSettings


def _valid_sync_settings(value: dict[str, object]) -> bool:
    try:
        decode_sync_settings(value)
    except (TypeError, ValueError):
        return False
    return True


DEFAULT_PODCAST_SYNC_SETTINGS = SettingDefinition[dict[str, object]](
    key="sync/default-podcast-settings",
    value_type=dict,
    default=encode_sync_settings(PodcastSyncSettings()),
    validator=_valid_sync_settings,
)


def read_default_podcast_sync_settings(
    settings: SettingsService,
) -> PodcastSyncSettings:
    return decode_sync_settings(settings.get_global(DEFAULT_PODCAST_SYNC_SETTINGS))


def save_default_podcast_sync_settings(
    settings: SettingsService, value: PodcastSyncSettings
) -> None:
    settings.set_global(DEFAULT_PODCAST_SYNC_SETTINGS, encode_sync_settings(value))
