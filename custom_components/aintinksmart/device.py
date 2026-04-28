"""Device manager class for Ain't Ink Smart."""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

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
    ATTR_IMAGE_PATH,
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

        self.status: str = STATE_IDLE
        self.last_error: str | None = None
        self.last_update: datetime | None = None
        self._send_lock = asyncio.Lock()
        self._update_listeners: list[callable] = []

        self._image_processor = ImageProcessor()
        self._protocol_formatter = ProtocolFormatter()
        self._packet_builder = PacketBuilder()

    @property
    def is_available(self) -> bool:
        """Return True if the device is available via BLE."""
        return async_scanner_count(self.hass, connectable=True) > 0 and self._ble_device is not None

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

    @callback
    def _handle_bluetooth_update(
        self, service_info: BluetoothServiceInfoBleak, change: Any
    ) -> None:
        """Handle updated Bluetooth device data."""
        was_available = self.is_available
        self._ble_device = service_info.device
        now_available = self.is_available

        if not was_available and now_available:
            self._update_state(STATE_IDLE)
        elif was_available and not now_available:
            self._update_state(HA_STATE_UNAVAILABLE, "Device became unavailable")
        elif self.status == HA_STATE_UNAVAILABLE and now_available:
            self._update_state(STATE_IDLE)
        else:
            self._notify_listeners()

    async def async_handle_send_image(self, call: ServiceCall) -> None:
        """Handle the send_image service call."""
        if not self.is_available:
            _LOGGER.error("[%s] Cannot send image: Device is unavailable", self.mac_address)
            raise vol.Invalid("Device is unavailable")

        if self._send_lock.locked():
            _LOGGER.warning("[%s] Send operation already in progress", self.mac_address)
            raise vol.Invalid("Send operation already in progress")

        async with self._send_lock:
            mode = call.data.get(ATTR_MODE)
            if not mode or mode not in ('bw', 'bwr'):
                raise vol.Invalid(f"Invalid mode: {mode}. Must be 'bw' or 'bwr'.")

            image_bytes = await self._resolve_image(call.data)
            if image_bytes is None:
                return

            await self._send(image_bytes, mode)

    async def _resolve_image(self, data: dict) -> bytes | None:
        """Resolve image bytes from service call data. Returns None on error (sets state)."""
        image_path = data.get(ATTR_IMAGE_PATH)
        image_data_b64 = data.get(ATTR_IMAGE_DATA)
        image_entity_id = data.get(ATTR_IMAGE_ENTITY_ID)

        if image_path:
            return await self._read_image_path(image_path)
        elif image_data_b64:
            return self._decode_base64(image_data_b64)
        elif image_entity_id:
            return await self._fetch_from_entity(image_entity_id)
        else:
            self._update_state(STATE_ERROR_IMAGE_FETCH, "No image source provided (use image_path, image_data, or image_entity_id)")
            return None

    async def _read_image_path(self, path: str) -> bytes | None:
        """Read image from local file path or URL."""
        parsed = urlparse(path)

        if parsed.scheme in ('http', 'https'):
            return await self._fetch_url(path)

        if not os.path.isfile(path):
            self._update_state(STATE_ERROR_IMAGE_FETCH, f"File not found: {path}")
            return None

        try:
            with open(path, 'rb') as f:
                image_bytes = f.read()
            _LOGGER.info("[%s] Read %d bytes from %s", self.mac_address, len(image_bytes), path)
            return image_bytes
        except OSError as e:
            self._update_state(STATE_ERROR_IMAGE_FETCH, f"Failed to read file: {e}")
            return None

    async def _fetch_url(self, url: str) -> bytes | None:
        """Fetch image from HTTP/HTTPS URL."""
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with async_timeout.timeout(15):
                response = await session.get(url)
                response.raise_for_status()
                image_bytes = await response.read()
            _LOGGER.info("[%s] Fetched %d bytes from %s", self.mac_address, len(image_bytes), url)
            return image_bytes
        except Exception as e:
            self._update_state(STATE_ERROR_IMAGE_FETCH, f"Failed to fetch URL: {e}")
            return None

    def _decode_base64(self, data: str) -> bytes | None:
        """Decode base64 image data."""
        try:
            image_bytes = base64.b64decode(data)
            _LOGGER.info("[%s] Decoded %d bytes from base64", self.mac_address, len(image_bytes))
            return image_bytes
        except (TypeError, ValueError, binascii.Error) as e:
            self._update_state(STATE_ERROR_IMAGE_PROCESS, f"Invalid base64 data: {e}")
            return None

    async def _fetch_from_entity(self, entity_id: str) -> bytes | None:
        """Fetch image from a Home Assistant camera or image entity."""
        try:
            image_state = self.hass.states.get(entity_id)
            if image_state is None:
                raise vol.Invalid(f"Entity not found: {entity_id}")
            image_url = image_state.attributes.get("entity_picture")
            if not image_url:
                raise vol.Invalid(f"No entity_picture attribute on: {entity_id}")
            if image_url.startswith("/"):
                image_url = f"{self.hass.config.internal_url}{image_url}"
            return await self._fetch_url(image_url)
        except Exception as e:
            self._update_state(STATE_ERROR_IMAGE_FETCH, f"Failed to fetch from entity {entity_id}: {e}")
            return None

    async def _send(self, image_bytes: bytes, mode: str) -> None:
        """Process and send image bytes via BLE."""
        self._update_state(STATE_CONNECTING)
        success = False
        try:
            async with async_timeout.timeout(SEND_TIMEOUT):
                processed_data = self._image_processor.process_image(image_bytes, mode)
                hex_payload = self._protocol_formatter.format_payload(processed_data)
                packets = self._packet_builder.build_packets(hex_payload, self.mac_address)

                self._update_state(STATE_SENDING)

                delay_ms = self._get_packet_delay()

                if not self.is_available or self._ble_device is None:
                    raise BleCommunicationError("BLE device became unavailable before sending")

                success = await async_send_packets_ble(self.hass, self._ble_device, packets, delay_ms)
                if success:
                    self._update_state(STATE_SUCCESS)
                elif self.status == STATE_SENDING:
                    self._update_state(STATE_ERROR_SEND, "BLE send returned false")

        except (ImageProcessingError, ProtocolFormattingError, PacketBuilderError) as e:
            _LOGGER.error("[%s] Image/protocol error: %s", self.mac_address, e)
            self._update_state(STATE_ERROR_IMAGE_PROCESS, str(e))
        except (BleCommunicationError, BleakError) as e:
            _LOGGER.error("[%s] BLE error: %s", self.mac_address, e)
            self._update_state(STATE_ERROR_SEND if isinstance(e, BleakError) else STATE_ERROR_CONNECTION, str(e))
        except asyncio.TimeoutError:
            _LOGGER.error("[%s] Send timed out", self.mac_address)
            self._update_state(STATE_ERROR_TIMEOUT, "Send operation timed out")
        except Exception as e:
            _LOGGER.exception("[%s] Unexpected error during send", self.mac_address)
            self._update_state(STATE_ERROR_UNKNOWN, str(e))
        finally:
            if self.status in (STATE_CONNECTING, STATE_SENDING):
                if not self.last_error:
                    self._update_state(STATE_ERROR_UNKNOWN, "Send did not complete")

    def _get_packet_delay(self) -> int:
        """Read packet delay from the number entity, or return default."""
        ent_reg = er.async_get(self.hass)
        unique_id = f"{self.entry.entry_id}_{NUMBER_KEY_PACKET_DELAY}"
        entity_id = ent_reg.async_get_entity_id("number", DOMAIN, unique_id)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state and state.state not in (None, HA_STATE_UNAVAILABLE, "unknown"):
                try:
                    delay = int(float(state.state))
                    if delay >= 1:
                        return delay
                except (ValueError, TypeError):
                    pass
        return DEFAULT_PACKET_DELAY_MS

    @callback
    def _update_state(self, new_state: str, error: str | None = None) -> None:
        """Update the internal state and notify listeners."""
        if new_state == self.status and error == self.last_error:
            return
        self.status = new_state
        self.last_error = error
        self.last_update = dt_util.utcnow()
        _LOGGER.info("[%s] State: %s (Error: %s)", self.mac_address, self.status, self.last_error)
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

    async def async_unload(self) -> None:
        """Clean up resources."""
        _LOGGER.debug("[%s] Unloading device manager", self.mac_address)
        if self._cancel_bluetooth_callback:
            self._cancel_bluetooth_callback()
            self._cancel_bluetooth_callback = None
        self._update_listeners.clear()
