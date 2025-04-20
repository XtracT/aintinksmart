#!/usr/bin/env python3
import argparse
import asyncio
import binascii
import logging
from typing import List, Tuple, Union
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from PIL import Image

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

##########################################
# BLE Characteristic UUIDs
##########################################
IMG_CHAR_UUID = "00001525-1212-efde-1523-785feabcd123"
NOTIFY_CHAR_UUID = "00001526-1212-efde-1523-785feabcd123"

##########################################
# XOR Secret String (Required by device protocol)
##########################################
SECRET_STR = (
    "b8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97d60015bab2cdefb7ae0fcb099b599cc44"
    "d391645dde4b89b6e50f53dc046ec25acb8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97"
    "d60015bab2cdefb7ae0fcb099b599ac44d391645dde4b89b6e50f53dc046ec25ac"
)

##########################################
# CRC16 Calculation Table (Required by device protocol)
##########################################
CRC_TABLE = [0, 32773, 32783, 10, 32795, 30, 20, 32785, 32819, 54, 60, 32825, 40, 32813, 32807, 34]

##########################################
# Image Processing Functions
##########################################

def round_up(n: int, multiple: int) -> int:
    """Rounds up n to the nearest multiple."""
    return ((n + multiple - 1) & (~(multiple - 1)))

def convert_image_to_bitplanes(image_path: str, mode: str = "bwr") -> Tuple[List[int], List[int], int, int]:
    """
    Reads an image file and converts it into black and red bitplanes.

    Args:
        image_path: Path to the image file (PNG, JPG, etc.).
        mode: Color mode ('bw' for black/white, 'bwr' for black/white/red).

    Returns:
        A tuple containing:
        - black_bits: List where 1=black, 0=otherwise.
        - red_bits: List where 1=red, 0=otherwise (all 0s if mode='bw').
        - padded_width: Width rounded up to the nearest 8.
        - padded_height: Height rounded up to the nearest 8.
    """
    try:
        im = Image.open(image_path).convert("RGB")
    except FileNotFoundError:
        logging.error(f"Image file not found: {image_path}")
        raise
    except Exception as e:
        logging.error(f"Error opening or converting image: {e}")
        raise

    width, height = im.size
    logging.info(f"Original image dimensions: {width}x{height}")

    padded_width = round_up(width, 8)
    padded_height = round_up(height, 8)
    logging.info(f"Padded dimensions for processing: {padded_width}x{padded_height}")

    padded_size = padded_width * padded_height
    black_bits = [0] * padded_size
    red_bits = [0] * padded_size

    threshold = 128

    # Process pixels into an intermediate 2D map based on color/luminance
    pixel_map = [[1 for _ in range(padded_height)] for _ in range(padded_width)] # Default to white (1)

    for y in range(height):
        for x in range(width):
            try:
                r, g, b = im.getpixel((x, y))
                lum = (r + g + b) // 3

                if mode == "bw":
                    if lum < threshold:
                        pixel_map[x][y] = 0  # Black
                    else:
                        pixel_map[x][y] = 1  # White
                else:  # bwr mode
                    # Prioritize red detection
                    if (r > 2 * g) and (r > 2 * b) and r > threshold: # Check threshold for red too
                        pixel_map[x][y] = 2  # Red
                    elif lum < threshold:
                        pixel_map[x][y] = 0  # Black
                    else:
                        pixel_map[x][y] = 1  # White
            except IndexError:
                 logging.warning(f"Pixel index out of bounds at ({x},{y}) - should not happen with Pillow.")
                 continue # Should not happen with Pillow's getpixel

    # Transform the 2D pixel map into linear black and red bitplanes
    for x in range(padded_width):
        for y in range(padded_height):
            idx = (y * padded_width) + x
            if idx >= padded_size: # Safety check
                logging.warning(f"Calculated index {idx} exceeds padded size {padded_size}")
                continue

            pixel_value = pixel_map[x][y]

            if pixel_value == 0:  # Black
                black_bits[idx] = 1
                red_bits[idx] = 0
            elif pixel_value == 1:  # White
                black_bits[idx] = 0
                red_bits[idx] = 0
            elif pixel_value == 2:  # Red
                black_bits[idx] = 0
                red_bits[idx] = 1
            # else: pixel_value remains 1 (White), bits already initialized to 0

    return black_bits, red_bits, padded_width, padded_height

##########################################
# Payload Formatting Functions
##########################################

def run_length_encode(bit_array: List[int], length: int) -> Tuple[List[int], int]:
    """
    Performs run-length encoding (RLE) on a bit array.

    Args:
        bit_array: The input list of bits (0s and 1s).
        length: The number of bits in the array to process.

    Returns:
        A tuple containing:
        - output: The RLE encoded byte values as a list of integers.
        - out_idx: The number of bytes in the encoded output.
    """
    if length == 0:
        return [], 0
    output = [0] * length  # Pre-allocate generously (worst case is slightly larger)
    i = 0
    out_idx = 0

    while i < length:
        current_bit = bit_array[i]
        run_length = 0

        # Count consecutive identical bits
        while (i + run_length < length and
               current_bit == bit_array[i + run_length] and
               run_length < 65535):
            run_length += 1

        if run_length == 0: # Should not happen in this loop structure, but safety first
             i += 1
             continue

        if run_length < 7:
            # Special encoding for short runs (up to 6 bits packed)
            bit_pattern = 0
            first_bit = 0
            num_bits_in_run = min(7, length - i)

            for j in range(num_bits_in_run):
                bit_val = 1 if bit_array[i + j] else 0
                if j == 0:
                    first_bit = bit_val
                else:
                    bit_pattern |= bit_val << (6 - j)

            output[out_idx] = 128 + (first_bit << 6) + bit_pattern
            out_idx += 1
            i += num_bits_in_run # Move past all bits processed in this short run
        else:
            # Encoding for longer runs
            bit_val = 1 if current_bit else 0

            if run_length <= 31:
                # 5-bit length encoding (0-31)
                output[out_idx] = (bit_val << 6) + run_length
                out_idx += 1
            elif run_length <= 255:
                # 8-bit length encoding (32-255)
                output[out_idx] = (bit_val << 6) + 1
                out_idx += 1
                output[out_idx] = run_length & 0xFF
                out_idx += 1
            else: # run_length <= 65535
                # 16-bit length encoding (256-65535)
                output[out_idx] = (bit_val << 6) + 0
                out_idx += 1
                output[out_idx] = run_length & 0xFF
                out_idx += 1
                output[out_idx] = (run_length >> 8) & 0xFF
                out_idx += 1

            i += run_length # Move past the entire run

    return output[:out_idx], out_idx


def format_hex(n: int, digits: int) -> str:
    """Formats an integer as a hex string, zero-padded to the specified number of digits."""
    hex_str = format(n, 'X').upper()
    return '0' * (digits - len(hex_str)) + hex_str


def pack_bits(bit_array: List[int]) -> bytes:
    """Packs a list of 0/1 bits into bytes (big-endian)."""
    out = bytearray()
    byte_count = (len(bit_array) + 7) // 8
    for i in range(byte_count):
        byte_val = 0
        for j in range(8):
            bit_index = i * 8 + j
            if bit_index < len(bit_array):
                byte_val = (byte_val << 1) | (bit_array[bit_index] & 1)
            else:
                byte_val <<= 1 # Pad with 0 if bits run out
        out.append(byte_val)
    return bytes(out)


def build_fc_hex(black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
    """
    Builds the 'FC' formatted hex payload using Run-Length Encoding.
    Includes 'FC8' section for red bits if present.
    """
    # RLE encode black bits
    black_encoded, black_len = run_length_encode(black_bits, len(black_bits))
    black_bytes = bytes(black_encoded[:black_len])
    black_hex = binascii.hexlify(black_bytes).upper().decode()
    black_hex_len = len(black_hex) // 2

    # Coordinates
    y_start, x_start = 0, 0
    y_end, x_end = height - 1, width - 1

    # Build the base FC string (black plane)
    sb = [
        "FC",
        format_hex(y_start, 4),
        format_hex(x_start, 4),
        format_hex(y_end, 4),
        format_hex(x_end, 4),
        format_hex(black_hex_len, 8),
        black_hex
    ]
    fc_out = "".join(sb)

    # If there are any red bits, add the FC8 section
    if any(red_bits):
        red_encoded, red_len = run_length_encode(red_bits, len(red_bits))
        red_bytes = bytes(red_encoded[:red_len])
        red_hex = binascii.hexlify(red_bytes).upper().decode()
        red_hex_len = len(red_hex) // 2

        # Build the FC8 string (red plane)
        sb2 = [
            "FC8",
            format_hex(0, 3),    # y_start 3 digits
            format_hex(0, 4),    # x_start 4 digits
            "8",                 # Separator/flag
            format_hex(y_end, 3), # y_end 3 digits
            format_hex(x_end, 4), # x_end 4 digits
            format_hex(red_hex_len, 8),
            red_hex
        ]
        fc_out += "".join(sb2)

    return fc_out


def build_fe_hex(black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
    """
    Builds the 'FE' formatted hex payload using direct bit packing (no RLE).
    Includes '03' section for red bits if present.
    """
    # Pack bits directly into bytes
    black_bytes = pack_bits(black_bits)
    red_bytes = pack_bits(red_bits)

    black_hex = binascii.hexlify(black_bytes).upper().decode()
    red_hex = binascii.hexlify(red_bytes).upper().decode()

    # Coordinates
    y_start, x_start = 0, 0
    y_end, x_end = height - 1, width - 1

    # Build the base FE string (black plane)
    fe = [
        "FE",
        format_hex(y_start, 4),
        format_hex(x_start, 4),
        format_hex(y_end, 4),
        format_hex(x_end, 4),
        black_hex
    ]
    fe_out = "".join(fe)

    # If there's any red bit, append the "03" section (red plane)
    if any(red_bits):
        more = [
            "03",
            format_hex(y_start, 4),
            format_hex(x_start, 4),
            format_hex(y_end, 4),
            format_hex(x_end, 4),
            red_hex
        ]
        fe_out += "".join(more)

    return fe_out


def build_best_hex(black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
    """
    Generates both FC (RLE) and FE (packed) hex payloads and returns the shorter one.
    """
    fc_out = build_fc_hex(black_bits, red_bits, width, height)
    fe_out = build_fe_hex(black_bits, red_bits, width, height)

    # Pick whichever format resulted in a smaller hex string
    if len(fc_out) <= len(fe_out):
        logging.info(f"Choosing FC format (RLE) - Length: {len(fc_out)}")
        return fc_out
    else:
        logging.info(f"Choosing FE format (Packed) - Length: {len(fe_out)}")
        return fe_out

##########################################
# BLE Packet Construction Functions
##########################################

def calc_crc16_nibbles(data: Union[bytes, bytearray], length: int) -> int:
    """Calculates CRC16 using the device's specific nibble-based algorithm."""
    crc_val = 0xFFFF
    for i in range(length):
        byte_val = data[i] & 0xFF
        for _ in range(2): # Process two nibbles per byte
            lookup_idx = ((crc_val >> 8) ^ byte_val) >> 4
            crc_val = CRC_TABLE[lookup_idx & 0xF] ^ (crc_val << 4)
            byte_val = (byte_val << 4) & 0xFF # Move to next nibble
    return crc_val & 0xFFFF


def build_ble_packets(full_hex_payload: str, ble_mac: str) -> List[bytes]:
    """
    Constructs the sequence of BLE packets from the formatted hex payload.

    Includes header packet and data packets, applying CRC and XOR encryption.

    Args:
        full_hex_payload: The complete 'FC' or 'FE' formatted hex string.
        ble_mac: The target device's MAC address (e.g., "AA:BB:CC:DD:EE:FF").

    Returns:
        A list of byte arrays, each representing a single BLE packet to be sent.

    Raises:
        ValueError: If the MAC address format is invalid or payload is not hex.
    """
    try:
        payload_bytes = binascii.unhexlify(full_hex_payload)
    except binascii.Error as e:
        logging.error(f"Invalid hex payload string: {e}")
        raise ValueError("Payload string is not valid hex.") from e

    # Calculate XOR keys
    parts = ble_mac.split(":")
    if len(parts) != 6:
        raise ValueError("Invalid MAC address format. Use XX:XX:XX:XX:XX:XX")
    try:
        mac_bytes = bytes(int(x, 16) for x in parts)
    except ValueError:
        raise ValueError("Invalid MAC address format. Contains non-hex characters.")

    mac_xor_key = 0
    for mb in mac_bytes:
        mac_xor_key ^= mb
    mac_xor_key &= 0xFF

    try:
        secret_char_key = ord(SECRET_STR[98]) & 0xFF
    except IndexError:
        logging.error("SECRET_STR is too short!")
        raise ValueError("Internal configuration error: SECRET_STR too short.")

    # Calculate number of data chunks needed (protocol specific calculation)
    # Constants 204 and 200 are derived from the original protocol analysis
    payload_len = len(payload_bytes)
    length_calc = (payload_len + 204) - 3
    num_data_chunks = length_calc // 200 # Total chunks including header = num_data_chunks + 1

    packets: List[bytes] = []

    # --- Create Header Chunk (20 bytes) ---
    header_chunk = bytearray(20)
    header_chunk[0] = 0xFF # Packet type identifier
    header_chunk[1] = 0xFC # Packet type identifier

    # Bytes 2-8: "easyTag" identifier
    easy_tag = b"easyTag"
    header_chunk[2:9] = easy_tag

    # Byte 9: Protocol specific constant
    header_chunk[9] = 98

    # Bytes 10-13: Total payload length (Big Endian)
    header_chunk[10] = (payload_len >> 24) & 0xFF
    header_chunk[11] = (payload_len >> 16) & 0xFF
    header_chunk[12] = (payload_len >> 8) & 0xFF
    header_chunk[13] = payload_len & 0xFF

    # Bytes 14-15: Number of data chunks (Big Endian)
    header_chunk[14] = (num_data_chunks >> 8) & 0xFF
    header_chunk[15] = num_data_chunks & 0xFF

    # Bytes 16-17: 'B','T' identifier
    header_chunk[16] = ord('B')
    header_chunk[17] = ord('T')

    # Bytes 18-19: CRC16 of first 18 bytes
    crc_val = calc_crc16_nibbles(header_chunk, 18)
    header_chunk[18] = (crc_val >> 8) & 0xFF
    header_chunk[19] = crc_val & 0xFF

    # XOR the header chunk (except byte 9)
    final_header = bytearray(header_chunk)
    for i in range(20):
        if i == 9:
            continue
        final_header[i] ^= mac_xor_key
        final_header[i] ^= secret_char_key
    packets.append(bytes(final_header))

    # --- Create Data Chunks (204 bytes each) ---
    for chunk_index in range(1, num_data_chunks + 1):
        data_chunk = bytearray(204)

        # Bytes 0-1: Chunk index (1-based, Big Endian)
        data_chunk[0] = (chunk_index >> 8) & 0xFF
        data_chunk[1] = chunk_index & 0xFF

        # Bytes 2-201: Payload data (200 bytes per chunk)
        payload_start_idx = (chunk_index - 1) * 200
        payload_end_idx = payload_start_idx + 200
        chunk_payload = payload_bytes[payload_start_idx:payload_end_idx]

        data_chunk[2 : 2 + len(chunk_payload)] = chunk_payload
        # Remaining bytes (if payload is shorter) are implicitly 0 due to bytearray initialization

        # Bytes 202-203: CRC16 of first 202 bytes
        crc_val = calc_crc16_nibbles(data_chunk, 202)
        data_chunk[202] = (crc_val >> 8) & 0xFF
        data_chunk[203] = crc_val & 0xFF

        # XOR the entire data chunk
        final_data_chunk = bytearray(data_chunk)
        for i in range(204):
            final_data_chunk[i] ^= mac_xor_key
            final_data_chunk[i] ^= secret_char_key
        packets.append(bytes(final_data_chunk))

    logging.info(f"Generated {len(packets)} BLE packets for transmission.")
    return packets

##########################################
# BLE Communication Functions
##########################################

def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
    """Handles incoming BLE notifications."""
    logging.info(f"Notification - Handle 0x{characteristic.handle:04X}: {data.hex()}")

async def send_image(ble_address: str, image_path: str, mode: str):
    """
    Connects to the BLE device, processes the image, sends the data packets,
    and handles notifications.
    """
    logging.info(f"Processing image: {image_path} (Mode: {mode})")
    try:
        black_bits, red_bits, w, h = convert_image_to_bitplanes(image_path, mode)
        hex_payload = build_best_hex(black_bits, red_bits, w, h)
        packets = build_ble_packets(hex_payload, ble_address)
    except Exception as e:
        logging.error(f"Failed to process image or build packets: {e}")
        return # Stop execution if preparation fails

    if not packets:
        logging.error("No packets generated, cannot send.")
        return

    logging.info(f"Attempting to connect to {ble_address}...")
    client = BleakClient(ble_address, timeout=30.0)

    try:
        await client.connect()
        logging.info("Connected successfully.")

        # Optional: Attempt MTU exchange for potentially faster transfers
        try:
            # Recommended MTU for many devices, adjust if needed
            mtu = await client.exchange_mtu(247)
            logging.info(f"Negotiated MTU: {mtu}")
        except Exception as e:
            logging.warning(f"MTU exchange failed (using default): {e}")

        # Ensure services are discovered
        await client.get_services()

        # Start notifications
        logging.info(f"Starting notifications on {NOTIFY_CHAR_UUID}")
        try:
            await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        except Exception as e:
            logging.error(f"Failed to start notifications: {e}")
            # Decide if you want to proceed without notifications
            # return

        # Send packets
        logging.info(f"Sending {len(packets)} data chunks...")
        for i, pkt in enumerate(packets):
            logging.debug(f"Sending chunk {i+1}/{len(packets)}, {len(pkt)} bytes...")
            try:
                await client.write_gatt_char(IMG_CHAR_UUID, pkt, response=False)
                # Small delay between packets can improve reliability on some devices
                await asyncio.sleep(0.02)
            except Exception as e:
                logging.error(f"Error sending chunk {i+1}: {e}")
                # Consider adding retry logic or stopping here
                break # Stop sending if one chunk fails

        logging.info("All chunks sent. Waiting 5 seconds for potential device processing/notifications...")
        await asyncio.sleep(5.0)
        logging.info("Image sending process complete.")

    except Exception as e:
        logging.error(f"An error occurred during BLE communication: {e}")
    finally:
        if client.is_connected:
            logging.info("Disconnecting...")
            try:
                await client.stop_notify(NOTIFY_CHAR_UUID)
            except Exception:
                logging.warning("Failed to stop notifications during disconnect.") # Non-critical
            await client.disconnect()
            logging.info("Disconnected.")
        else:
            logging.info("Client was not connected.")

##########################################
# Main Execution Block
##########################################
def main():
    parser = argparse.ArgumentParser(
        description="Sends an image to a compatible BLE e-ink display.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--image", required=True, help="Path to the input image file (PNG, JPG, etc.)")
    parser.add_argument("--mac", required=True, help="BLE MAC address of the target display (e.g., AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--mode", choices=["bw", "bwr"], default="bwr", help="Color mode: 'bw' (black/white) or 'bwr' (black/white/red)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(send_image(args.mac, args.image, args.mode))
    except KeyboardInterrupt:
        logging.info("Process interrupted by user.")
    except Exception as e:
        logging.critical(f"An unhandled error occurred: {e}")

if __name__ == "__main__":
    main()
