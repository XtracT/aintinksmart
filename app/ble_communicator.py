"""
Handles Bluetooth Low Energy (BLE) communication with the E-Ink display
using the bleak library.
"""

import asyncio
import logging
from typing import List
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from . import config

# Constants
# Small delay between packets can improve reliability on some devices
PACKET_SEND_DELAY = 0.02 # seconds
# Time to wait after sending all packets for device processing/notifications
POST_SEND_WAIT_DELAY = 5.0 # seconds
# Connection timeout
CONNECTION_TIMEOUT = 30.0 # seconds


class BleCommunicationError(Exception):
    """Custom exception for BLE communication failures."""
    pass

class BleCommunicator:
    """Manages BLE connection, packet sending, and notifications."""

    def __init__(self, ble_address: str):
        """
        Initializes the communicator for a specific device address.

        Args:
            ble_address: The MAC address of the target BLE device.
        """
        if not ble_address:
            raise ValueError("BLE address cannot be empty.")
        self.address = ble_address
        self.client = BleakClient(self.address, timeout=CONNECTION_TIMEOUT)

    @staticmethod
    def _notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
        """Static method to handle incoming BLE notifications."""
        logging.info(f"Notification - Handle 0x{characteristic.handle:04X}: {data.hex()}")

    async def connect(self):
        """Establishes connection to the BLE device."""
        if self.client.is_connected:
            logging.warning(f"Already connected to {self.address}.")
            return

        logging.info(f"Attempting to connect to {self.address}...")
        try:
            await self.client.connect()
            if self.client.is_connected:
                logging.info(f"Connected successfully to {self.address}.")
                # Ensure services are discovered (good practice after connect)
                # Access services property to ensure discovery (replaces deprecated get_services())
                _ = self.client.services
                logging.debug("Services discovered (implicitly or explicitly).")
            else:
                 # Safety check in case connect() doesn't raise but fails
                 raise BleCommunicationError("Connection attempt finished but client is not connected.")

        except BleakError as e:
            logging.error(f"BleakError connecting to {self.address}: {e}")
            raise BleCommunicationError(f"Failed to connect: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error connecting to {self.address}: {e}")
            raise BleCommunicationError(f"Unexpected connection error: {e}") from e

    async def disconnect(self):
        """Disconnects from the BLE device."""
        if not self.client.is_connected:
            logging.warning(f"Not connected to {self.address}, cannot disconnect.")
            return

        logging.info(f"Disconnecting from {self.address}...")
        try:
            # Only attempt to stop notify if still connected
            if self.client.is_connected:
                try:
                    await self.client.stop_notify(config.NOTIFY_CHAR_UUID)
                    logging.debug("Stopped notifications.")
                except BleakError as e:
                    # Log non-critical failure (e.g., if notifications weren't started or already disconnected)
                    logging.warning(f"Could not stop notifications during disconnect: {e}")
                except Exception as e:
                     logging.warning(f"Unexpected error stopping notifications: {e}")
            else:
                logging.debug("Client already disconnected, skipping stop_notify.")


            await self.client.disconnect()
            logging.info(f"Disconnected from {self.address}.")
        except BleakError as e:
            logging.error(f"BleakError during disconnect: {e}")
            raise BleCommunicationError(f"Failed to disconnect cleanly: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error during disconnect: {e}")
            raise BleCommunicationError(f"Unexpected disconnect error: {e}") from e


    async def send_packets(self, packets: List[bytes]):
        """
        Sends the prepared data packets to the device's image characteristic.
        Assumes connection is already established.

        Args:
            packets: A list of byte arrays, each representing a packet.

        Raises:
            BleCommunicationError: If not connected or if sending fails.
        """
        if not self.client.is_connected:
            raise BleCommunicationError("Cannot send packets, not connected.")
        if not packets:
            logging.warning("No packets provided to send.")
            return

        logging.info(f"Starting notifications on {config.NOTIFY_CHAR_UUID}")
        try:
            await self.client.start_notify(config.NOTIFY_CHAR_UUID, self._notification_handler)
            logging.debug("Notifications started.")
        except BleakError as e:
            logging.error(f"Failed to start notifications: {e}")
            raise BleCommunicationError(f"Failed to start notifications: {e}") from e
        except Exception as e:
             logging.error(f"Unexpected error starting notifications: {e}")
             raise BleCommunicationError(f"Unexpected error starting notifications: {e}") from e


        logging.info(f"Sending {len(packets)} data packets...")
        total_packets = len(packets)
        for i, pkt in enumerate(packets):
            logging.debug(f"Sending packet {i+1}/{total_packets}, {len(pkt)} bytes...")
            try:
                await self.client.write_gatt_char(config.IMG_CHAR_UUID, pkt, response=False)
                if PACKET_SEND_DELAY > 0:
                    await asyncio.sleep(PACKET_SEND_DELAY)
            except BleakError as e:
                logging.error(f"BleakError sending packet {i+1}: {e}")
                raise BleCommunicationError(f"Error sending packet {i+1}: {e}") from e
            except Exception as e:
                 logging.error(f"Unexpected error sending packet {i+1}: {e}")
                 raise BleCommunicationError(f"Unexpected error sending packet {i+1}: {e}") from e


        logging.info("All packets sent.")
        if POST_SEND_WAIT_DELAY > 0:
            logging.info(f"Waiting {POST_SEND_WAIT_DELAY}s for potential device processing/notifications...")
            await asyncio.sleep(POST_SEND_WAIT_DELAY)
        logging.info("Image sending process complete.")

    # Context manager support for automatic connect/disconnect
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()