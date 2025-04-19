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
        self._discovered_mqtt_devices: dict[str, str] = {} # Added to store MQTT discovery results
        self._selected_mac: str | None = None
        self._config_data: dict[str, Any] = {}
        self._mqtt_unsubscribe: callable | None = None # Added for MQTT scan result subscription

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
                return await self.async_step_discover_devices(discovery_method="ble")
            elif selection == "mqtt_discover":
                _LOGGER.debug("User selected MQTT discovery")
                return await self.async_step_mqtt_discovery_setup()
            # Handle selection from discover_devices step if returning here
            elif CONF_ADDRESS in user_input:
                 self._selected_mac = user_input[CONF_ADDRESS]
                 await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
                 self._abort_if_unique_id_configured()
                 return await self.async_step_configure_communication()


        # Initial form to choose discovery method or manual entry
        schema = vol.Schema({
            vol.Required("selection"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["ble_discover", "mqtt_discover", "manual"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="user_selection_options",
                )
            )
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"discovery_timeout": DISCOVERY_TIMEOUT},
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
                return await self.async_step_configure_communication()

        # Show form to enter MAC
        return self.async_show_form(
            step_id="manual_entry",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
        )

    async def async_step_mqtt_discovery_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for MQTT base topic for discovery."""
        _LOGGER.debug("Starting MQTT discovery setup step")
        errors: dict[str, str] = {}

        if user_input is not None:
            mqtt_base_topic = user_input[CONF_MQTT_BASE_TOPIC]
            # Store the base topic temporarily for the scan step
            self._config_data[CONF_MQTT_BASE_TOPIC] = mqtt_base_topic
            _LOGGER.debug("MQTT discovery base topic set to: %s", mqtt_base_topic)
            return await self.async_step_mqtt_discovery_scan()

        # Show form to enter MQTT base topic
        schema = vol.Schema({
            vol.Required(
                CONF_MQTT_BASE_TOPIC,
                description={"suggested_value": DEFAULT_MQTT_BASE_TOPIC},
                default=DEFAULT_MQTT_BASE_TOPIC,
            ): str
        })

        return self.async_show_form(
            step_id="mqtt_discovery_setup",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_mqtt_discovery_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initiate MQTT scan and wait for results."""
        _LOGGER.debug("Starting MQTT discovery scan step")
        errors: dict[str, str] = {}
        mqtt_base_topic = self._config_data.get(CONF_MQTT_BASE_TOPIC)

        if not mqtt_base_topic:
             _LOGGER.error("MQTT base topic not set for discovery scan.")
             return self.async_abort(reason="mqtt_topic_required") # Should not happen if flow is correct

        scan_command_topic = f"{mqtt_base_topic}/bridge/command/scan"
        scan_result_topic = f"{mqtt_base_topic}/bridge/scan_result"
        # Clear previous MQTT discovery results
        self._discovered_mqtt_devices = {}
        self._scan_future = asyncio.Future() # Create a future to signal completion

        @callback
        def mqtt_scan_result_callback(msg: mqtt.models.MQTTMessage) -> None:
            """Handle incoming MQTT scan results."""
            _LOGGER.debug("Received MQTT scan result on topic %s", msg.topic)
            try:
                payload = json.loads(msg.payload)
                payload = json.loads(msg.payload)
                if isinstance(payload, list):
                    _LOGGER.debug("Received list of devices in MQTT scan result")
                    for device_info in payload:
                        if isinstance(device_info, dict) and "mac" in device_info:
                            mac = format_mac(device_info["mac"])
                            name = device_info.get("name", f"{DEFAULT_NAME} {mac}")
                            # Add all discovered devices, check for already configured later
                            self._discovered_mqtt_devices[mac] = name
                            _LOGGER.debug("Discovered device via MQTT: %s (%s)", name, mac)
                    # If we received a list and found devices, consider scan complete
                    if self._discovered_mqtt_devices and not self._scan_future.done():
                         self._scan_future.set_result(True)

                elif isinstance(payload, dict) and "address" in payload:
                     # Handle single device object
                     _LOGGER.debug("Received single device in MQTT scan result")
                     mac = format_mac(payload["address"])
                     name = payload.get("name", f"{DEFAULT_NAME} {mac}")
                     # Add the discovered device, check for already configured later
                     self._discovered_mqtt_devices[mac] = name
                     _LOGGER.debug("Discovered device via MQTT: %s (%s)", name, mac)
                     # If we received a single device, consider scan complete
                     if not self._scan_future.done():
                          self._scan_future.set_result(True)

                else:
                    _LOGGER.warning("Received unexpected payload format on MQTT scan result topic: %s", msg.payload)

            except json.JSONDecodeError:
                _LOGGER.warning("Received invalid JSON on MQTT scan result topic: %s", msg.payload)
            except Exception as e:
                _LOGGER.exception("Error processing MQTT scan result:")


        # Subscribe to scan results topic
        _LOGGER.debug("Subscribing to MQTT scan result topic: %s", scan_result_topic)
        try:
            self._mqtt_unsubscribe = await mqtt.async_subscribe(
                self.hass, scan_result_topic, mqtt_scan_result_callback, qos=1
            )
            # No need for async_on_step_done with write_to_file approach, handle unsubscribe manually if needed
        except HomeAssistantError as e:
            _LOGGER.error("Failed to subscribe to MQTT scan result topic %s: %s", scan_result_topic, e)
            return self.async_show_form(
                step_id="mqtt_discovery_scan",
                errors={"base": "mqtt_subscription_failed"},
                description_placeholders={"topic": scan_result_topic},
            )


        # Publish scan command
        _LOGGER.info("Publishing MQTT scan command to topic: %s", scan_command_topic)
        try:
            await mqtt.async_publish(self.hass, scan_command_topic, "", qos=1, retain=False)
        except HomeAssistantError as e:
            _LOGGER.error("Failed to publish MQTT scan command to topic %s: %s", scan_command_topic, e)
            # Unsubscribe if publish failed
            if self._mqtt_unsubscribe:
                 self._mqtt_unsubscribe()
                 self._mqtt_unsubscribe = None
            return self.async_show_form(
                step_id="mqtt_discovery_scan",
                errors={"base": "mqtt_publish_failed"},
                description_placeholders={"topic": scan_command_topic},
            )

        # Wait for discovery results or timeout
        _LOGGER.debug("Waiting %.1f seconds for MQTT discovery results or timeout...", DISCOVERY_TIMEOUT)
        try:
            await asyncio.wait_for(self._scan_future, timeout=DISCOVERY_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out waiting for MQTT discovery results.")
        except asyncio.CancelledError:
             _LOGGER.debug("MQTT discovery scan step cancelled.")
             # Clean up subscription if cancelled
             if self._mqtt_unsubscribe:
                  self._mqtt_unsubscribe()
                  self._mqtt_unsubscribe = None
             raise # Re-raise the cancellation exception


        # After waiting (either by result or timeout), unsubscribe and proceed to show discovered devices
        if self._mqtt_unsubscribe:
             self._mqtt_unsubscribe()
             self._mqtt_unsubscribe = None

        if self._discovered_mqtt_devices:
             return await self.async_step_discover_devices(discovery_method="mqtt")
        else:
             _LOGGER.warning("No devices discovered via MQTT scan")
             # Show the MQTT discovery setup form again with an error
             return self.async_show_form(
                 step_id="mqtt_discovery_setup", # Return to setup step to allow changing topic or trying again
                 errors={"base": "no_devices_found"},
                 data_schema=vol.Schema({
                     vol.Required(
                         CONF_MQTT_BASE_TOPIC,
                         description={"suggested_value": mqtt_base_topic},
                         default=mqtt_base_topic,
                     ): str
                 }),
                 description_placeholders={"discovery_timeout": DISCOVERY_TIMEOUT},
             )


    async def async_step_discover_devices(
        self, user_input: dict[str, Any] | None = None, discovery_method: str | None = None
    ) -> ConfigFlowResult:
        """Show discovered devices and allow selection."""
        _LOGGER.debug("Starting discover devices step (method: %s)", discovery_method)
        errors: dict[str, str] = {}

        if user_input is not None:
            # User has selected a device from the list
            self._selected_mac = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._selected_mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_configure_communication()

        discovered_devices: dict[str, str] = {}
        description_placeholders: dict[str, Any] = {}

        if discovery_method == "ble":
             # Gather BLE results (already done in async_step_user before refactor, now do here)
             _LOGGER.debug("Gathering BLE discovery results...")
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

             discovered_devices = {
                 mac: info.name or f"{DEFAULT_NAME} {mac}"
                 for mac, info in self._discovered_ble_devices.items()
             }
             description_placeholders["method"] = "Bluetooth" # Need string for this
        elif discovery_method == "mqtt":
             # Use previously stored MQTT discovered devices
             _LOGGER.debug("Using MQTT discovery results...")
             discovered_devices = getattr(self, "_discovered_mqtt_devices", {})
             description_placeholders["method"] = "MQTT Gateway" # Need string for this
        else:
             _LOGGER.error("Unknown discovery method in async_step_discover_devices: %s", discovery_method)
             return self.async_abort(reason="unknown_discovery_method")


        if not discovered_devices:
            _LOGGER.warning("No devices found during %s discovery.", discovery_method)
            # Return to the initial step with an error
            errors["base"] = "no_devices_found"
            # Need to return to the user step, but pass the error.
            # This is complex with separate steps. Let's simplify and abort with a specific reason.
            return self.async_abort(reason="no_devices_found")


        # Show form to pick a discovered device
        description_placeholders["count"] = len(discovered_devices)
        return self.async_show_form(
            step_id="user", # Return to user step to handle selection
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(discovered_devices)}
            ),
            description_placeholders=description_placeholders,
            errors=errors,
        )


    async def async_step_configure_communication(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask user for communication mode and MQTT topic if needed."""
        _LOGGER.debug("Starting configure communication step for %s", self._selected_mac)
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


    def _async_create_entry(self, title: str, data: dict[str, Any]) -> ConfigFlowResult:
        """Create the config entry with combined data."""
        # Note: Options flow is removed, so no options are set here.
        # Communication mode is now stored in data.
        _LOGGER.info("Creating config entry '%s' with data: %s", title, data)
        return self.async_create_entry(
            title=title,
            data=data,
        )
