"""
Builds the actual BLE data packets from the formatted hex payload,
applying protocol-specific CRC calculation and XOR encryption.
"""

import logging
import binascii
from typing import List, Union, Tuple
from . import config # Use relative import within the app package

class PacketBuilderError(Exception):
    """Custom exception for packet building failures."""
    pass

class PacketBuilder:
    """
    Constructs the sequence of encrypted and CRC-checked BLE packets
    ready for transmission.
    """

    @staticmethod
    def _calculate_crc16(data: Union[bytes, bytearray], length: int) -> int:
        """Calculates CRC16 using the device's specific nibble-based algorithm."""
        crc_val = 0xFFFF
        if length > len(data):
            raise PacketBuilderError(f"CRC calculation length ({length}) exceeds data length ({len(data)})")

        for i in range(length):
            byte_val = data[i] & 0xFF
            # Process two nibbles per byte
            for _ in range(2):
                # Ensure intermediate XOR result is byte-sized
                temp_val = ((crc_val >> 8) ^ byte_val) & 0xFF # Ensure intermediate XOR result is byte-sized
                lookup_idx = temp_val >> 4

                if lookup_idx >= len(config.CRC_TABLE):
                     raise PacketBuilderError(f"CRC lookup index {lookup_idx} out of bounds for CRC_TABLE.")

                crc_val = (config.CRC_TABLE[lookup_idx] ^ (crc_val << 4)) & 0xFFFF
                byte_val = (byte_val << 4) & 0xFF # Move to next nibble

        return crc_val & 0xFFFF

    def _calculate_xor_keys(self, ble_mac: str) -> Tuple[int, int]:
        """Calculates the XOR keys based on MAC address and secret string."""
        parts = ble_mac.upper().split(":")
        if len(parts) != 6:
            raise PacketBuilderError(f"Invalid MAC address format: {ble_mac}. Use XX:XX:XX:XX:XX:XX")
        try:
            mac_bytes = bytes(int(x, 16) for x in parts)
        except ValueError:
            raise PacketBuilderError(f"Invalid MAC address format: {ble_mac}. Contains non-hex characters.")

        mac_xor_key = 0
        for mb in mac_bytes:
            mac_xor_key ^= mb
        mac_xor_key &= 0xFF

        try:
            # Use specific index from protocol analysis
            secret_char_key = ord(config.SECRET_STR[config.HEADER_PROTOCOL_BYTE_VAL]) & 0xFF
        except IndexError:
            logging.error(f"SECRET_STR is too short! Needed index {config.HEADER_PROTOCOL_BYTE_VAL}")
            raise PacketBuilderError("Internal configuration error: SECRET_STR too short.")
        except TypeError:
             logging.error("SECRET_STR is not a string or HEADER_PROTOCOL_BYTE_VAL is invalid type.")
             raise PacketBuilderError("Internal configuration error: Invalid SECRET_STR or index.")


        return mac_xor_key, secret_char_key

    def _apply_xor(self, data: bytearray, mac_key: int, secret_key: int, is_header: bool = False) -> bytes:
        """Applies XOR encryption to the data packet."""
        encrypted_data = bytearray(len(data))
        for i in range(len(data)):
            # Skip XOR for the specific protocol byte in the header
            if is_header and i == config.HEADER_PROTOCOL_BYTE_INDEX:
                encrypted_data[i] = data[i]
                continue

            encrypted_byte = data[i] ^ mac_key
            encrypted_byte ^= secret_key
            encrypted_data[i] = encrypted_byte & 0xFF
        return bytes(encrypted_data)


    def build_packets(self, full_hex_payload: str, ble_mac: str) -> List[bytes]:
        """
        Constructs the sequence of BLE packets from the formatted hex payload.

        Args:
            full_hex_payload: The complete 'FC' or 'FE' formatted hex string.
            ble_mac: The target device's MAC address (e.g., "AA:BB:CC:DD:EE:FF").

        Returns:
            A list of byte arrays, each representing a single BLE packet to be sent.

        Raises:
            PacketBuilderError: If MAC format is invalid, payload is not hex,
                                or another building error occurs.
        """
        logging.info(f"Building BLE packets for MAC: {ble_mac}")
        try:
            payload_bytes = binascii.unhexlify(full_hex_payload)
        except binascii.Error as e:
            logging.error(f"Invalid hex payload string provided: {e}")
            raise PacketBuilderError("Payload string is not valid hex.") from e

        mac_xor_key, secret_char_key = self._calculate_xor_keys(ble_mac)
        logging.debug(f"Calculated XOR keys: MAC={mac_xor_key:02X}, Secret={secret_char_key:02X}")

        payload_len = len(payload_bytes)

        # Calculate number of data chunks needed
        # These constants define the chunking strategy
        data_per_chunk = config.DATA_CHUNK_PAYLOAD_LENGTH
        chunk_overhead = config.DATA_CHUNK_TOTAL_LENGTH - data_per_chunk # Index + CRC bytes
        # Use ceiling division to calculate chunks
        num_data_chunks = (payload_len + data_per_chunk - 1) // data_per_chunk
        if payload_len == 0: # Handle empty payload case
             num_data_chunks = 0

        logging.info(f"Payload length: {payload_len} bytes. Needs {num_data_chunks} data chunks.")

        packets: List[bytes] = []

        # --- Header Chunk ---
        header_chunk = bytearray(config.HEADER_LENGTH)
        header_chunk[0:2] = config.HEADER_PACKET_TYPE # FF FC
        header_chunk[2:9] = config.HEADER_TAG # "easyTag"
        header_chunk[config.HEADER_PROTOCOL_BYTE_INDEX] = config.HEADER_PROTOCOL_BYTE_VAL # 98 (at index 9)

        # Bytes 10-13: Total payload length (Big Endian)
        header_chunk[10:14] = payload_len.to_bytes(4, 'big')

        # Bytes 14-15: Number of data chunks (Big Endian)
        header_chunk[14:16] = num_data_chunks.to_bytes(2, 'big')

        # Bytes 16-17: 'B','T' identifier
        header_chunk[16:18] = config.HEADER_BT_ID

        # Bytes 18-19: CRC16 of first 18 bytes
        # CRC covers first 18 bytes
        crc_calc_len = config.HEADER_LENGTH - 2
        crc_val = self._calculate_crc16(header_chunk, crc_calc_len)
        header_chunk[18:20] = crc_val.to_bytes(2, 'big')

        # XOR the header chunk
        final_header = self._apply_xor(header_chunk, mac_xor_key, secret_char_key, is_header=True)
        packets.append(final_header)

        # --- Data Chunks ---
        for chunk_index in range(num_data_chunks):
            data_chunk = bytearray(config.DATA_CHUNK_TOTAL_LENGTH)

            # Bytes 0-1: Chunk index (1-based, Big Endian)
            protocol_chunk_index = chunk_index + 1
            data_chunk[0:2] = protocol_chunk_index.to_bytes(2, 'big')

            # Bytes 2-201: Payload data
            payload_start_idx = chunk_index * data_per_chunk
            payload_end_idx = payload_start_idx + data_per_chunk
            chunk_payload = payload_bytes[payload_start_idx:payload_end_idx]

            data_chunk[2 : 2 + len(chunk_payload)] = chunk_payload
            # Remaining bytes in data_chunk are implicitly 0

            # Bytes 202-203: CRC16
            crc_calc_len = config.DATA_CHUNK_TOTAL_LENGTH - 2
            crc_val = self._calculate_crc16(data_chunk, crc_calc_len)
            data_chunk[202:204] = crc_val.to_bytes(2, 'big')

            # XOR the entire data chunk
            final_data_chunk = self._apply_xor(data_chunk, mac_xor_key, secret_char_key, is_header=False)
            packets.append(final_data_chunk)

        logging.info(f"Generated {len(packets)} BLE packets ({len(packets)-1} data chunks).")
        return packets