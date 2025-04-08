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
        self._send_lock = asyncio.Lock()  # Prevent concurrent sends
        self._update_listeners: list[callable] = []  # Simple listener pattern for now
        self._cancel_bluetooth_callback: callable | None = None

        self._image_processor = ImageProcessor()
        self._protocol_formatter = ProtocolFormatter()
        self._packet_builder = PacketBuilder()

        # Options and listeners for auto-update
        self._options = dict(entry.options)
        self._cancel_state_listener: callable | None = None
        self._options_update_remove: callable | None = None
        self._options_update_remove = entry.add_update_listener(self._handle_options_update)

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

        # Setup source listener and trigger initial update if enabled
        # Defer listener setup until HA is fully started
        self.hass.bus.async_listen_once(
            "homeassistant_started", self._async_post_startup
        )

    async def _async_post_startup(self, event):
        """Set up listeners after HA has started."""
        _LOGGER.debug("[%s] Home Assistant started, setting up listeners", self.mac_address)
        self._setup_source_listener()

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
        """Process, format, build packets, and send image via BLE. Return True on success."""
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
                if self._ble_device is None:
                    raise BleCommunicationError("BLE device became unavailable before sending")

                success = await async_send_packets_ble(self.hass, self._ble_device, packets)

            if success:
                self._update_state(STATE_SUCCESS)
                self._last_image_bytes = image_bytes  # Store for camera on success
            else:
                from .const import STATE_ERROR_SEND
                from .const import STATE_ERROR_SEND
                self._update_state(STATE_ERROR_SEND, "Sending failed (unknown reason)")

        except (
            ImageProcessingError,
            ProtocolFormattingError,
            PacketBuilderError,
            BleCommunicationError,
            BleakError,
            asyncio.TimeoutError,
        ) as e:
            _LOGGER.error("[%s] Send operation failed: %s", self.mac_address, e)
            from .const import STATE_ERROR_SEND, STATE_ERROR_IMAGE_PROCESS, STATE_ERROR_CONNECTION, STATE_ERROR_TIMEOUT
            if isinstance(e, (ImageProcessingError, ProtocolFormattingError, PacketBuilderError)):
                error_state = STATE_ERROR_IMAGE_PROCESS
            elif isinstance(e, BleCommunicationError):
                error_state = STATE_ERROR_CONNECTION
            elif isinstance(e, asyncio.TimeoutError):
                error_state = STATE_ERROR_TIMEOUT
            else: # BleakError
                error_state = STATE_ERROR_SEND
            from .const import STATE_ERROR_SEND, STATE_ERROR_IMAGE_PROCESS, STATE_ERROR_CONNECTION, STATE_ERROR_TIMEOUT
            if isinstance(e, (ImageProcessingError, ProtocolFormattingError, PacketBuilderError)):
                error_state = STATE_ERROR_IMAGE_PROCESS
            elif isinstance(e, BleCommunicationError):
                error_state = STATE_ERROR_CONNECTION
            elif isinstance(e, asyncio.TimeoutError):
                error_state = STATE_ERROR_TIMEOUT
            else: # BleakError
                error_state = STATE_ERROR_SEND
            self._update_state(error_state, f"Send failed: {e}")
        except Exception as e:
            _LOGGER.exception("[%s] Unexpected error during send operation", self.mac_address)
            from .const import STATE_ERROR_UNKNOWN
            from .const import STATE_ERROR_UNKNOWN
            self._update_state(STATE_ERROR_UNKNOWN, f"Unexpected error: {e}")
        finally:
            if self._status in [STATE_CONNECTING, STATE_SENDING] and not success:
                if not self._last_error:
                    # Keep the specific error state if already set
                    if self._status not in [STATE_ERROR_CONNECTION, STATE_ERROR_TIMEOUT, STATE_ERROR_SEND, STATE_ERROR_IMAGE_PROCESS, STATE_ERROR_UNKNOWN]:
                        from .const import STATE_ERROR_UNKNOWN
                        self._update_state(STATE_ERROR_UNKNOWN, "Send operation did not complete")
                    # else: # Keep existing error state and message
                    #    self._update_state(self._status, self._last_error)
        return success


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
        if self._cancel_state_listener:
            self._cancel_state_listener()
            self._cancel_state_listener = None
        if self._options_update_remove:
            self._options_update_remove()
            self._options_update_remove = None
        # Cancel any pending tasks if necessary (e.g., if using background tasks)
        self._update_listeners.clear()

    async def _handle_options_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Handle options update."""
        _LOGGER.debug("[%s] Options updated, reloading options and listeners", self.mac_address)
        self._options = dict(entry.options)
        self._setup_source_listener()

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