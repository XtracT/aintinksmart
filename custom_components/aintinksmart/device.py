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

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import STATE_UNAVAILABLE as HA_STATE_UNAVAILABLE # Avoid confusion
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util # Import datetime utility

# Import constants, helpers, and comms module
from .const import (
    DOMAIN,
    CONF_MAC,
    STATE_IDLE,
    STATE_CONNECTING,
    STATE_SENDING,
    STATE_ERROR,
    STATE_SUCCESS,
    ATTR_LAST_UPDATE,
    ATTR_LAST_ERROR,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
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

_LOGGER = logging.getLogger(__name__)

# Timeout for the entire send operation
SEND_TIMEOUT = 90.0 # Seconds

class AintinksmartDevice:
    """Manages state and communication for a single Ain't Ink Smart device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the device manager."""
        self.hass = hass
        self.entry = entry
        self.mac_address = entry.data[CONF_MAC]
        self.formatted_mac = dr.format_mac(self.mac_address)
        self.name = f"Ain't Ink Smart {self.mac_address}"

        self._ble_device: BLEDevice | None = None
        self._status: str = STATE_IDLE
        self._last_error: str | None = None
        self._last_update: datetime | None = None
        self._last_image_bytes: bytes | None = None
        self._send_lock = asyncio.Lock() # Prevent concurrent sends
        self._update_listeners: list[callable] = [] # Simple listener pattern for now
        self._cancel_bluetooth_callback: callable | None = None

        self._image_processor = ImageProcessor()
        self._protocol_formatter = ProtocolFormatter()
        self._packet_builder = PacketBuilder()

    @property
    def is_available(self) -> bool:
        """Return True if the device is considered available."""
        # Available if we have a BLEDevice object associated
        return self._ble_device is not None

    @property
    def state_data(self) -> dict[str, Any]:
        """Return the current state data for entities."""
        return {
            "status": self._status if self.is_available else HA_STATE_UNAVAILABLE,
            ATTR_LAST_ERROR: self._last_error,
            ATTR_LAST_UPDATE: self._last_update,
            "last_image_bytes": self._last_image_bytes, # For camera
            "is_available": self.is_available,
        }

    async def async_init(self) -> None:
        """Perform initial setup and try to find the BLE device."""
        _LOGGER.debug("[%s] Initializing device manager", self.mac_address)
        self._ble_device = async_ble_device_from_address(self.hass, self.mac_address.upper(), connectable=True)
        if not self._ble_device:
            _LOGGER.warning("[%s] Device not found initially via Bluetooth", self.mac_address)
            # Optionally raise ConfigEntryNotReady here if initial connection is mandatory
            # raise ConfigEntryNotReady(f"Device {self.mac_address} not found")

        # Register callback for Bluetooth device updates
        self._cancel_bluetooth_callback = async_register_callback(
            self.hass, self._handle_bluetooth_update, {"address": self.mac_address.upper()}, mode="active"
        )
        self._update_state(STATE_IDLE if self.is_available else HA_STATE_UNAVAILABLE)

    @callback
    def _handle_bluetooth_update(
        self, service_info: BluetoothServiceInfoBleak, change: Any # change type depends on HA version
    ) -> None:
        """Handle updated Bluetooth device data."""
        _LOGGER.debug("[%s] Bluetooth update received: %s", self.mac_address, service_info)
        self._ble_device = service_info.device
        # Update state if availability changed
        if self._status == HA_STATE_UNAVAILABLE and self.is_available:
             self._update_state(STATE_IDLE)
        elif self._status != HA_STATE_UNAVAILABLE and not self.is_available:
             self._update_state(HA_STATE_UNAVAILABLE, "Device became unavailable")
        else:
             self._notify_listeners() # Notify even if state didn't change, maybe RSSI updated


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
                    self._update_state(STATE_ERROR, f"Failed to get image from entity: {e}")
                    return # Abort send
                except Exception as e:
                    _LOGGER.exception("[%s] Unexpected error fetching image from entity %s", self.mac_address, image_entity_id)
                    self._update_state(STATE_ERROR, f"Unexpected error getting image from entity: {e}")
                    return # Abort send

            elif image_data_b64:
                _LOGGER.info("[%s] Decoding base64 image data", self.mac_address)
                try:
                    image_bytes = base64.b64decode(image_data_b64)
                except (TypeError, ValueError, binascii.Error) as e:
                    _LOGGER.error("[%s] Invalid base64 image data provided: %s", self.mac_address, e)
                    self._update_state(STATE_ERROR, f"Invalid base64 data: {e}")
                    return # Abort send
            else:
                _LOGGER.error("[%s] Service call missing image_data or image_entity_id", self.mac_address)
                self._update_state(STATE_ERROR, "No image source provided")
                return # Abort send

            if not image_bytes:
                 _LOGGER.error("[%s] Image data is empty after processing input", self.mac_address)
                 self._update_state(STATE_ERROR, "Image data is empty")
                 return # Abort send

            # --- Start actual send process ---
            self._update_state(STATE_CONNECTING)
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

                    # 4. Send via BLE
                    self._update_state(STATE_SENDING)
                    if self._ble_device is None: # Re-check availability
                         raise BleCommunicationError("BLE device became unavailable before sending")

                    success = await async_send_packets_ble(self.hass, self._ble_device, packets)

                if success:
                    self._update_state(STATE_SUCCESS)
                    self._last_image_bytes = image_bytes # Store for camera on success
                else:
                    # Should not happen if async_send_packets_ble raises on failure
                    self._update_state(STATE_ERROR, "Sending failed (unknown reason)")

            except (
                ImageProcessingError,
                ProtocolFormattingError,
                PacketBuilderError,
                BleCommunicationError,
                BleakError, # Catch BleakError directly too
                asyncio.TimeoutError,
            ) as e:
                _LOGGER.error("[%s] Send operation failed: %s", self.mac_address, e)
                self._update_state(STATE_ERROR, f"Send failed: {e}")
            except Exception as e:
                _LOGGER.exception("[%s] Unexpected error during send operation", self.mac_address)
                self._update_state(STATE_ERROR, f"Unexpected error: {e}")
            finally:
                 # Ensure state is not left as connecting/sending if an error occurred
                 if self._status in [STATE_CONNECTING, STATE_SENDING] and not success:
                      if not self._last_error: # Avoid overwriting specific error
                           self._update_state(STATE_ERROR, "Send operation did not complete")
                      else:
                           self._update_state(STATE_ERROR, self._last_error) # Keep existing error


    @callback
    def _update_state(self, new_state: str, error: str | None = None) -> None:
        """Update the internal state and notify listeners."""
        self._status = new_state
        self._last_error = error if error else None
        self._last_update = dt_util.utcnow()
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

    async def async_unload(self) -> None:
        """Clean up resources."""
        _LOGGER.debug("[%s] Unloading device manager", self.mac_address)
        if self._cancel_bluetooth_callback:
            self._cancel_bluetooth_callback()
            self._cancel_bluetooth_callback = None
        # Cancel any pending tasks if necessary (e.g., if using background tasks)
        self._update_listeners.clear()