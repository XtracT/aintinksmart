"""
Handles formatting the image bitplanes into the specific hex payload
strings (FC or FE format) required by the E-Ink display protocol.
"""
import logging
import binascii
from typing import List, Tuple, Dict, Any

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
            logging.error(f"Failed to format number {n} as hex with {digits} digits.")
            # Re-raise or return a default? Re-raising seems safer.
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
                # This part seems overly complex and might be specific to reverse engineering.
                # Double-check if this is standard RLE or a device quirk.
                # Assuming the original logic is correct for the target device:
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
                    # 5-bit length encoding (0-31)
                    output_list.append((bit_val << 6) + run_length)
                elif run_length <= 255:
                    # 8-bit length encoding (32-255)
                    output_list.append((bit_val << 6) + 1)
                    output_list.append(run_length & 0xFF)
                else: # run_length <= 65535
                    # 16-bit length encoding (256-65535)
                    output_list.append((bit_val << 6) + 0)
                    output_list.append(run_length & 0xFF)
                    output_list.append((run_length >> 8) & 0xFF)

                i += run_length # Move past the entire run

        return bytes(output_list)


    def _build_fc_hex(self, black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
        """Builds the 'FC' formatted hex payload using Run-Length Encoding."""
        try:
            # RLE encode black bits
            black_rle_bytes = self._run_length_encode(black_bits)
            black_hex = binascii.hexlify(black_rle_bytes).upper().decode()
            black_hex_len = len(black_hex) // 2

            # Coordinates
            y_start, x_start = 0, 0
            y_end, x_end = height - 1, width - 1

            # Build the base FC string (black plane)
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

            # If there are any red bits, add the FC8 section
            if any(bit == 1 for bit in red_bits): # More explicit check
                red_rle_bytes = self._run_length_encode(red_bits)
                red_hex = binascii.hexlify(red_rle_bytes).upper().decode()
                red_hex_len = len(red_hex) // 2

                # Build the FC8 string (red plane) - Note the different coordinate formatting
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
            logging.error(f"Error building FC hex payload: {e}")
            raise ProtocolFormattingError(f"Failed to build FC payload: {e}") from e

    def _build_fe_hex(self, black_bits: List[int], red_bits: List[int], width: int, height: int) -> str:
        """Builds the 'FE' formatted hex payload using direct bit packing."""
        try:
            # Pack bits directly into bytes
            black_bytes = self._pack_bits(black_bits)
            red_bytes = self._pack_bits(red_bits)

            black_hex = binascii.hexlify(black_bytes).upper().decode()
            red_hex = binascii.hexlify(red_bytes).upper().decode()

            # Coordinates
            y_start, x_start = 0, 0
            y_end, x_end = height - 1, width - 1

            # Build the base FE string (black plane)
            fe = [
                "FE",
                self._format_hex(y_start, 4),
                self._format_hex(x_start, 4),
                self._format_hex(y_end, 4),
                self._format_hex(x_end, 4),
                black_hex
            ]
            fe_out = "".join(fe)

            # If there's any red bit, append the "03" section (red plane)
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
            logging.error(f"Error building FE hex payload: {e}")
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

        logging.info("Generating FC (RLE) and FE (Packed) format payloads...")
        fc_out = self._build_fc_hex(black_bits, red_bits, width, height)
        fe_out = self._build_fe_hex(black_bits, red_bits, width, height)

        # Pick whichever format resulted in a smaller hex string
        if len(fc_out) <= len(fe_out):
            logging.info(f"Choosing FC format (RLE) - Length: {len(fc_out)}")
            return fc_out
        else:
            logging.info(f"Choosing FE format (Packed) - Length: {len(fe_out)}")
            return fe_out