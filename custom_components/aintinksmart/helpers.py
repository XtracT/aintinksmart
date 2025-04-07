"""Helper functions and classes for the Ain't Ink Smart integration."""
import logging
import io
import binascii # Added for hexlify
from typing import List, Dict, Any, Tuple, Union # Added Union
from PIL import Image

_LOGGER = logging.getLogger(__name__)

# --- Constants previously from config ---
# TODO: Consider making these configurable via Config Entry options if needed

# Image Processing
PAD_MULTIPLE: int = 8
IMAGE_PROCESSING_THRESHOLD: int = 128

# Packet Building / Protocol Constants
SECRET_STR = (
    "b8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97d60015bab2cdefb7ae0fcb099b599cc44"
    "d391645dde4b89b6e50f53dc046ec25acb8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97"
    "d60015bab2cdefb7ae0fcb099b599ac44d391645dde4b89b6e50f53dc046ec25ac"
)
CRC_TABLE = [0, 32773, 32783, 10, 32795, 30, 20, 32785, 32819, 54, 60, 32825, 40, 32813, 32807, 34]
HEADER_PACKET_TYPE = bytes([0xFF, 0xFC])
HEADER_TAG = b"easyTag"
HEADER_PROTOCOL_BYTE_VAL = 98
HEADER_PROTOCOL_BYTE_INDEX = 9 # Index of byte not XORed in header
HEADER_BT_ID = b"BT"
HEADER_LENGTH = 20
DATA_CHUNK_PAYLOAD_LENGTH = 200
DATA_CHUNK_TOTAL_LENGTH = 204 # Payload + Index + CRC

# --- Image Processor ---

class ImageProcessingError(Exception):
    """Custom exception for image processing failures."""
    pass

class ImageProcessor:
    """Loads and converts images into black and red bitplanes."""

    @staticmethod
    def _round_up(n: int, multiple: int) -> int:
        """Rounds up n to the nearest multiple."""
        if multiple == 0:
            return n
        return ((n + multiple - 1) // multiple) * multiple

    def process_image(self, image_bytes: bytes, mode: str) -> Dict[str, Any]:
        """
        Reads image bytes and converts them into black and red bitplanes.

        Args:
            image_bytes: The raw bytes of the image file (PNG, JPG, etc.).
            mode: Color mode ('bw' for black/white, 'bwr' for black/white/red).

        Returns:
            A dictionary containing:
            - 'black_bits': List where 1=black, 0=otherwise.
            - 'red_bits': List where 1=red, 0=otherwise (all 0s if mode='bw').
            - 'width': Padded width.
            - 'height': Padded height.

        Raises:
            ImageProcessingError: If the image cannot be opened or processed.
        """
        _LOGGER.info("Processing image with mode: %s", mode)
        if mode not in ['bw', 'bwr']:
             raise ImageProcessingError(f"Invalid mode specified: {mode}. Must be 'bw' or 'bwr'.")

        try:
            img_file = io.BytesIO(image_bytes)
            im = Image.open(img_file).convert("RGB")
        except Exception as e:
            _LOGGER.error("Error opening or converting image from bytes: %s", e)
            raise ImageProcessingError(f"Could not open or convert image: {e}") from e

        width, height = im.size
        _LOGGER.info("Original image dimensions: %dx%d", width, height)

        padded_width = self._round_up(width, PAD_MULTIPLE)
        padded_height = self._round_up(height, PAD_MULTIPLE)
        _LOGGER.info("Padded dimensions for processing: %dx%d", padded_width, padded_height)

        padded_size = padded_width * padded_height
        black_bits = [0] * padded_size
        red_bits = [0] * padded_size

        threshold = IMAGE_PROCESSING_THRESHOLD

        # Process pixels into an intermediate 2D map (easier to visualize padding)
        # Default to white (1) for padded areas
        pixel_map = [[1 for _ in range(padded_height)] for _ in range(padded_width)] # Default to white (1)

        for y in range(height):
            for x in range(width):
                try:
                    r, g, b = im.getpixel((x, y))
                    lum = (r + g + b) // 3

                    if mode == "bw":
                        pixel_map[x][y] = 0 if lum < threshold else 1
                    else:  # bwr mode
                        # Simple red detection heuristic
                        is_red = (r > 2 * g) and (r > 2 * b) and r > threshold
                        is_dark = lum < threshold

                        if is_red:
                            pixel_map[x][y] = 2
                        elif is_dark:
                            pixel_map[x][y] = 0
                        else:
                            pixel_map[x][y] = 1
                except IndexError:
                    # Should not happen with Pillow's getpixel
                    _LOGGER.warning("Pixel index out of bounds at (%d,%d) - check logic.", x, y)
                    continue

        # Transform the 2D pixel map into linear bitplanes (handling padding)
        for y_pad in range(padded_height):
            for x_pad in range(padded_width):
                idx = (y_pad * padded_width) + x_pad
                if idx >= padded_size: # Safety check
                    _LOGGER.warning("Calculated index %d exceeds padded size %d", idx, padded_size)
                    continue

                # Get value from pixel_map (handles padding implicitly via initialization)
                pixel_value = pixel_map[x_pad][y_pad]

                if pixel_value == 0:  # Black
                    black_bits[idx] = 1
                    red_bits[idx] = 0
                elif pixel_value == 1:  # White
                    black_bits[idx] = 0
                    red_bits[idx] = 0
                elif pixel_value == 2:  # Red
                    black_bits[idx] = 0
                    red_bits[idx] = 1
                # else: pixel_value is 1 (White), bits already 0

        _LOGGER.info("Image processing complete. Bitplane size: %d", len(black_bits))
        return {
            "black_bits": black_bits,
            "red_bits": red_bits,
            "width": padded_width,
            "height": padded_height,
        }

# --- Protocol Formatter ---

class ProtocolFormattingError(Exception):
    """Custom exception for protocol formatting failures."""
    pass

class ProtocolFormatter:
    """
    Formats image bitplanes into FC (RLE) or FE (packed) hex payloads.
    Chooses the shorter representation.
    """

    @staticmethod
    def _format_hex(n: int, digits: int) -> str:
        """Formats an integer as a hex string, zero-padded to the specified number of digits."""
        try:
            hex_str = format(n, 'X').upper()
            return '0' * (digits - len(hex_str)) + hex_str
        except (TypeError, ValueError):
            _LOGGER.error("Failed to format number %d as hex with %d digits.", n, digits)
            raise ProtocolFormattingError(f"Invalid input for hex formatting: n={n}, digits={digits}")

    @staticmethod
    def _pack_bits(bit_array: List[int]) -> bytes:
        """Packs a list of 0/1 bits into bytes (big-endian)."""
        out = bytearray()
        byte_count = (len(bit_array) + 7) // 8
        for i in range(byte_count):
            byte_val = 0
            for j in range(8):
                bit_index = i * 8 + j
                if bit_index < len(bit_array):
                    # Ensure bit is 0 or 1
                    bit = bit_array[bit_index] & 1
                    byte_val = (byte_val << 1) | bit
                else:
                    byte_val <<= 1 # Pad with 0 if bits run out
            out.append(byte_val)
        return bytes(out)

    @staticmethod
    def _run_length_encode(bit_array: List[int]) -> bytes:
        """
        Performs run-length encoding (RLE) on a bit array according to the
        specific device protocol rules.

        Args:
            bit_array: The input list of bits (0s and 1s).

        Returns:
            The RLE encoded byte values as bytes.
        """
        length = len(bit_array)
        if length == 0:
            return b''

        output_list = []
        i = 0
        while i < length:
            current_bit = bit_array[i]
            run_length = 0

            # Count consecutive identical bits
            while (i + run_length < length and
                   current_bit == bit_array[i + run_length] and
                   run_length < 65535):
                run_length += 1

            if run_length == 0: # Should not happen normally
                 i += 1
                 continue

            bit_val = 1 if current_bit else 0

            if run_length < 7:
                # Special encoding for short runs (up to 6 bits packed)
                bit_pattern = 0
                first_bit = 0
                num_bits_in_run = min(7, length - i)

                for j in range(num_bits_in_run):
                    current_run_bit = 1 if bit_array[i + j] else 0
                    if j == 0:
                        first_bit = current_run_bit
                    else:
                        bit_pattern |= current_run_bit << (6 - j)

                output_list.append(128 + (first_bit << 6) + bit_pattern)
                i += num_bits_in_run # Move past all bits processed in this short run
            else:
                # Encoding for longer runs
                if run_length <= 31:
                    output_list.append((bit_val << 6) + run_length)
                elif run_length <= 255:
                    output_list.append((bit_val << 6) + 1)
                    output_list.append(run_length & 0xFF)
                else: # run_length <= 65535
                    output_list.append((bit_val << 6) + 0)
                    output_list.append(run_length & 0xFF)
                    output_list.append((run_length >> 8) & 0xFF)

                i += run_length # Move past the entire run

        return bytes(output_list)


    def _build_fc_hex(self, black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
        """Builds the 'FC' formatted hex payload using Run-Length Encoding."""
        try:
            black_rle_bytes = self._run_length_encode(black_bits)
            black_hex = binascii.hexlify(black_rle_bytes).upper().decode()
            black_hex_len = len(black_hex) // 2

            y_start, x_start = 0, 0
            y_end, x_end = height - 1, width - 1

            sb = [
                "FC",
                self._format_hex(y_start, 4),
                self._format_hex(x_start, 4),
                self._format_hex(y_end, 4),
                self._format_hex(x_end, 4),
                self._format_hex(black_hex_len, 8),
                black_hex
            ]
            fc_out = "".join(sb)

            if any(bit == 1 for bit in red_bits):
                red_rle_bytes = self._run_length_encode(red_bits)
                red_hex = binascii.hexlify(red_rle_bytes).upper().decode()
                red_hex_len = len(red_hex) // 2

                sb2 = [
                    "FC8",
                    self._format_hex(y_start, 3), # y_start 3 digits
                    self._format_hex(x_start, 4), # x_start 4 digits
                    "8",                          # Separator/flag
                    self._format_hex(y_end, 3),   # y_end 3 digits
                    self._format_hex(x_end, 4),   # x_end 4 digits
                    self._format_hex(red_hex_len, 8),
                    red_hex
                ]
                fc_out += "".join(sb2)

            return fc_out
        except Exception as e:
            _LOGGER.error("Error building FC hex payload: %s", e)
            raise ProtocolFormattingError(f"Failed to build FC payload: {e}") from e

    def _build_fe_hex(self, black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
        """Builds the 'FE' formatted hex payload using direct bit packing."""
        try:
            black_bytes = self._pack_bits(black_bits)
            red_bytes = self._pack_bits(red_bits)

            black_hex = binascii.hexlify(black_bytes).upper().decode()
            red_hex = binascii.hexlify(red_bytes).upper().decode()

            y_start, x_start = 0, 0
            y_end, x_end = height - 1, width - 1

            fe = [
                "FE",
                self._format_hex(y_start, 4),
                self._format_hex(x_start, 4),
                self._format_hex(y_end, 4),
                self._format_hex(x_end, 4),
                black_hex
            ]
            fe_out = "".join(fe)

            if any(bit == 1 for bit in red_bits):
                more = [
                    "03",
                    self._format_hex(y_start, 4),
                    self._format_hex(x_start, 4),
                    self._format_hex(y_end, 4),
                    self._format_hex(x_end, 4),
                    red_hex
                ]
                fe_out += "".join(more)

            return fe_out
        except Exception as e:
            _LOGGER.error("Error building FE hex payload: %s", e)
            raise ProtocolFormattingError(f"Failed to build FE payload: {e}") from e

    def format_payload(self, image_data: Dict[str, Any]) -> str:
        """
        Generates both FC (RLE) and FE (packed) hex payloads from bitplanes
        and returns the shorter one.

        Args:
            image_data: A dictionary containing 'black_bits', 'red_bits',
                        'width', and 'height'.

        Returns:
            The shorter hex payload string ('FC...' or 'FE...').

        Raises:
            ProtocolFormattingError: If formatting fails.
        """
        black_bits = image_data['black_bits']
        red_bits = image_data['red_bits']
        width = image_data['width']
        height = image_data['height']

        _LOGGER.info("Generating FC (RLE) and FE (Packed) format payloads...")
        fc_out = self._build_fc_hex(black_bits, red_bits, width, height)
        fe_out = self._build_fe_hex(black_bits, red_bits, width, height)

        if len(fc_out) <= len(fe_out):
            _LOGGER.info("Choosing FC format (RLE) - Length: %d", len(fc_out))
            return fc_out
        else:
            _LOGGER.info("Choosing FE format (Packed) - Length: %d", len(fe_out))
            return fe_out

# --- Packet Builder ---

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
                temp_val = ((crc_val >> 8) ^ byte_val) & 0xFF
                lookup_idx = temp_val >> 4

                if lookup_idx >= len(CRC_TABLE):
                     raise PacketBuilderError(f"CRC lookup index {lookup_idx} out of bounds for CRC_TABLE.")

                crc_val = (CRC_TABLE[lookup_idx] ^ (crc_val << 4)) & 0xFFFF
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
            secret_char_key = ord(SECRET_STR[HEADER_PROTOCOL_BYTE_VAL]) & 0xFF
        except IndexError:
            _LOGGER.error("SECRET_STR is too short! Needed index %d", HEADER_PROTOCOL_BYTE_VAL)
            raise PacketBuilderError("Internal configuration error: SECRET_STR too short.")
        except TypeError:
             _LOGGER.error("SECRET_STR is not a string or HEADER_PROTOCOL_BYTE_VAL is invalid type.")
             raise PacketBuilderError("Internal configuration error: Invalid SECRET_STR or index.")


        return mac_xor_key, secret_char_key

    def _apply_xor(self, data: bytearray, mac_key: int, secret_key: int, is_header: bool = False) -> bytes:
        """Applies XOR encryption to the data packet."""
        encrypted_data = bytearray(len(data))
        for i in range(len(data)):
            # Skip XOR for the specific protocol byte in the header
            if is_header and i == HEADER_PROTOCOL_BYTE_INDEX:
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
        _LOGGER.info("Building BLE packets for MAC: %s", ble_mac)
        try:
            payload_bytes = binascii.unhexlify(full_hex_payload)
        except binascii.Error as e:
            _LOGGER.error("Invalid hex payload string provided: %s", e)
            raise PacketBuilderError("Payload string is not valid hex.") from e

        mac_xor_key, secret_char_key = self._calculate_xor_keys(ble_mac)
        _LOGGER.debug("Calculated XOR keys: MAC=%02X, Secret=%02X", mac_xor_key, secret_char_key)

        payload_len = len(payload_bytes)

        # Calculate number of data chunks needed
        data_per_chunk = DATA_CHUNK_PAYLOAD_LENGTH
        # Use ceiling division to calculate chunks
        num_data_chunks = (payload_len + data_per_chunk - 1) // data_per_chunk
        if payload_len == 0: # Handle empty payload case
             num_data_chunks = 0

        _LOGGER.info("Payload length: %d bytes. Needs %d data chunks.", payload_len, num_data_chunks)

        packets: List[bytes] = []

        header_chunk = bytearray(HEADER_LENGTH)
        header_chunk[0:2] = HEADER_PACKET_TYPE # FF FC
        header_chunk[2:9] = HEADER_TAG # "easyTag"
        header_chunk[HEADER_PROTOCOL_BYTE_INDEX] = HEADER_PROTOCOL_BYTE_VAL # 98 (at index 9)

        # Bytes 10-13: Total payload length (Big Endian)
        header_chunk[10:14] = payload_len.to_bytes(4, 'big')

        # Bytes 14-15: Number of data chunks (Big Endian)
        header_chunk[14:16] = num_data_chunks.to_bytes(2, 'big')

        # Bytes 16-17: 'B','T' identifier
        header_chunk[16:18] = HEADER_BT_ID

        # Bytes 18-19: CRC16 of first 18 bytes
        crc_calc_len = HEADER_LENGTH - 2
        crc_val = self._calculate_crc16(header_chunk, crc_calc_len)
        header_chunk[18:20] = crc_val.to_bytes(2, 'big')

        # XOR the header chunk
        final_header = self._apply_xor(header_chunk, mac_xor_key, secret_char_key, is_header=True)
        packets.append(final_header)

        for chunk_index in range(num_data_chunks):
            data_chunk = bytearray(DATA_CHUNK_TOTAL_LENGTH)

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
            crc_calc_len = DATA_CHUNK_TOTAL_LENGTH - 2
            crc_val = self._calculate_crc16(data_chunk, crc_calc_len)
            data_chunk[202:204] = crc_val.to_bytes(2, 'big')

            # XOR the entire data chunk
            final_data_chunk = self._apply_xor(data_chunk, mac_xor_key, secret_char_key, is_header=False)
            packets.append(final_data_chunk)

        _LOGGER.info("Generated %d BLE packets (%d data chunks).", len(packets), len(packets)-1 if packets else 0)
        return packets