"""
Handles loading, processing, and converting images for the E-Ink display.
"""
import logging
import io
from typing import List, Dict, Any
from PIL import Image
from . import config # Use relative import within the app package

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
        # Original bitwise version: return ((n + multiple - 1) & (~(multiple - 1)))
        # Using //* is arguably more readable for non-power-of-2 multiples,
        # though PAD_MULTIPLE is 8 here.

    def process_image(self, image_bytes: bytes, mode: str = config.DEFAULT_COLOR_MODE) -> Dict[str, Any]:
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
        logging.info(f"Processing image with mode: {mode}")
        try:
            # Open image from bytes
            img_file = io.BytesIO(image_bytes)
            im = Image.open(img_file).convert("RGB")
        except Exception as e:
            logging.error(f"Error opening or converting image from bytes: {e}")
            raise ImageProcessingError(f"Could not open or convert image: {e}") from e

        width, height = im.size
        logging.info(f"Original image dimensions: {width}x{height}")

        padded_width = self._round_up(width, config.PAD_MULTIPLE)
        padded_height = self._round_up(height, config.PAD_MULTIPLE)
        logging.info(f"Padded dimensions for processing: {padded_width}x{padded_height}")

        padded_size = padded_width * padded_height
        black_bits = [0] * padded_size
        red_bits = [0] * padded_size

        threshold = config.IMAGE_PROCESSING_THRESHOLD

        # Process pixels into an intermediate 2D map based on color/luminance
        # Using a flat list might be slightly more efficient, but 2D is easier to visualize
        # Initialize pixel_map with padding assumption (default white = 1)
        pixel_map = [[1 for _ in range(padded_height)] for _ in range(padded_width)] # Default to white (1)

        for y in range(height):
            for x in range(width):
                try:
                    r, g, b = im.getpixel((x, y))
                    # Simple luminance calculation
                    lum = (r + g + b) // 3

                    if mode == "bw":
                        pixel_map[x][y] = 0 if lum < threshold else 1 # 0: Black, 1: White
                    else:  # bwr mode (default)
                        # Prioritize red detection (simple heuristic)
                        is_red = (r > 2 * g) and (r > 2 * b) and r > threshold
                        is_dark = lum < threshold

                        if is_red:
                            pixel_map[x][y] = 2  # Red
                        elif is_dark:
                            pixel_map[x][y] = 0  # Black
                        else:
                            pixel_map[x][y] = 1  # White
                except IndexError:
                    # Should not happen with Pillow's getpixel and correct loops
                    logging.warning(f"Pixel index out of bounds at ({x},{y}) - check logic.")
                    continue

        # Transform the 2D pixel map into linear black and red bitplanes
        # Iterate through the padded dimensions
        for y_pad in range(padded_height):
            for x_pad in range(padded_width):
                idx = (y_pad * padded_width) + x_pad
                if idx >= padded_size: # Safety check, should not be needed with correct loops
                    logging.warning(f"Calculated index {idx} exceeds padded size {padded_size}")
                    continue

                # Get value from pixel_map (defaults to 1=white if outside original bounds)
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
                # else: pixel_value remains 1 (White), bits already initialized to 0

        logging.info(f"Image processing complete. Bitplane size: {len(black_bits)}")
        return {
            "black_bits": black_bits,
            "red_bits": red_bits,
            "width": padded_width,
            "height": padded_height,
        }