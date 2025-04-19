"""MQTT Communication for Ain't Ink Smart."""
from __future__ import annotations

import asyncio
import binascii
import json
import logging
from typing import TYPE_CHECKING

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice

_LOGGER = logging.getLogger(__name__)

class MqttCommunicationError(Exception):
    """Custom exception for MQTT communication errors."""

async def async_send_packets_mqtt(
    hass: HomeAssistant,
    base_topic: str,
    mac_address: str,
    packets: list[bytes], # Changed type hint
    packet_delay_ms: int,
) -> bool:
    """
    Send image packets to the display via MQTT gateway.

    Args:
        hass: HomeAssistant instance.
        base_topic: The base MQTT topic for the gateway (e.g., 'aintinksmart/gateway').
        mac_address: The MAC address of the target display (used in topic).
        packets: A list of bytes packets to send.
        packet_delay_ms: Delay between sending packets in milliseconds.

    Returns:
        True if all packets were published successfully, False otherwise.

    Raises:
        MqttCommunicationError: If there's an error publishing to MQTT.
    """
    if not packets:
        _LOGGER.warning("[%s] No packets provided for MQTT send", mac_address)
        return False

    if not base_topic:
        raise MqttCommunicationError(f"[{mac_address}] MQTT base topic is not configured")

    mac_no_colons = mac_address.replace(":", "").lower()
    start_topic = f"{base_topic}/display/{mac_no_colons}/command/start"
    packet_topic = f"{base_topic}/display/{mac_no_colons}/command/packet"
    # end_topic = f"{base_topic}/display/{mac_no_colons}/command/end" # Not currently used by firmware

    packet_count = len(packets)
    start_payload = json.dumps({"total_packets": packet_count}) # Match app format
    delay_sec = packet_delay_ms / 1000.0

    _LOGGER.info(
        "[%s] Sending %d packets via MQTT to base topic '%s' (Delay: %.3f s)",
        mac_address, packet_count, base_topic, delay_sec
    )

    try:
        # Send start command
        _LOGGER.debug("[%s] Publishing to %s: %s", mac_address, start_topic, start_payload)
        await mqtt.async_publish(hass, start_topic, start_payload, qos=1, retain=False)
        await asyncio.sleep(delay_sec) # Small delay after start command

        # Send packets sequentially
        for i, packet_bytes in enumerate(packets):
            hex_packet_payload = binascii.hexlify(packet_bytes).upper().decode() # Convert bytes to uppercase hex string
            _LOGGER.debug("[%s] Publishing packet %d/%d to %s", mac_address, i + 1, packet_count, packet_topic)
            await mqtt.async_publish(hass, packet_topic, hex_packet_payload, qos=1, retain=False)
            # Only sleep if not the last packet
            if i < packet_count - 1:
                await asyncio.sleep(delay_sec)

        # Send end command (Optional, if firmware requires it later)
        # _LOGGER.debug("[%s] Publishing to %s: END", mac_address, end_topic)
        # await mqtt.async_publish(hass, end_topic, "END", qos=1, retain=False)

        _LOGGER.info("[%s] Successfully published all %d packets via MQTT", mac_address, packet_count)
        return True

    except HomeAssistantError as e:
        _LOGGER.error("[%s] Failed to publish MQTT message: %s", mac_address, e)
        raise MqttCommunicationError(f"MQTT publish failed: {e}") from e
    except Exception as e:
        _LOGGER.exception("[%s] Unexpected error during MQTT send", mac_address)
        raise MqttCommunicationError(f"Unexpected MQTT error: {e}") from e