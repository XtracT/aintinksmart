# Ain't Ink Smart E-Ink Display Project

This repository contains the Home Assistant custom integration and optional ESP32 firmware for controlling certain Bluetooth Low Energy (BLE) e-ink displays.

The project provides two primary ways to interact with the displays:

1.  **Home Assistant Integration:** A custom component for Home Assistant that allows seamless control and display updates from your smart home environment. This is the recommended method for most users.
2.  **ESP32 MQTT Gateway Firmware:** Custom firmware for ESP32 devices that acts as a BLE-to-MQTT bridge, enabling control via MQTT messages. This is used by the Home Assistant integration in MQTT Gateway mode, or can be used independently.

Additionally, the repository includes a Python headless service and standalone CLI scripts for direct interaction or alternative use cases.

## Home Assistant Integration

The Home Assistant integration allows you to easily integrate compatible e-ink displays into your Home Assistant setup. It supports sending images via either direct BLE or an MQTT gateway (using the ESP32 firmware).

For detailed information on the purpose, structure, configuration, entities, services, and how the integration works, please refer to the [Home Assistant Integration Documentation](doc/home_assistant_integration.md).

### Installation (Recommended Method: HACS)

The easiest way to install the Home Assistant integration is via HACS (Home Assistant Community Store) as a custom repository.

1.  **Ensure HACS is installed** in your Home Assistant instance.
2.  **Add Custom Repository:**
    *   In Home Assistant, navigate to HACS.
    *   Go to the "Integrations" section.
    *   Click the three dots in the top right corner and select "Custom repositories".
    *   Enter the URL of this GitHub repository (`<YOUR_REPOSITORY_URL>`) in the "Repository" field.
    *   Select "Integration" as the "Category".
    *   Click the "Add" button.
3.  **Install Integration:**
    *   Close the custom repositories dialog.
    *   Search for "Ain't Ink Smart E-Ink Display" in the HACS > Integrations section.
    *   Click on the integration and then click the "Download" or "Install" button.
4.  **Restart Home Assistant:** After the download is complete, restart your Home Assistant instance to load the new integration.

### Installation (Manual Method)

Alternatively, you can install the integration manually:

1.  **Copy Files:** Copy the `custom_components/aintinksmart` directory from this repository into your Home Assistant `config/custom_components/` directory.
2.  **Restart Home Assistant:** Restart your Home Assistant instance.

## ESP32 Firmware (MQTT Gateway)

The custom ESP32 firmware acts as an MQTT-controlled BLE gateway for the e-ink displays. It is required if you plan to use the Home Assistant integration or the Python service in MQTT Gateway mode.

For a detailed overview of the system architecture, including the role of the ESP32 gateway, please refer to the [System Architecture Document](doc/ARCHITECTURE.md). For details on the MQTT topics used for communication with the gateway, see [MQTT Topics](doc/mqtt_topics.md).

### Building and Flashing (Using PlatformIO)

The ESP32 firmware is developed using the PlatformIO ecosystem.

1.  **Install PlatformIO:** If you don't have it already, install the PlatformIO extension for VS Code or the PlatformIO Core CLI.
2.  **Open Project:** Open the `src/` directory as a PlatformIO project in VS Code.
3.  **Configure:** Edit `src/config.h` to configure your WiFi credentials, MQTT broker details, and other settings.
4.  **Build:** Build the project using the PlatformIO build task (usually `PlatformIO: Build` in VS Code or `pio run` from the terminal in the `src/` directory).
5.  **Upload:** Connect your ESP32 board and upload the firmware using the PlatformIO upload task (usually `PlatformIO: Upload` in VS Code or `pio run --target upload` from the terminal).

## Python Headless Service (`app/`)

This repository also includes a Python headless service designed to run in a Docker container. It can operate in Direct BLE mode or utilize the ESP32 MQTT Gateway. This service is an alternative method for sending images via MQTT without using Home Assistant.

For detailed information on the service's purpose, configuration, and usage, please refer to the [System Architecture Document](doc/ARCHITECTURE.md) and the [MQTT Topics Document](doc/mqtt_topics.md).

## CLI Scripts (`scripts/`)

A set of Python CLI scripts are provided in the `scripts/` directory for direct interaction with the service via MQTT or as reference examples of the BLE communication protocol.

*   `scripts/send_image_cli.py`: Send an image to a display via the MQTT service.
*   `scripts/scan_ble_cli.py`: Trigger a BLE scan via the MQTT service and display results.
*   `scripts/send_bwr_ble.py`: A standalone script demonstrating the core direct BLE communication logic (proof-of-concept).

These scripts require Python 3.10+ and the libraries listed in `requirements.txt`. You can find the scripts in the [`scripts/` directory](scripts/).

## Compatibility

| Size  | Resolution | Colors | Part Number | Tested Status | Notes |
| :---- | :--------- | :----- | :---------- | :------------ | :---- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes           |       |

## Troubleshooting

Refer to the specific documentation for the Home Assistant integration ([doc/home_assistant_integration.md](doc/home_assistant_integration.md)), the ESP32 firmware, or the Python service ([doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)) for troubleshooting steps related to each component.

## Contributing

## License