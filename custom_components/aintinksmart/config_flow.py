"""Config flow for Ain't Ink Smart integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from .const import (
    DOMAIN,
    CONF_MAC,
    DEFAULT_NAME,
)

_LOGGER = logging.getLogger(__name__)

MAC_ADDRESS_REGEX = r"^([0-9A-Fa-f]{2}[:.-]?){5}([0-9A-Fa-f]{2})$"


def _validate_mac(mac: str) -> bool:
    """Validate a MAC address."""
    return re.match(MAC_ADDRESS_REGEX, mac) is not None


class AintinksmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ain't Ink Smart."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_ble_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._selected_mac: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step to choose discovery method or manual entry."""
        _LOGGER.debug("Starting user step (initial choice)")
        errors: dict[str, str] = {}

        if user_input is not None:
            selection = user_input.get("selection")

            if selection == "manual":
                _LOGGER.debug("User selected manual entry")
                return await self.async_step_manual_entry()
            elif selection == "ble_discover":
                _LOGGER.debug("User selected BLE discovery")
                return await self.async_step_discover_devices()
            elif CONF_ADDRESS in user_input:
                 self._selected_mac = user_input[CONF_ADDRESS]
                 await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
                 self._abort_if_unique_id_configured()
                 return self._async_create_entry(self._selected_mac)

        schema = vol.Schema({
            vol.Required("selection"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["ble_discover", "manual"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="user_selection_options",
                )
            )
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={},
            errors=errors,
        )

    async def async_step_manual_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user choosing to enter MAC address manually."""
        _LOGGER.debug("Starting manual entry step")
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input[CONF_MAC]
            if not _validate_mac(mac):
                errors["base"] = "invalid_mac"
            else:
                self._selected_mac = format_mac(mac)
                await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self._async_create_entry(self._selected_mac)

        return self.async_show_form(
            step_id="manual_entry",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
        )

    async def async_step_discover_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered BLE devices and allow selection."""
        _LOGGER.debug("Starting BLE discover devices step")
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_mac = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._async_create_entry(self._selected_mac)

        discovered_devices: dict[str, str] = {}
        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            formatted_address = format_mac(address)
            if formatted_address not in current_addresses and formatted_address not in self._discovered_ble_devices:
                if discovery_info.name and discovery_info.name.lower().startswith("easytag"):
                    _LOGGER.debug("Discovered device via BLE: %s (%s)", discovery_info.name, formatted_address)
                    self._discovered_ble_devices[formatted_address] = discovery_info

        discovered_devices = {
            mac: info.name or f"{DEFAULT_NAME} {mac}"
            for mac, info in self._discovered_ble_devices.items()
        }

        if not discovered_devices:
            _LOGGER.warning("No devices found during BLE discovery.")
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(discovered_devices)}
            ),
            description_placeholders={"count": len(discovered_devices)},
            errors=errors,
        )

    def _async_create_entry(self, mac: str) -> ConfigFlowResult:
        """Create the config entry."""
        title = f"{DEFAULT_NAME} {mac}"
        _LOGGER.info("Creating config entry '%s' for MAC: %s", title, mac)
        return self.async_create_entry(
            title=title,
            data={CONF_MAC: mac},
        )
