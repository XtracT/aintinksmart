"""BLE Communication helpers for Ain't Ink Smart."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from bleak import BleakClient # Import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant

from .const import IMG_CHAR_UUID

_LOGGER = logging.getLogger(__name__)

# Packet delay is now configurable via number entity

class BleCommunicationError(Exception):
    """Custom exception for BLE communication errors."""
    pass

async def async_send_packets_ble(
    hass: HomeAssistant,
    ble_device: BLEDevice,
    packets: List[bytes],
    packet_delay_ms: int, # Delay between packets in milliseconds
) -> bool:
    """
    Connects to the BLE device and sends the provided packets.

    Args:
        hass: HomeAssistant instance.
        ble_device: The target BLEDevice object.
        packets: A list of byte arrays, each representing a packet to send.
        packet_delay_ms: Delay between sending packets in milliseconds.
    Returns:
        True if packets were sent successfully, False otherwise.

    Raises:
        BleCommunicationError: If connection or communication fails.
    """
    _LOGGER.info("Attempting to send %d packets via BLE to %s", len(packets), ble_device.address)

    try:
        # Use bleak-retry-connector to establish connection with retries
        client = await establish_connection(
            client_class=BleakClient, # Explicitly pass BleakClient
            device=ble_device,
            name=f"Ain't Ink Smart ({ble_device.address})",
            disconnected_callback=lambda client: _LOGGER.warning("Device %s disconnected", ble_device.address),
            # use_services_cache=True, # Consider enabling if performance is an issue
            ble_device_callback=lambda: ble_device, # Provide the device object
            max_attempts=3 # Number of connection attempts
        )

        packets_sent_successfully = False
        try:
            async with client:
                _LOGGER.info("Connected to %s", ble_device.address)

                # Find the characteristic
                img_char: BleakGATTCharacteristic | None = client.services.get_characteristic(IMG_CHAR_UUID)
                if img_char is None:
                    _LOGGER.error("Image characteristic %s not found on device %s", IMG_CHAR_UUID, ble_device.address)
                    raise BleCommunicationError(f"Characteristic {IMG_CHAR_UUID} not found")

                _LOGGER.debug("Found characteristic: %s", img_char.uuid)

                # Calculate delay in seconds
                delay_sec = packet_delay_ms / 1000.0

                # Send packets one by one with a delay
                for i, packet in enumerate(packets):
                    try:
                        # response=False as we don't expect a response for writes here
                        await client.write_gatt_char(img_char, packet, response=False)
                        _LOGGER.debug("Sent packet %d/%d (%d bytes) to %s", i + 1, len(packets), len(packet), ble_device.address)
                        # Add the configured delay between packets
                        if delay_sec > 0:
                            await asyncio.sleep(delay_sec)
                    except BleakError as e:
                        _LOGGER.error("BleakError sending packet %d to %s: %s", i + 1, ble_device.address, e)
                        raise BleCommunicationError(f"BLE write error: {e}") from e
                    except Exception as e:
                        _LOGGER.error("Unexpected error sending packet %d to %s: %s", i + 1, ble_device.address, e)
                        raise BleCommunicationError(f"Unexpected write error: {e}") from e

                _LOGGER.info("Successfully sent all %d packets to %s", len(packets), ble_device.address)
                packets_sent_successfully = True
                # Disconnect happens implicitly on exiting 'async with client'

        except EOFError:
            # If EOFError happens during disconnect AFTER sending packets, log warning but consider it success
            if packets_sent_successfully:
                _LOGGER.warning("EOFError during disconnect after successful packet send to %s. Assuming success.", ble_device.address)
                return True
            else:
                _LOGGER.error("EOFError during BLE operation with %s before all packets were sent.", ble_device.address)
                raise BleCommunicationError("EOFError during BLE communication") from EOFError
        # Re-raise other exceptions caught by the outer try/except
        except BleCommunicationError:
             raise # Re-raise our custom error
        except BleakError as e:
             _LOGGER.error("BleakError during BLE operation with %s: %s", ble_device.address, e)
             raise BleCommunicationError(f"BLE communication failed: {e}") from e
        except asyncio.TimeoutError:
             _LOGGER.error("Timeout during BLE operation with %s", ble_device.address)
             raise BleCommunicationError("BLE communication timed out") from asyncio.TimeoutError
        except Exception as e:
             _LOGGER.exception("Unexpected error during BLE operation with %s: %s", ble_device.address, e)
             raise BleCommunicationError(f"Unexpected BLE error: {e}") from e

        return packets_sent_successfully

    except BleakError as e:
        _LOGGER.error("BleakError during BLE operation with %s: %s", ble_device.address, e)
        raise BleCommunicationError(f"BLE communication failed: {e}") from e
    except asyncio.TimeoutError:
        _LOGGER.error("Timeout during BLE operation with %s", ble_device.address)
        raise BleCommunicationError("BLE communication timed out") from asyncio.TimeoutError
    except Exception as e:
        _LOGGER.exception("Unexpected error during BLE operation with %s: %s", ble_device.address, e)
        raise BleCommunicationError(f"Unexpected BLE error: {e}") from e

    # Return False if connection failed after retries (establish_connection returns None)
    # This path might not be reachable if establish_connection raises instead
    # return False
