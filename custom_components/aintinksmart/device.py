"""Device manager class for Ain't Ink Smart."""
from __future__ import annotations

import asyncio
import base64 # Add base64 import
import binascii # Add binascii import
import logging
from datetime import datetime
from typing import Any

import async_timeout
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import voluptuous as vol # For service call validation

from homeassistant.components import mqtt # Added
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
    async_scanner_count, # Added to check if BT is enabled
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback, HassJob
from homeassistant.const import STATE_UNAVAILABLE as HA_STATE_UNAVAILABLE # Avoid confusion
from homeassistant.exceptions import HomeAssistantError # Added
from homeassistant.helpers import aiohttp_client, device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later # Added for MQTT timeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util # Import datetime utility

# Import constants, helpers, and comms module
from .const import (
    DOMAIN,
    CONF_MAC,
    CONF_COMM_MODE, # Added
    CONF_MQTT_BASE_TOPIC, # Added
    COMM_MODE_BLE, # Added
    COMM_MODE_MQTT, # Added
    DEFAULT_COMM_MODE, # Added
    DEFAULT_MQTT_BASE_TOPIC, # Added
    STATE_IDLE,
    STATE_CONNECTING,
    STATE_SENDING,
    STATE_ERROR,
    STATE_SUCCESS,
    STATE_ERROR_CONNECTION, # Added
    STATE_ERROR_TIMEOUT, # Added
    STATE_ERROR_SEND, # Added
    STATE_ERROR_IMAGE_FETCH, # Added
    STATE_ERROR_IMAGE_PROCESS, # Added
    STATE_ERROR_UNKNOWN, # Added
    ATTR_LAST_UPDATE,
    ATTR_LAST_ERROR,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
    NUMBER_KEY_PACKET_DELAY,
    DEFAULT_PACKET_DELAY_MS,
    MQTT_BRIDGE_STATUS_TOPIC_SUFFIX, # Added
    SENSOR_KEY_MQTT_DISPLAY_TRANSFER_STATUS, # Added import
)
from .helpers import (
    ImageProcessor,
    ProtocolFormatter,
    PacketBuilder,
    ImageProcessingError,
    ProtocolFormattingError,
    PacketBuilderError,
)
from .ble_comms import async_send_packets_ble, BleCommunicationError
from .mqtt_comms import async_send_packets_mqtt, MqttCommunicationError # Added

_LOGGER = logging.getLogger(__name__)

# Timeout for the entire send operation
SEND_TIMEOUT = 90.0 # Seconds for BLE/MQTT send attempt including processing
MQTT_STATUS_TIMEOUT = 120.0 # Seconds to wait for a final status from MQTT gateway after sending

class AintinksmartDevice:
    """Manages state and communication for a single Ain't Ink Smart device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the device manager."""
        self.hass = hass
        self.entry = entry
        self.mac_address = entry.data[CONF_MAC]
        self.formatted_mac = dr.format_mac(self.mac_address)
        self.name = f"Ain't Ink Smart {self.mac_address}" # Used for logging prefix

        # Communication mode specifics
        self._comm_mode: str = DEFAULT_COMM_MODE
        self._mqtt_base_topic: str | None = None
        self._ble_device: BLEDevice | None = None
        self._cancel_bluetooth_callback: callable | None = None
        self._cancel_mqtt_subscription: callable | None = None
        self._cancel_mqtt_bridge_status_subscription: callable | None = None # Added for bridge status
        self._mqtt_status_timeout_task: asyncio.TimerHandle | None = None

        # State tracking
        self._status: str = STATE_IDLE
        self._mqtt_bridge_status: str = HA_STATE_UNAVAILABLE # Added for gateway bridge status
        self._mqtt_display_transfer_status: str = HA_STATE_UNAVAILABLE # Added for display transfer status
        self._last_error: str | None = None
        self._last_update: datetime | None = None
        self._last_image_bytes: bytes | None = None # Last successfully sent image
        self._pending_image_bytes: bytes | None = None # Image currently being sent (for MQTT success handling)
        self._send_lock = asyncio.Lock()  # Prevent concurrent sends
        self._update_listeners: list[callable] = []  # Simple listener pattern for entities
        self._auto_update_enabled: bool = True # Flag for the auto-update switch

        # Helpers
        self._image_processor = ImageProcessor()
        self._protocol_formatter = ProtocolFormatter()
        self._packet_builder = PacketBuilder()

        # Listeners for source entity updates
        self._cancel_state_listener: callable | None = None
        # Note: Options update listener is added in __init__.py and calls _handle_options_update

    @property
    def is_available(self) -> bool:
        """Return True if the device is considered available based on comm mode."""
        if self._comm_mode == COMM_MODE_BLE:
            # Available if BT is enabled and we have a BLEDevice object
            return async_scanner_count(self.hass, connectable=True) > 0 and self._ble_device is not None
        if self._comm_mode == COMM_MODE_MQTT:
            # Available if MQTT is connected
            # Could add checks for recent gateway status messages if needed
            return mqtt.is_connected(self.hass)
        return False # Should not happen

    @property
    def state_data(self) -> dict[str, Any]:
        """Return the current state data for entities."""
        is_available_status = self.is_available # Evaluate the property here
        return {
            "status": self._status if is_available_status else HA_STATE_UNAVAILABLE,
            ATTR_LAST_ERROR: self._last_error,
            ATTR_LAST_UPDATE: self._last_update,
            "last_image_bytes": self._last_image_bytes, # For camera
            "is_available": is_available_status, # Use the evaluated value
            "mqtt_bridge_status": self._mqtt_bridge_status, # Added
            SENSOR_KEY_MQTT_DISPLAY_TRANSFER_STATUS: self._mqtt_display_transfer_status, # Added
        }

    async def async_init(self) -> None:
        """Perform initial setup based on configuration."""
        _LOGGER.debug("[%s] Initializing device manager", self.mac_address)

        # Read options and set up communication mode
        self._comm_mode = self.entry.data.get(CONF_COMM_MODE, DEFAULT_COMM_MODE)
        self._mqtt_base_topic = self.entry.data.get(CONF_MQTT_BASE_TOPIC) # Can be None

        await self.async_setup_communication_mode()

        # Defer source listener setup until HA is fully started
        self.hass.bus.async_listen_once(
            "homeassistant_started", self._async_post_startup
        )

    async def _async_post_startup(self, event):
        """Set up listeners after HA has started."""
        _LOGGER.debug("[%s] Home Assistant started, setting up listeners", self.mac_address)
        self._setup_source_listener()

    async def async_setup_communication_mode(self) -> None:
        """Set up listeners and initial state based on the current communication mode."""
        _LOGGER.debug("[%s] Setting up communication mode: %s", self.mac_address, self._comm_mode)
        await self.async_cleanup_communication_mode() # Clean up previous mode's listeners

        if self._comm_mode == COMM_MODE_BLE:
            # Reset MQTT bridge status when switching away from MQTT
            self._mqtt_bridge_status = HA_STATE_UNAVAILABLE
            self._mqtt_display_transfer_status = HA_STATE_UNAVAILABLE # Added reset
            self._notify_listeners() # Notify entities about the status change

            if async_scanner_count(self.hass, connectable=True) < 1:
                _LOGGER.warning("[%s] Bluetooth scanner is not available or enabled", self.mac_address)
                self._update_state(HA_STATE_UNAVAILABLE, "Bluetooth not available")
                return

            self._ble_device = async_ble_device_from_address(self.hass, self.mac_address.upper(), connectable=True)
            if not self._ble_device:
                _LOGGER.warning("[%s] BLE device not found initially", self.mac_address)

            self._cancel_bluetooth_callback = async_register_callback(
                self.hass, self._handle_bluetooth_update, {"address": self.mac_address.upper()}, mode="active"
            )
            self._update_state(STATE_IDLE if self.is_available else HA_STATE_UNAVAILABLE)

        elif self._comm_mode == COMM_MODE_MQTT:
            if not self._mqtt_base_topic:
                _LOGGER.error("[%s] MQTT mode selected but base topic is not configured", self.mac_address)
                self._update_state(STATE_ERROR, "MQTT base topic not configured")
                return

            if not mqtt.is_connected(self.hass):
                _LOGGER.warning("[%s] MQTT integration is not connected", self.mac_address)
                # State will be updated by MQTT connection callbacks if it connects later
                self._update_state(HA_STATE_UNAVAILABLE, "MQTT not connected")
                # We still subscribe, it will work once MQTT connects

            mac_no_colons = self.mac_address.replace(":", "").upper() # Changed to upper case
            status_topic = f"{self._mqtt_base_topic}/display/{mac_no_colons}/status"
            bridge_status_topic = f"{self._mqtt_base_topic}/{MQTT_BRIDGE_STATUS_TOPIC_SUFFIX}" # Define the variable

            _LOGGER.info("[%s] Subscribing to MQTT status topic: %s", self.mac_address, status_topic)
            _LOGGER.info("[%s] Subscribing to MQTT bridge status topic: %s", self.mac_address, bridge_status_topic) # Added
            try:
                self._cancel_mqtt_subscription = await mqtt.async_subscribe(
                    self.hass, status_topic, self._handle_mqtt_status_update, qos=1
                )
                self._cancel_mqtt_bridge_status_subscription = await mqtt.async_subscribe( # Added
                    self.hass, bridge_status_topic, self._handle_mqtt_bridge_status_update, qos=1 # Added
                )
            except HomeAssistantError as e:
                _LOGGER.error("[%s] Failed to subscribe to MQTT topics: %s", self.mac_address, e) # Modified log
                self._update_state(STATE_ERROR, f"MQTT subscription failed: {e}")
                # Attempt to clean up any partial subscriptions
                await self.async_cleanup_communication_mode()
                return

            # Set initial state based on MQTT connection status
            self._update_state(STATE_IDLE if mqtt.is_connected(self.hass) else HA_STATE_UNAVAILABLE)

        else:
            _LOGGER.error("[%s] Unknown communication mode: %s", self.mac_address, self._comm_mode)
            self._update_state(STATE_ERROR, f"Invalid communication mode: {self._comm_mode}")

    async def async_cleanup_communication_mode(self) -> None:
        """Remove listeners/callbacks for the current communication mode."""
        _LOGGER.debug("[%s] Cleaning up communication mode listeners", self.mac_address)
        if self._cancel_bluetooth_callback:
            _LOGGER.debug("[%s] Cancelling Bluetooth callback", self.mac_address)
            self._cancel_bluetooth_callback()
            self._cancel_bluetooth_callback = None
        if self._cancel_mqtt_subscription is not None:
            _LOGGER.debug("[%s] Unsubscribing from MQTT display status topic", self.mac_address) # Modified log
            try:
                await self._cancel_mqtt_subscription()
            except HomeAssistantError as e:
                 _LOGGER.warning("[%s] Error unsubscribing from MQTT display status: %s", self.mac_address, e) # Modified log
            self._cancel_mqtt_subscription = None
        if self._cancel_mqtt_bridge_status_subscription is not None: # Added
            _LOGGER.debug("[%s] Unsubscribing from MQTT bridge status topic", self.mac_address) # Added
            try: # Added
                await self._cancel_mqtt_bridge_status_subscription() # Added
            except HomeAssistantError as e: # Added
                 _LOGGER.warning("[%s] Error unsubscribing from MQTT bridge status: %s", self.mac_address, e) # Added
            self._cancel_mqtt_bridge_status_subscription = None # Added
        if self._mqtt_status_timeout_task:
            self._mqtt_status_timeout_task.cancel()
            self._mqtt_status_timeout_task = None

        self._ble_device = None # Clear BLE device reference

    @callback
    def _handle_bluetooth_update(
        self, service_info: BluetoothServiceInfoBleak, change: Any
    ) -> None:
        """Handle updated Bluetooth device data (only relevant in BLE mode)."""
        if self._comm_mode != COMM_MODE_BLE:
            return # Ignore if not in BLE mode

        _LOGGER.debug("[%s] Bluetooth update received: %s", self.mac_address, service_info.device)
        was_available = self.is_available
        self._ble_device = service_info.device
        now_available = self.is_available

        if not was_available and now_available:
            self._update_state(STATE_IDLE)
        elif was_available and not now_available:
            self._update_state(HA_STATE_UNAVAILABLE, "Device became unavailable")
        elif self._status == HA_STATE_UNAVAILABLE and now_available: # Handle case where BT adapter comes online
            self._update_state(STATE_IDLE)
        else:
            self._notify_listeners() # Notify for potential RSSI changes etc.

    @callback
    def _handle_mqtt_status_update(self, msg: mqtt.models.MQTTMessage) -> None:
        """Handle status messages received from the MQTT gateway."""
        if self._comm_mode != COMM_MODE_MQTT:
            return # Should not happen if unsubscribed correctly

        payload = msg.payload.lower() # Payload is already string, just lower() for main status logic
        _LOGGER.info("[%s] Received MQTT status update: '%s'", self.mac_address, payload)

        # Store the payload as the transfer status (preserving case)
        self._mqtt_display_transfer_status = msg.payload # Payload is already string
        _LOGGER.debug("[%s] Stored display transfer status: '%s'", self.mac_address, self._mqtt_display_transfer_status) # Added debug log

        # Cancel pending timeout task if we receive any status
        if self._mqtt_status_timeout_task:
            self._mqtt_status_timeout_task.cancel()
            self._mqtt_status_timeout_task = None

        # Map gateway status to internal states
        # This mapping depends heavily on the firmware's published statuses
        # Example mapping (adjust based on actual firmware):
        new_state = STATE_IDLE
        error_msg = None

        if "connected_ble" in payload:
            new_state = STATE_CONNECTING # Or keep sending?
        elif "sending_packets" in payload:
            new_state = STATE_SENDING
        elif "success" in payload:
            new_state = STATE_SUCCESS
        elif "error_connect" in payload:
            new_state = STATE_ERROR_CONNECTION
            error_msg = "Gateway failed to connect to display"
        elif "error_send" in payload:
            new_state = STATE_ERROR_SEND
            error_msg = "Gateway failed to send packets"
        elif "error_timeout" in payload:
            new_state = STATE_ERROR_TIMEOUT
            error_msg = "Gateway timed out during operation"
        elif "error" in payload: # Generic error
            new_state = STATE_ERROR_UNKNOWN
            error_msg = f"Gateway reported error: {payload}"
        elif "idle" in payload:
            new_state = STATE_IDLE
        else:
            _LOGGER.warning("[%s] Unhandled MQTT status payload: %s", self.mac_address, payload)
            # Optionally set to unknown or keep previous state?
            # For now, assume idle if not recognized after a send attempt
            if self._status == STATE_SENDING:
                 new_state = STATE_IDLE # Revert to idle if unrecognized status during send
            else:
                 return # Ignore if not sending and status is weird

        self._update_state(new_state, error_msg)

    @callback
    def _handle_mqtt_bridge_status_update(self, msg: mqtt.models.MQTTMessage) -> None: # Added
        """Handle status messages received from the MQTT gateway bridge topic.""" # Added
        if self._comm_mode != COMM_MODE_MQTT: # Added
            return # Should not happen if unsubscribed correctly # Added

        payload = msg.payload # Assuming simple string status, no lower() needed yet # Added
        _LOGGER.debug("[%s] Received MQTT bridge status update: '%s'", self.mac_address, payload) # Added

        # Update the internal bridge status
        self._mqtt_bridge_status = payload # Added

        # Notify listeners about the state change (including the new bridge status)
        self._notify_listeners() # Added

    @callback
    def _handle_mqtt_status_timeout(self) -> None:
        """Handle timeout waiting for MQTT status after sending."""
        _LOGGER.warning("[%s] Timed out waiting for final MQTT status update", self.mac_address)
        self._mqtt_status_timeout_task = None
        if self._status == STATE_SENDING: # Only update if still waiting
            self._update_state(STATE_ERROR_TIMEOUT, "No final status received from gateway")


    async def async_handle_send_image_service(self, call: ServiceCall) -> None:
        """Handle the send_image service call."""
        if not self.is_available:
            _LOGGER.error("[%s] Cannot send image: Device is unavailable", self.mac_address)
            raise vol.Invalid("Device is unavailable")

        if self._send_lock.locked():
            _LOGGER.warning("[%s] Send operation already in progress", self.mac_address)
            raise vol.Invalid("Send operation already in progress")

        async with self._send_lock:
            image_data_b64 = call.data.get(ATTR_IMAGE_DATA)
            image_entity_id = call.data.get(ATTR_IMAGE_ENTITY_ID)
            mode = call.data.get(ATTR_MODE) # Already validated by services.yaml? Add validation here too.

            if not mode or mode not in ['bw', 'bwr']:
                 _LOGGER.error("[%s] Invalid mode specified in service call: %s", self.mac_address, mode)
                 raise vol.Invalid(f"Invalid mode: {mode}. Must be 'bw' or 'bwr'.")

            image_bytes: bytes | None = None

            if image_entity_id:
                _LOGGER.info("[%s] Fetching image from entity: %s", self.mac_address, image_entity_id)
                try:
                    image_state = self.hass.states.get(image_entity_id)
                    if image_state is None:
                        raise vol.Invalid(f"Image entity not found: {image_entity_id}")
                    # TODO: Check HA version for correct attribute name (content_type vs url_path?)
                    image_url = image_state.attributes.get("entity_picture") # Common attribute
                    if not image_url:
                         raise vol.Invalid(f"Could not get image URL from entity: {image_entity_id}")

                    # Construct full URL if relative
                    if image_url.startswith("/"):
                         image_url = f"{self.hass.config.internal_url}{image_url}" # Adjust if external needed

                    session = aiohttp_client.async_get_clientsession(self.hass)
                    async with async_timeout.timeout(10): # Timeout for fetching image
                        response = await session.get(image_url)
                        response.raise_for_status()
                        image_bytes = await response.read()
                    _LOGGER.info("[%s] Successfully fetched %d bytes from %s", self.mac_address, len(image_bytes), image_entity_id)
                except (aiohttp_client.ClientError, asyncio.TimeoutError, vol.Invalid) as e:
                    _LOGGER.error("[%s] Failed to fetch or process image from entity %s: %s", self.mac_address, image_entity_id, e)
                    from .const import STATE_ERROR_IMAGE_FETCH
                    from .const import STATE_ERROR_IMAGE_FETCH
                    self._update_state(STATE_ERROR_IMAGE_FETCH, f"Failed to get image from entity: {e}")
                    return # Abort send
                except Exception as e:
                    _LOGGER.exception("[%s] Unexpected error fetching image from entity %s", self.mac_address, image_entity_id)
                    from .const import STATE_ERROR_UNKNOWN
                    from .const import STATE_ERROR_UNKNOWN
                    self._update_state(STATE_ERROR_UNKNOWN, f"Unexpected error getting image from entity: {e}")
                    return # Abort send

            elif image_data_b64:
                _LOGGER.info("[%s] Decoding base64 image data", self.mac_address)
                try:
                    image_bytes = base64.b64decode(image_data_b64)
                except (TypeError, ValueError, binascii.Error) as e:
                    _LOGGER.error("[%s] Invalid base64 image data provided: %s", self.mac_address, e)
                    from .const import STATE_ERROR_IMAGE_PROCESS
                    from .const import STATE_ERROR_IMAGE_PROCESS
                    self._update_state(STATE_ERROR_IMAGE_PROCESS, f"Invalid base64 data: {e}")
                    return # Abort send
            else:
                _LOGGER.error("[%s] Service call missing image_data or image_entity_id", self.mac_address)
                from .const import STATE_ERROR_UNKNOWN
                from .const import STATE_ERROR_UNKNOWN
                self._update_state(STATE_ERROR_UNKNOWN, "No image source provided")
    async def _async_send_image_internal(self, image_bytes: bytes, mode: str) -> bool:
        """Process, format, build packets, and send image via configured mode. Return True on success."""
        self._update_state(STATE_CONNECTING) # Initial state for both modes
        self._pending_image_bytes = image_bytes # Store for potential MQTT success handling
        success = False
        try:
            async with async_timeout.timeout(SEND_TIMEOUT):
                # 1. Process Image
                _LOGGER.debug("[%s] Processing image...", self.mac_address)
                processed_data = self._image_processor.process_image(image_bytes, mode)

                # 2. Format Payload
                _LOGGER.debug("[%s] Formatting payload...", self.mac_address)
                hex_payload = self._protocol_formatter.format_payload(processed_data)

                # 3. Build Packets
                _LOGGER.debug("[%s] Building packets...", self.mac_address)
                packets = self._packet_builder.build_packets(hex_payload, self.mac_address)

                # 4. Send via configured mode
                self._update_state(STATE_SENDING)

                # --- Get Packet Delay (only for BLE) ---
                delay_ms = DEFAULT_PACKET_DELAY_MS # Initialize with default

                if self._comm_mode == COMM_MODE_BLE:
                    ent_reg = er.async_get(self.hass)
                    number_unique_id = f"{self.entry.entry_id}_{NUMBER_KEY_PACKET_DELAY}"
                    delay_entity_id = ent_reg.async_get_entity_id("number", DOMAIN, number_unique_id)

                    if delay_entity_id:
                        state = self.hass.states.get(delay_entity_id)
                        if state and state.state not in (None, HA_STATE_UNAVAILABLE, "unknown"):
                            try:
                                delay_ms = int(float(state.state))
                                if delay_ms < 1: # Ensure positive delay
                                    _LOGGER.warning(
                                        "[%s] Packet delay %s state (%s ms) is invalid, using default %dms",
                                        self.mac_address, delay_entity_id, state.state, DEFAULT_PACKET_DELAY_MS
                                    )
                                    delay_ms = DEFAULT_PACKET_DELAY_MS
                                else:
                                    _LOGGER.debug("[%s] Using packet delay from %s: %d ms", self.mac_address, delay_entity_id, delay_ms)
                            except (ValueError, TypeError):
                                _LOGGER.warning(
                                    "[%s] Could not parse packet delay from %s state '%s', using default %dms",
                                    self.mac_address, delay_entity_id, state.state, DEFAULT_PACKET_DELAY_MS
                                )
                                delay_ms = DEFAULT_PACKET_DELAY_MS
                        else:
                            _LOGGER.warning(
                                "[%s] Packet delay entity %s state is unavailable (%s), using default %dms",
                                self.mac_address, delay_entity_id, state.state if state else "None", DEFAULT_PACKET_DELAY_MS
                            )
                            # Keep default delay_ms
                    else:
                        _LOGGER.warning(
                            "[%s] Packet delay entity with unique ID %s not found, using default %dms",
                            self.mac_address, number_unique_id, DEFAULT_PACKET_DELAY_MS
                        )
                        # Keep default delay_ms
                    # End of BLE-specific delay lookup
                # --- End Get Packet Delay ---

                # --- Send based on mode ---
                if self._comm_mode == COMM_MODE_BLE:
                    if not self.is_available or self._ble_device is None:
                        raise BleCommunicationError("BLE device became unavailable before sending")
                    success = await async_send_packets_ble(self.hass, self._ble_device, packets, delay_ms)
                    if success:
                        self._update_state(STATE_SUCCESS)
                        # _last_image_bytes updated in _update_state for SUCCESS
                    else:
                        # Error state likely already set by BleakError exception below
                        # If no exception but returns False, set generic send error
                        if self._status == STATE_SENDING:
                            self._update_state(STATE_ERROR_SEND, "BLE send command returned false")

                elif self._comm_mode == COMM_MODE_MQTT:
                    if not self.is_available:
                        raise MqttCommunicationError("MQTT is not connected")
                    if not self._mqtt_base_topic:
                        raise MqttCommunicationError("MQTT base topic not configured")

                    # Publish packets via MQTT
                    publish_success = await async_send_packets_mqtt(
                        self.hass, self._mqtt_base_topic, self.mac_address, packets, delay_ms
                    )

                    if publish_success:
                        _LOGGER.info("[%s] MQTT packets published, waiting for gateway status...", self.mac_address)
                        # Start timeout for waiting for final status
                        if self._mqtt_status_timeout_task:
                            self._mqtt_status_timeout_task.cancel()
                        self._mqtt_status_timeout_task = self.hass.loop.call_later(
                            MQTT_STATUS_TIMEOUT, HassJob(self._handle_mqtt_status_timeout).target
                        )
                        # Keep state as STATE_SENDING, success determined by _handle_mqtt_status_update
                        success = True # Indicate publish was ok, but overall success pending
                    else:
                        # Error state should be set by MqttCommunicationError exception below
                        success = False
                        if self._status == STATE_SENDING:
                            self._update_state(STATE_ERROR_SEND, "MQTT publish command returned false")

                else:
                    _LOGGER.error("[%s] Unknown communication mode for sending: %s", self.mac_address, self._comm_mode)
                    self._update_state(STATE_ERROR_UNKNOWN, f"Invalid comm mode: {self._comm_mode}")
                    success = False
                # --- End Send based on mode ---

            # Note: State updates for success/failure are handled within the mode blocks
            # or by the exception handlers below.

        except (
            ImageProcessingError,
            ProtocolFormattingError,
            PacketBuilderError,
            BleCommunicationError, # BLE specific
            BleakError,            # BLE specific
            MqttCommunicationError,# MQTT specific
            asyncio.TimeoutError,  # Generic timeout for the whole operation
        ) as e:
            _LOGGER.error("[%s] Send operation failed: %s", self.mac_address, e)
            # Map specific exceptions to error states
            error_state = STATE_ERROR_UNKNOWN
            error_message = f"Send failed: {e}"

            if isinstance(e, (ImageProcessingError, ProtocolFormattingError, PacketBuilderError)):
                error_state = STATE_ERROR_IMAGE_PROCESS
            elif isinstance(e, (BleCommunicationError, MqttCommunicationError)):
                # Covers BLE connection/send issues and MQTT publish issues
                error_state = STATE_ERROR_CONNECTION # Use connection error for MQTT publish failure too
            elif isinstance(e, BleakError):
                # More specific BLE errors
                error_state = STATE_ERROR_SEND
            elif isinstance(e, asyncio.TimeoutError):
                error_state = STATE_ERROR_TIMEOUT
                error_message = "Send operation timed out" # More specific message

            self._update_state(error_state, error_message)
            success = False # Ensure success is false if an exception occurred
        except Exception as e:
            _LOGGER.exception("[%s] Unexpected error during send operation", self.mac_address)
            _LOGGER.exception("[%s] Unexpected error during send operation", self.mac_address)
            self._update_state(STATE_ERROR_UNKNOWN, f"Unexpected error: {e}")
            success = False
        finally:
            # If we finished sending but ended in a non-final state (and no specific error was set)
            # set a generic error state. This shouldn't happen often with the new logic.
            if self._status in [STATE_CONNECTING, STATE_SENDING]:
                _LOGGER.warning("[%s] Send operation finished in intermediate state: %s", self.mac_address, self._status)
                if not self._last_error: # Avoid overwriting specific errors set above
                    self._update_state(STATE_ERROR_UNKNOWN, "Send operation did not complete successfully")
            # Clear pending image if the operation failed
            if not success or self._status != STATE_SUCCESS:
                self._pending_image_bytes = None

        # Return True only if the initial send command was successful (for MQTT, final success is async)
        # For BLE, this reflects the actual send result.
        return success


    @callback
    @callback
    def _update_state(self, new_state: str, error: str | None = None) -> None:
        """Update the internal state and notify listeners."""
        # Prevent redundant updates
        if new_state == self._status and error == self._last_error:
            return

        self._status = new_state
        self._last_error = error if error else None
        self._last_update = dt_util.utcnow()

        # Handle storing image on successful send (especially for MQTT async success)
        if new_state == STATE_SUCCESS and self._pending_image_bytes is not None:
            _LOGGER.debug("[%s] Storing successfully sent image (%d bytes)", self.mac_address, len(self._pending_image_bytes))
            self._last_image_bytes = self._pending_image_bytes
            self._pending_image_bytes = None # Clear pending image
        elif new_state != STATE_SENDING and new_state != STATE_CONNECTING:
            # Clear pending image if send fails or completes unsuccessfully
            self._pending_image_bytes = None

        _LOGGER.info("[%s] State updated: %s (Error: %s)", self.mac_address, self._status, self._last_error)
        self._notify_listeners()

    @callback
    def add_listener(self, listener: callable) -> None:
        """Add a listener for state updates."""
        self._update_listeners.append(listener)

    @callback
    def remove_listener(self, listener: callable) -> None:
        """Remove a listener."""
        try:
            self._update_listeners.remove(listener)
        except ValueError:
            pass # Listener already removed

    @callback
    def _notify_listeners(self) -> None:
        """Notify all registered listeners."""
        for listener in self._update_listeners:
            listener()

    @callback
    def async_set_auto_update_enabled(self, enabled: bool) -> None:
        """Set the auto-update flag from the switch entity."""
        _LOGGER.debug("[%s] Auto update set to: %s", self.mac_address, enabled)
        self._auto_update_enabled = enabled
        # No need to notify listeners here, the switch handles its own state

    async def async_unload(self) -> None:
        """Clean up resources."""
        _LOGGER.debug("[%s] Unloading device manager", self.mac_address)

        # Clean up communication mode listeners
        await self.async_cleanup_communication_mode()

        # Clean up source entity listener
        if self._cancel_state_listener:
            self._cancel_state_listener()
            self._cancel_state_listener = None

        # Clear entity listeners
        self._update_listeners.clear()

    # Note: The options update listener in __init__.py triggers a full reload,
    # so we don't need a specific _handle_options_update method here anymore
    # to just re-read options. The reload handles cleanup via async_unload
    # and setup via async_setup_entry / async_init.

    def _setup_source_listener(self) -> None:
        """Set up or cancel the state listener for the source image entity."""
        from homeassistant.helpers.event import async_track_state_change_event
        from homeassistant.helpers import entity_registry as er

        # Cancel existing listener if any
        if self._cancel_state_listener:
            self._cancel_state_listener()
            self._cancel_state_listener = None

        # Find the source select entity
        ent_reg = er.async_get(self.hass)
        source_select_unique_id = f"{self.entry.entry_id}_source_entity"
        source_select_entity_id = ent_reg.async_get_entity_id("select", DOMAIN, source_select_unique_id)

        if not source_select_entity_id:
            _LOGGER.warning("[%s] Source select entity not found in registry, cannot listen for changes.", self.mac_address)
            return

        # Always listen to the source select entity itself
        _LOGGER.info("[%s] Listening for changes to source select entity: %s", self.mac_address, source_select_entity_id)
        self._cancel_state_listener = async_track_state_change_event(
            self.hass,
            [source_select_entity_id],
            self._handle_source_select_update, # Listen to the select entity, not the source directly
        )

    async def _handle_source_select_update(self, event) -> None:
        """Handle state change of the source select entity."""
        new_state = event.data.get("new_state")
        if not new_state or not new_state.state or new_state.state in ("unknown", "unavailable"):
            _LOGGER.warning("[%s] Source select entity changed to an invalid state: %s", self.mac_address, new_state)
            return

        source_entity_id = new_state.state
        _LOGGER.info("[%s] Source select entity changed to %s, triggering update check.", self.mac_address, source_entity_id)

        # Get mode from mode select entity
        mode_select_entity_id = f"select.{self.formatted_mac.replace(':', '').lower()}_update_mode"
        mode_state = self.hass.states.get(mode_select_entity_id)
        mode = "bwr"
        if mode_state and mode_state.state in ("bw", "bwr"):
            mode = mode_state.state

        # Trigger update (which includes the check for differences)
        await self._trigger_update_from_source(source_entity_id, mode)

    async def _trigger_update_from_source(self, source_entity_id: str, mode: str) -> None:
        """Fetch image from source entity and send it if different from last uploaded."""
        # Check if auto-update is enabled first
        if not self._auto_update_enabled:
            _LOGGER.debug("[%s] Auto-update is disabled, skipping update from source %s", self.mac_address, source_entity_id)
            return

        if not self.is_available:
            _LOGGER.warning("[%s] Device unavailable, skipping auto-update", self.mac_address)
            return
        if self._send_lock.locked():
            _LOGGER.warning("[%s] Send operation already in progress, skipping auto-update", self.mac_address)
            return

        async with self._send_lock:
            try:
                image_state = self.hass.states.get(source_entity_id)
                if image_state is None:
                    _LOGGER.error("[%s] Source entity not found: %s", self.mac_address, source_entity_id)
                    return
                image_url = image_state.attributes.get("entity_picture")
                if not image_url:
                    _LOGGER.error("[%s] No entity_picture attribute in source entity: %s", self.mac_address, source_entity_id)
                    return
                if image_url.startswith("/"):
                    try:
                        from homeassistant.helpers.network import get_url
                        base_url = get_url(self.hass)
                    except Exception:
                        base_url = self.hass.config.internal_url or self.hass.config.external_url or ""
                    image_url = f"{base_url}{image_url}"
                session = aiohttp_client.async_get_clientsession(self.hass)
                async with async_timeout.timeout(10):
                    response = await session.get(image_url)
                    response.raise_for_status()
                    image_bytes = await response.read()
                _LOGGER.info("[%s] Fetched %d bytes from source entity %s", self.mac_address, len(image_bytes), source_entity_id)
            except Exception as e:
                _LOGGER.error("[%s] Failed to fetch image from source entity %s: %s", self.mac_address, source_entity_id, e)
                from .const import STATE_ERROR_IMAGE_FETCH
                from .const import STATE_ERROR_IMAGE_FETCH
                self._update_state(STATE_ERROR_IMAGE_FETCH, f"Fetch failed: {e}")
                return

            # Compare with last uploaded image
            if self._last_image_bytes is not None and self._last_image_bytes == image_bytes:
                _LOGGER.info("[%s] Source image unchanged, skipping update", self.mac_address)
                return

            # Call internal send method
            success = await self._async_send_image_internal(image_bytes, mode)
            if success:
                _LOGGER.info("[%s] Auto-update successful", self.mac_address)
            else:
                _LOGGER.warning("[%s] Auto-update failed", self.mac_address)