"""Only non-secret scrobbling preferences belong in global settings."""

from iOpenPod.app.core.settings.definitions import SettingDefinition
from iOpenPod.app.core.settings.service import SettingsService

from .models import Account, Service

SCROBBLE_DURING_SYNC = SettingDefinition("sync/scrobble", bool, True)
LASTFM_USERNAME = SettingDefinition("scrobbling/lastfm-username", str, "")
LISTENBRAINZ_USERNAME = SettingDefinition("scrobbling/listenbrainz-username", str, "")


def account_setting(service: Service) -> SettingDefinition[str]:
    return LASTFM_USERNAME if service is Service.LASTFM else LISTENBRAINZ_USERNAME


def configured_accounts(settings: SettingsService) -> tuple[Account, ...]:
    return tuple(
        Account(service, username)
        for service in Service
        if (username := settings.get(account_setting(service)))
    )
