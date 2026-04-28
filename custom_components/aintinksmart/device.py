"""Device manager class for Ain't Ink Smart."""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from datetime import datetime
from typing import Any

import async_timeout
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
    async_scanner_count,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import STATE_UNAVAILABLE as HA_STATE_UNAVAILABLE
from homeassistant.helpers import aiohttp_client, device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_MAC,
    STATE_IDLE,
    STATE_CONNECTING,
    STATE_SENDING,
    STATE_ERROR,
    STATE_SUCCESS,
    STATE_ERROR_CONNECTION,
    STATE_ERROR_TIMEOUT,
    STATE_ERROR_SEND,
    STATE_ERROR_IMAGE_FETCH,
    STATE_ERROR_IMAGE_PROCESS,
    STATE_ERROR_UNKNOWN,
    ATTR_LAST_UPDATE,
    ATTR_LAST_ERROR,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
    NUMBER_KEY_PACKET_DELAY,
    DEFAULT_PACKET_DELAY_MS,
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

SEND_TIMEOUT = 90.0


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
        self._cancel_bluetooth_callback: callable | None = None

        self._status: str = STATE_IDLE
        self._last_error: str | None = None
        self._last_update: datetime | None = None
        self._last_image_bytes: bytes | None = None
        self._pending_image_bytes: bytes | None = None
        self._send_lock = asyncio.Lock()
        self._update_listeners: list[callable] = []
        self._auto_update_enabled: bool = True

        self._image_processor = ImageProcessor()
        self._protocol_formatter = ProtocolFormatter()
        self._packet_builder = PacketBuilder()

        self._cancel_state_listener: callable | None = None

    @property
    def is_available(self) -> bool:
        """Return True if the device is available via BLE."""
        return async_scanner_count(self.hass, connectable=True) > 0 and self._ble_device is not None

    @property
    def state_data(self) -> dict[str, Any]:
        """Return the current state data for entities."""
        is_available = self.is_available
        return {
            "status": self._status if is_available else HA_STATE_UNAVAILABLE,
            ATTR_LAST_ERROR: self._last_error,
            ATTR_LAST_UPDATE: self._last_update,
            "last_image_bytes": self._last_image_bytes,
            "is_available": is_available,
        }

    async def async_init(self) -> None:
        """Perform initial setup."""
        _LOGGER.debug("[%s] Initializing device manager", self.mac_address)

        if async_scanner_count(self.hass, connectable=True) < 1:
            _LOGGER.warning("[%s] Bluetooth scanner is not available or enabled", self.mac_address)
            self._update_state(HA_STATE_UNAVAILABLE, "Bluetooth not available")
        else:
            self._ble_device = async_ble_device_from_address(self.hass, self.mac_address.upper(), connectable=True)
            if not self._ble_device:
                _LOGGER.warning("[%s] BLE device not found initially", self.mac_address)

            self._cancel_bluetooth_callback = async_register_callback(
                self.hass, self._handle_bluetooth_update, {"address": self.mac_address.upper()}, mode="active"
            )
            self._update_state(STATE_IDLE if self.is_available else HA_STATE_UNAVAILABLE)

        self.hass.bus.async_listen_once("homeassistant_started", self._async_post_startup)

    async def _async_post_startup(self, event):
        """Set up listeners after HA has started."""
        _LOGGER.debug("[%s] Home Assistant started, setting up listeners", self.mac_address)
        self._setup_source_listener()

    @callback
    def _handle_bluetooth_update(
        self, service_info: BluetoothServiceInfoBleak, change: Any
    ) -> None:
        """Handle updated Bluetooth device data."""
        _LOGGER.debug("[%s] Bluetooth update received: %s", self.mac_address, service_info.device)
        was_available = self.is_available
        self._ble_device = service_info.device
        now_available = self.is_available

        if not was_available and now_available:
            self._update_state(STATE_IDLE)
        elif was_available and not now_available:
            self._update_state(HA_STATE_UNAVAILABLE, "Device became unavailable")
        elif self._status == HA_STATE_UNAVAILABLE and now_available:
            self._update_state(STATE_IDLE)
        else:
            self._notify_listeners()

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
            mode = call.data.get(ATTR_MODE)

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
                    image_url = image_state.attributes.get("entity_picture")
                    if not image_url:
                         raise vol.Invalid(f"Could not get image URL from entity: {image_entity_id}")

                    if image_url.startswith("/"):
                         image_url = f"{self.hass.config.internal_url}{image_url}"

                    session = aiohttp_client.async_get_clientsession(self.hass)
                    async with async_timeout.timeout(10):
                        response = await session.get(image_url)
                        response.raise_for_status()
                        image_bytes = await response.read()
                    _LOGGER.info("[%s] Successfully fetched %d bytes from %s", self.mac_address, len(image_bytes), image_entity_id)
                except (aiohttp_client.ClientError, asyncio.TimeoutError, vol.Invalid) as e:
                    _LOGGER.error("[%s] Failed to fetch or process image from entity %s: %s", self.mac_address, image_entity_id, e)
                    self._update_state(STATE_ERROR_IMAGE_FETCH, f"Failed to get image from entity: {e}")
                    return
                except Exception as e:
                    _LOGGER.exception("[%s] Unexpected error fetching image from entity %s", self.mac_address, image_entity_id)
                    self._update_state(STATE_ERROR_UNKNOWN, f"Unexpected error getting image from entity: {e}")
                    return

            elif image_data_b64:
                _LOGGER.info("[%s] Decoding base64 image data", self.mac_address)
                try:
                    image_bytes = base64.b64decode(image_data_b64)
                except (TypeError, ValueError, binascii.Error) as e:
                    _LOGGER.error("[%s] Invalid base64 image data provided: %s", self.mac_address, e)
                    self._update_state(STATE_ERROR_IMAGE_PROCESS, f"Invalid base64 data: {e}")
                    return
            else:
                _LOGGER.error("[%s] Service call missing image_data or image_entity_id", self.mac_address)
                self._update_state(STATE_ERROR_UNKNOWN, "No image source provided")
                return

            await self._async_send_image_internal(image_bytes, mode)

    async def _async_send_image_internal(self, image_bytes: bytes, mode: str) -> bool:
        """Process, format, build packets, and send image via BLE."""
        self._update_state(STATE_CONNECTING)
        self._pending_image_bytes = image_bytes
        success = False
        try:
            async with async_timeout.timeout(SEND_TIMEOUT):
                _LOGGER.debug("[%s] Processing image...", self.mac_address)
                processed_data = self._image_processor.process_image(image_bytes, mode)

                _LOGGER.debug("[%s] Formatting payload...", self.mac_address)
                hex_payload = self._protocol_formatter.format_payload(processed_data)

                _LOGGER.debug("[%s] Building packets...", self.mac_address)
                packets = self._packet_builder.build_packets(hex_payload, self.mac_address)

                self._update_state(STATE_SENDING)

                # Get packet delay from number entity
                delay_ms = DEFAULT_PACKET_DELAY_MS
                ent_reg = er.async_get(self.hass)
                number_unique_id = f"{self.entry.entry_id}_{NUMBER_KEY_PACKET_DELAY}"
                delay_entity_id = ent_reg.async_get_entity_id("number", DOMAIN, number_unique_id)

                if delay_entity_id:
                    state = self.hass.states.get(delay_entity_id)
                    if state and state.state not in (None, HA_STATE_UNAVAILABLE, "unknown"):
                        try:
                            delay_ms = int(float(state.state))
                            if delay_ms < 1:
                                delay_ms = DEFAULT_PACKET_DELAY_MS
                            else:
                                _LOGGER.debug("[%s] Using packet delay: %d ms", self.mac_address, delay_ms)
                        except (ValueError, TypeError):
                            delay_ms = DEFAULT_PACKET_DELAY_MS

                if not self.is_available or self._ble_device is None:
                    raise BleCommunicationError("BLE device became unavailable before sending")
                success = await async_send_packets_ble(self.hass, self._ble_device, packets, delay_ms)
                if success:
                    self._update_state(STATE_SUCCESS)
                else:
                    if self._status == STATE_SENDING:
                        self._update_state(STATE_ERROR_SEND, "BLE send command returned false")

        except (
            ImageProcessingError,
            ProtocolFormattingError,
            PacketBuilderError,
            BleCommunicationError,
            BleakError,
            asyncio.TimeoutError,
        ) as e:
            _LOGGER.error("[%s] Send operation failed: %s", self.mac_address, e)
            error_state = STATE_ERROR_UNKNOWN
            error_message = f"Send failed: {e}"

            if isinstance(e, (ImageProcessingError, ProtocolFormattingError, PacketBuilderError)):
                error_state = STATE_ERROR_IMAGE_PROCESS
            elif isinstance(e, BleCommunicationError):
                error_state = STATE_ERROR_CONNECTION
            elif isinstance(e, BleakError):
                error_state = STATE_ERROR_SEND
            elif isinstance(e, asyncio.TimeoutError):
                error_state = STATE_ERROR_TIMEOUT
                error_message = "Send operation timed out"

            self._update_state(error_state, error_message)
            success = False
        except Exception as e:
            _LOGGER.exception("[%s] Unexpected error during send operation", self.mac_address)
            self._update_state(STATE_ERROR_UNKNOWN, f"Unexpected error: {e}")
            success = False
        finally:
            if self._status in [STATE_CONNECTING, STATE_SENDING]:
                _LOGGER.warning("[%s] Send operation finished in intermediate state: %s", self.mac_address, self._status)
                if not self._last_error:
                    self._update_state(STATE_ERROR_UNKNOWN, "Send operation did not complete successfully")
            if not success or self._status != STATE_SUCCESS:
                self._pending_image_bytes = None

        return success

    @callback
    def _update_state(self, new_state: str, error: str | None = None) -> None:
        """Update the internal state and notify listeners."""
        if new_state == self._status and error == self._last_error:
            return

        self._status = new_state
        self._last_error = error if error else None
        self._last_update = dt_util.utcnow()

        if new_state == STATE_SUCCESS and self._pending_image_bytes is not None:
            _LOGGER.debug("[%s] Storing successfully sent image (%d bytes)", self.mac_address, len(self._pending_image_bytes))
            self._last_image_bytes = self._pending_image_bytes
            self._pending_image_bytes = None
        elif new_state != STATE_SENDING and new_state != STATE_CONNECTING:
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
            pass

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

    async def async_unload(self) -> None:
        """Clean up resources."""
        _LOGGER.debug("[%s] Unloading device manager", self.mac_address)

        if self._cancel_bluetooth_callback:
            self._cancel_bluetooth_callback()
            self._cancel_bluetooth_callback = None

        if self._cancel_state_listener:
            self._cancel_state_listener()
            self._cancel_state_listener = None

        self._update_listeners.clear()

    def _setup_source_listener(self) -> None:
        """Set up the state listener for the source image entity."""
        ent_reg = er.async_get(self.hass)
        source_select_unique_id = f"{self.entry.entry_id}_source_entity"
        source_select_entity_id = ent_reg.async_get_entity_id("select", DOMAIN, source_select_unique_id)

        if not source_select_entity_id:
            _LOGGER.warning("[%s] Source select entity not found in registry, cannot listen for changes.", self.mac_address)
            return

        _LOGGER.info("[%s] Listening for changes to source select entity: %s", self.mac_address, source_select_entity_id)
        self._cancel_state_listener = async_track_state_change_event(
            self.hass,
            [source_select_entity_id],
            self._handle_source_select_update,
        )

    async def _handle_source_select_update(self, event) -> None:
        """Handle state change of the source select entity."""
        new_state = event.data.get("new_state")
        if not new_state or not new_state.state or new_state.state in ("unknown", "unavailable"):
            _LOGGER.warning("[%s] Source select entity changed to an invalid state: %s", self.mac_address, new_state)
            return

        source_entity_id = new_state.state
        _LOGGER.info("[%s] Source select entity changed to %s, triggering update check.", self.mac_address, source_entity_id)

        mode_select_entity_id = f"select.{self.formatted_mac.replace(':', '').lower()}_update_mode"
        mode_state = self.hass.states.get(mode_select_entity_id)
        mode = "bwr"
        if mode_state and mode_state.state in ("bw", "bwr"):
            mode = mode_state.state

        await self._trigger_update_from_source(source_entity_id, mode)

    async def _trigger_update_from_source(self, source_entity_id: str, mode: str) -> None:
        """Fetch image from source entity and send it if different from last uploaded."""
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
                self._update_state(STATE_ERROR_IMAGE_FETCH, f"Fetch failed: {e}")
                return

            if self._last_image_bytes is not None and self._last_image_bytes == image_bytes:
                _LOGGER.info("[%s] Source image unchanged, skipping update", self.mac_address)
                return

            success = await self._async_send_image_internal(image_bytes, mode)
            if success:
                _LOGGER.info("[%s] Auto-update successful", self.mac_address)
            else:
                _LOGGER.warning("[%s] Auto-update failed", self.mac_address)
