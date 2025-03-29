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
from . import config # Use relative import within the app package

# Recommended MTU for many devices, adjust if needed based on testing
RECOMMENDED_MTU = 247
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
        self._is_connected = False # Internal state tracking

    @staticmethod
    def _notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
        """Static method to handle incoming BLE notifications."""
        # Keep this simple for now, just log the notification
        logging.info(f"Notification - Handle 0x{characteristic.handle:04X}: {data.hex()}")
        # In a more complex app, this could update state or trigger events.

    async def connect(self):
        """Establishes connection to the BLE device."""
        if self._is_connected:
            logging.warning(f"Already connected to {self.address}.")
            return
        if not self.client:
             self.client = BleakClient(self.address, timeout=CONNECTION_TIMEOUT)

        logging.info(f"Attempting to connect to {self.address}...")
        try:
            await self.client.connect()
            self._is_connected = self.client.is_connected
            if self._is_connected:
                logging.info(f"Connected successfully to {self.address}.")
                # Optional: Attempt MTU exchange
                await self._try_exchange_mtu()
                # Ensure services are discovered (good practice after connect)
                await self.client.get_services()
            else:
                 # Should not happen if connect() doesn't raise error, but safety check
                 raise BleCommunicationError("Connection attempt finished but client is not connected.")

        except BleakError as e:
            logging.error(f"BleakError connecting to {self.address}: {e}")
            self._is_connected = False
            raise BleCommunicationError(f"Failed to connect: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error connecting to {self.address}: {e}")
            self._is_connected = False
            raise BleCommunicationError(f"Unexpected connection error: {e}") from e

    async def disconnect(self):
        """Disconnects from the BLE device."""
        if not self.client or not self._is_connected:
            logging.warning(f"Not connected to {self.address}, cannot disconnect.")
            self._is_connected = False # Ensure state is correct
            return

        logging.info(f"Disconnecting from {self.address}...")
        try:
            # Attempt to stop notifications gracefully first
            try:
                await self.client.stop_notify(config.NOTIFY_CHAR_UUID)
                logging.debug("Stopped notifications.")
            except BleakError as e:
                # Log non-critical failure (e.g., if notifications weren't started)
                logging.warning(f"Could not stop notifications during disconnect: {e}")
            except Exception as e:
                 logging.warning(f"Unexpected error stopping notifications: {e}")


            await self.client.disconnect()
            logging.info(f"Disconnected from {self.address}.")
        except BleakError as e:
            logging.error(f"BleakError during disconnect: {e}")
            # Still raise, as disconnect failed
            raise BleCommunicationError(f"Failed to disconnect cleanly: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error during disconnect: {e}")
            raise BleCommunicationError(f"Unexpected disconnect error: {e}") from e
        finally:
             self._is_connected = False # Ensure state is updated even on error


    async def _try_exchange_mtu(self):
        """Attempts to negotiate a higher MTU for potentially faster transfers."""
        if not self._is_connected:
            logging.warning("Cannot exchange MTU, not connected.")
            return
        try:
            mtu = await self.client.exchange_mtu(RECOMMENDED_MTU)
            logging.info(f"Negotiated MTU: {mtu}")
        except BleakError as e:
            logging.warning(f"MTU exchange failed (using default): {e}")
        except Exception as e:
            logging.warning(f"Unexpected error during MTU exchange: {e}")


    async def send_packets(self, packets: List[bytes]):
        """
        Sends the prepared data packets to the device's image characteristic.
        Assumes connection is already established.

        Args:
            packets: A list of byte arrays, each representing a packet.

        Raises:
            BleCommunicationError: If not connected or if sending fails.
        """
        if not self._is_connected:
            raise BleCommunicationError("Cannot send packets, not connected.")
        if not packets:
            logging.warning("No packets provided to send.")
            return

        # Start notifications before sending data
        logging.info(f"Starting notifications on {config.NOTIFY_CHAR_UUID}")
        try:
            await self.client.start_notify(config.NOTIFY_CHAR_UUID, self._notification_handler)
            logging.debug("Notifications started.")
        except BleakError as e:
            logging.error(f"Failed to start notifications: {e}")
            # Decide whether to proceed without notifications or raise error
            raise BleCommunicationError(f"Failed to start notifications: {e}") from e
        except Exception as e:
             logging.error(f"Unexpected error starting notifications: {e}")
             raise BleCommunicationError(f"Unexpected error starting notifications: {e}") from e


        # Send packets
        logging.info(f"Sending {len(packets)} data packets...")
        total_packets = len(packets)
        for i, pkt in enumerate(packets):
            logging.debug(f"Sending packet {i+1}/{total_packets}, {len(pkt)} bytes...")
            try:
                await self.client.write_gatt_char(config.IMG_CHAR_UUID, pkt, response=False)
                # Small delay can improve reliability
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