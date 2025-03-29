# BLE E-Ink Image Sender (`send_bwr_ble.py`)

This Python script sends black/white or black/white/red images to certain types of Bluetooth Low Energy (BLE) e-ink displays.

## Description

The script implements a communication protocol based on reverse engineering of the original device communication. It takes an image file, processes it into the required format, and transmits it to the specified display via BLE.

## Disclaimer

This script is unofficial and based on reverse engineering efforts. It is provided "as is" without warranty of any kind. While it aims to replicate the necessary protocol steps, there might be subtle differences compared to the official application, particularly in how images are dithered or converted to the display's color format. Use at your own discretion. Ensure you comply with any relevant terms of service for your device.

## Requirements

*   Python 3.7+
*   `bleak` library (for BLE communication)
*   `Pillow` library (for image processing)
*   A compatible BLE adapter on your system (e.g., BlueZ on Linux, WinRT on Windows 10+, CoreBluetooth on macOS).

## Installation

Install the required libraries using pip:

```bash
pip install bleak Pillow
```

## Usage

Run the script from your terminal:

```bash
python send_bwr_ble.py --image <path_to_image> --mac <device_mac_address> [--mode <bw|bwr>] [--debug]
```

**Arguments:**

*   `--image`: (Required) Path to the input image file (e.g., `my_image.png`, `photo.jpg`).
*   `--mac`: (Required) The BLE MAC address of the target e-ink display (e.g., `AA:BB:CC:DD:EE:FF`).
*   `--mode`: (Optional) Color mode for image processing.
    *   `bwr` (default): Black, White, Red mode. Attempts to map colors to black, white, or red.
    *   `bw`: Black, White mode. Converts the image to monochrome.
*   `--debug`: (Optional) Enable verbose debug logging for troubleshooting.

**Example:**

```bash
python send_bwr_ble.py --image assets/label.png --mac E1:23:45:67:89:AB --mode bwr
```

## Compatibility

This script has been tested with the following device(s). Compatibility with other models is not guaranteed but may work if they use a similar protocol.

| Size  | Resolution | Colors | Part Number | Tested Status | Notes |
| :---- | :--------- | :----- | :---------- | :------------ | :---- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes           |       |
|       |            |        |               |       |

*Feel free to report success or failure with other models via issues or pull requests.*

## Troubleshooting

*   **Connection Issues:** Ensure the display is powered on and within range. Double-check the MAC address. Make sure your system's Bluetooth is enabled and working. On Linux, ensure the `bluetooth` service is running.
*   **Errors During Sending:** Use the `--debug` flag to get more detailed logs, which might indicate specific problems during packet generation or transmission.
*   **Image Appearance:** The script uses basic thresholding for color conversion. Results may vary compared to the official app, especially for images with gradients or many colors. Pre-processing images to be purely black/white/red might yield better results for `bwr` mode.

## Contributing

(Optional: Add guidelines if you accept contributions)

## License

(Optional: Add license information, e.g., MIT License)