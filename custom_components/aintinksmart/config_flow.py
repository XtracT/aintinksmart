"""Config flow for Ain't Ink Smart integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from bleak.backends.device import BLEDevice

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import format_mac

from .const import DOMAIN, CONF_MAC, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)

# Simple MAC address validation regex
MAC_ADDRESS_REGEX = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"

def _validate_mac(mac: str) -> bool:
    """Validate a MAC address."""
    return re.match(MAC_ADDRESS_REGEX, mac) is not None

class AintinksmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ain't Ink Smart."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Handle manual entry submission from the menu path
            if CONF_MAC in user_input:
                address = user_input[CONF_MAC]
                if not _validate_mac(address):
                    errors["base"] = "invalid_mac"
                else:
                    await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
                    self._abort_if_unique_id_configured()
                    return self._async_create_entry(title=f"{DEFAULT_NAME} {address}", mac=address)
            else:
                # This case might occur if the form schema changes unexpectedly
                errors["base"] = "unknown_error"


        # Check for discovered devices before showing options
        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            # Basic filter - check if name starts with 'EasyTag' (case-insensitive)
            # TODO: Refine this filter if a specific service UUID is known
            if discovery_info.name and discovery_info.name.lower().startswith("easytag"):
                 self._discovered_devices[address] = discovery_info

        # Determine next step based on discovery
        if not self._discovered_devices:
            # No devices discovered, show only manual entry form
            return self.async_show_form(
                step_id="user", # Keep step_id as user for submission handling
                data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
                errors=errors,
                description_placeholders={"message": "No compatible devices discovered. Please enter the MAC address manually."},
            )

        # Devices discovered, show menu to pick or enter manually
        # Rely on strings.json for title and description based on step_id
        return self.async_show_menu(
            step_id="user",
            menu_options=["pick_device", "manual_entry"],
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user picking a discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            title = discovery_info.name or f"{DEFAULT_NAME} {address}"
            return self._async_create_entry(title=title, mac=address)

        # Create selection list
        discovered_names = {
            address: discovery_info.name or f"{DEFAULT_NAME} {address}"
            for address, discovery_info in self._discovered_devices.items()
        }
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(discovered_names)}),
        )

    async def async_step_manual_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual entry chosen from menu."""
        # Show the same form as the user step when no devices are found
        return self.async_show_form(
            step_id="user", # Submit back to user step handler
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            description_placeholders={"message": "Please enter the MAC address."},
        )


    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle bluetooth discovery."""
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()

        # TODO: Add more specific filtering if possible (e.g., service UUIDs)
        # For now, rely on the name filter used in async_step_user or assume
        # HA's discovery mechanism already filtered appropriately if manifest has uuids.
        # If we want to be stricter here, check discovery_info.name again.
        if not discovery_info.name or not discovery_info.name.lower().startswith("easytag"):
             return self.async_abort(reason="not_supported") # Abort if name doesn't match expected pattern

        self._discovery_info = discovery_info
        # Present confirmation to the user
        self.context["title_placeholders"] = {"name": discovery_info.name or discovery_info.address}
        return await self.async_step_bluetooth_confirm()


    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user confirming a discovered device."""
        if user_input is None:
             # Show the confirmation form
             return self.async_show_form(
                 step_id="bluetooth_confirm",
                 description_placeholders=self.context.get("title_placeholders"),
             )

        # User confirmed
        if self._discovery_info is None:
            return self.async_abort(reason="discovery_error") # Should not happen normally

        address = self._discovery_info.address
        title = self._discovery_info.name or f"{DEFAULT_NAME} {address}"
        return self._async_create_entry(title=title, mac=address)

    def _async_create_entry(self, title: str, mac: str) -> ConfigFlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=title,
            data={
                CONF_MAC: mac, # Store the non-formatted MAC
            },
        )
