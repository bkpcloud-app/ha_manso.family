"""Vestibulare integration."""
from datetime import timedelta
import logging

from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PortalClient, AuthError, PortalError
from .const import DOMAIN, CONF_PORTAL, SCAN_MINUTES

PLATFORMS = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry):
    # One private session per config entry. Home Assistant owns its shutdown.
    # Never close a Home Assistant-managed aiohttp session during polling.
    session = async_create_clientsession(hass)
    client = PortalClient(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
        entry.data[CONF_PORTAL],
    )

    async def update():
        try:
            items = await client.collect(dt_util.now().year)
        except AuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except PortalError as exc:
            raise UpdateFailed(str(exc)) from exc
        return {
            "items": items,
            "synced": dt_util.utcnow(),
            "submission_probe": client.last_diagnostics,
            "visual_probe": client.last_visual_diagnostics,
            "delivery_navigation": client.delivery_discovery,
            "navigation_probe": client.last_navigation_diagnostics,
            "counts": dict(client.last_counts),
        }

    coordinator = DataUpdateCoordinator(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=timedelta(minutes=SCAN_MINUTES), update_method=update)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
