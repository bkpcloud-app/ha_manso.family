"""Setup and reauthentication via the HA UI."""
from hashlib import sha256
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import PortalClient, normalize_portal, AuthError, PortalError
from .const import DOMAIN, CONF_PORTAL

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

class VestibulareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, portal, username, password):
        async with async_create_clientsession(self.hass, auto_cleanup=False) as session:
            await PortalClient(session, username, password, portal).login()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            try:
                portal = normalize_portal(user_input[CONF_PORTAL])
            except ValueError:
                errors[CONF_PORTAL] = "invalid_url"
            else:
                try:
                    await self._validate(portal, username, user_input[CONF_PASSWORD])
                except AuthError:
                    errors["base"] = "invalid_auth"
                except PortalError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(sha256(f"{portal}|{username.lower()}".encode()).hexdigest())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="Vestibulare", data={CONF_PORTAL: portal, CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required(CONF_PORTAL): str, vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): PASSWORD}), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await self._validate(entry.data[CONF_PORTAL], entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            except AuthError:
                errors["base"] = "invalid_auth"
            except PortalError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD}), errors=errors)
