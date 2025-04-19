"""Config flow for Ain't Ink Smart integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, cast

import voluptuous as vol
from bleak.backends.device import BLEDevice

from homeassistant.components import mqtt
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from .const import (
    DOMAIN,
    CONF_MAC,
    DEFAULT_NAME,
    CONF_COMM_MODE, # Added
    CONF_MQTT_BASE_TOPIC, # Added
    COMM_MODE_BLE, # Added
    COMM_MODE_MQTT, # Added
    DEFAULT_COMM_MODE, # Added
    DEFAULT_MQTT_BASE_TOPIC, # Added
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 25 # Seconds to wait for discovery results

# Simple MAC address validation regex
MAC_ADDRESS_REGEX = r"^([0-9A-Fa-f]{2}[:.-]?){5}([0-9A-Fa-f]{2})$" # Allow . and - as separators too

def _validate_mac(mac: str) -> bool:
    """Validate a MAC address."""
    return re.match(MAC_ADDRESS_REGEX, mac) is not None

def _format_mac_for_mqtt(mac: str) -> str:
    """Format MAC address for MQTT topics (lowercase, no separators)."""
    return mac.replace(":", "").replace("-", "").replace(".", "").lower()

class AintinksmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ain't Ink Smart."""

    VERSION = 1 # Keep version 1 as we store data differently now

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_ble_devices: dict[str, BluetoothServiceInfoBleak] = {}
        # self._discovered_mqtt_devices: dict[str, str] = {} # Removed MQTT discovery
        # self._mqtt_unsubscribe: asyncio.TimerHandle | None = None # Removed MQTT discovery
        self._selected_mac: str | None = None
        self._config_data: dict[str, Any] = {}

    # Removed _async_mqtt_scan_callback as MQTT discovery is removed
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the config flow: discover devices and offer manual entry."""
        _LOGGER.debug("Starting user step")

        # --- Start Background Discovery ---
        # 1. Bluetooth Discovery (HA handles this implicitly, we just read results later)


        # MQTT Discovery removed due to complexity and potential errors

        # --- Show Menu ---
        # Offer choice immediately, discovery runs in background
        return self.async_show_menu(
            step_id="user",
            menu_options=["pick_device", "manual_entry"],
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user choosing to pick a discovered device."""
        if user_input is not None:
            # User has selected a device from the list
            self._selected_mac = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_configure_communication()

        _LOGGER.debug("Waiting %.1f seconds for discovery results...", DISCOVERY_TIMEOUT)
        await asyncio.sleep(DISCOVERY_TIMEOUT)

        # MQTT listener cleanup removed

        # Gather BLE results
        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            formatted_address = format_mac(address)
            # TODO: Add better filtering based on service UUIDs or advertisement data if known
            if formatted_address not in current_addresses and formatted_address not in self._discovered_ble_devices:
                 # Basic name filter for now
                 if discovery_info.name and discovery_info.name.lower().startswith("easytag"):
                     _LOGGER.debug("Discovered device via BLE: %s (%s)", discovery_info.name, formatted_address)
                     self._discovered_ble_devices[formatted_address] = discovery_info

        # Use only BLE results
        discovered_devices: dict[str, str] = {
            mac: info.name or f"{DEFAULT_NAME} {mac}"
            for mac, info in self._discovered_ble_devices.items()
        }

        if not discovered_devices:
            _LOGGER.warning("No devices discovered via Bluetooth scan")
            return self.async_abort(reason="no_devices_found")
            # Alternative: Show form with error message
            # return self.async_show_form(step_id="pick_device", errors={"base": "no_devices_found"})

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(discovered_devices)}
            ),
            description_placeholders={"count": len(discovered_devices)},
        )


    async def async_step_manual_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user choosing to enter MAC address manually."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input[CONF_MAC]
            if not _validate_mac(mac):
                errors["base"] = "invalid_mac"
            else:
                self._selected_mac = format_mac(mac)
                await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return await self.async_step_configure_communication()

        # Show form to enter MAC
        return self.async_show_form(
            step_id="manual_entry",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
        )



    async def async_step_configure_communication(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask user for communication mode and MQTT topic if needed."""
        errors: dict[str, str] = {}

        if user_input is not None:
            comm_mode = user_input[CONF_COMM_MODE]
            mqtt_topic = user_input.get(CONF_MQTT_BASE_TOPIC)

            if comm_mode == COMM_MODE_MQTT and not mqtt_topic:
                errors["base"] = "mqtt_topic_required"
            else:
                self._config_data = {
                    CONF_MAC: self._selected_mac, # Use the stored MAC
                    CONF_COMM_MODE: comm_mode,
                }
                if comm_mode == COMM_MODE_MQTT:
                    self._config_data[CONF_MQTT_BASE_TOPIC] = mqtt_topic

                title = f"{DEFAULT_NAME} {self._selected_mac}"
                return self._async_create_entry(title=title, data=self._config_data)

        # Schema for the configuration form
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COMM_MODE, default=DEFAULT_COMM_MODE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[COMM_MODE_BLE, COMM_MODE_MQTT],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="comm_mode_options", # Matches options_flow selector
                    )
                ),
                vol.Optional(
                    CONF_MQTT_BASE_TOPIC,
                    description={"suggested_value": DEFAULT_MQTT_BASE_TOPIC},
                    default=DEFAULT_MQTT_BASE_TOPIC,
                ): str,
            }
        )

        return self.async_show_form(
            step_id="configure_communication",
            data_schema=schema,
            errors=errors,
            description_placeholders={"mac_address": self._selected_mac},
        )

    # Remove async_step_bluetooth and async_step_bluetooth_confirm as discovery is handled differently

    def _async_create_entry(self, title: str, data: dict[str, Any]) -> ConfigFlowResult:
        """Create the config entry with combined data."""
        # Note: Options flow is removed, so no options are set here.
        # Communication mode is now stored in data.
        _LOGGER.info("Creating config entry '%s' with data: %s", title, data)
        return self.async_create_entry(
            title=title,
            data=data,
        )
