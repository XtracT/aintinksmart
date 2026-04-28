# Ain't Ink Smart Home Assistant Integration

This document explains the structure, purpose, and usage of the Ain't Ink Smart custom component for Home Assistant.

## Intended Purpose

The Ain't Ink Smart integration allows users to control and display images on compatible e-ink displays from within Home Assistant via Bluetooth Low Energy (BLE).

It provides entities to:
- Display the last sent image (Camera).
- Show the current status of the device (Sensor).
- Manually trigger an update from a configured source entity (Button).
- Configure the delay between sending packets (Number).
- Select the source image entity and the update mode (Select).
- Enable or disable automatic updates (Switch).

## Structure

The integration follows the standard Home Assistant custom component structure, residing in the `custom_components/aintinksmart/` directory.

- `__init__.py`: The entry point of the integration. It handles the setup and unloading of the integration, sets up the platforms, and registers the custom services.
- `const.py`: Defines constants used throughout the integration, including domain name, platform names, configuration keys, device states, and service attributes.
- `config_flow.py`: Manages the configuration flow for adding devices. It handles BLE discovery and manual entry of device MAC address.
- `device.py`: Contains the core logic for managing a single Ain't Ink Smart device instance. It handles BLE communication (delegating to `ble_comms.py`), tracks the device's state, processes image data, formats the protocol payload, builds packets, and provides state data to the entities.
- `ble_comms.py`: Provides functions for sending image packets to the e-ink display via BLE. It handles connecting to the BLE device and writing data to the appropriate characteristic.
- `helpers.py`: Contains helper classes and functions for image processing (converting images to bitplanes), protocol formatting (generating RLE or packed hex payloads), and packet building (calculating CRC and applying XOR encryption).
- `manifest.json`: Standard Home Assistant manifest file, specifying the integration's domain, name, version, required Python packages, and dependencies (like `bluetooth`).
- `services.yaml`: Defines the custom services exposed by the integration (`send_image` and `force_update`).
- `strings.json`: Contains translatable strings used in the configuration flow and UI.
- `button.py`: Defines the `Force Update Display` button entity.
- `camera.py`: Defines the `Display Image` camera entity.
- `entity.py`: A base class for all entities, providing common functionality like unique IDs, device info, and state update listeners.
- `number.py`: Defines the `Packet Delay` number entity.
- `select.py`: Defines `Source Entity` and `Update Mode` select entities.
- `sensor.py`: Defines the `Status` sensor entity.
- `switch.py`: Defines the `Enable Auto Update` switch entity.

## Usage

1.  **Installation:** Copy the `aintinksmart` folder into the `custom_components` directory of your Home Assistant configuration (or install via HACS).
2.  **Configuration:**
    *   Go to **Settings -> Devices & Services**.
    *   Click **+ Add Integration**.
    *   Search for "Ain't Ink Smart E-Ink Display".
    *   The integration will attempt to discover devices via Bluetooth. If your device is found, select it.
    *   Alternatively, choose "Add MAC manually" and provide the MAC address.
3.  **Entities:** Once configured, the integration creates several entities for your device:
    *   A Camera entity to show the last image sent.
    *   A Sensor entity to show the device's current status.
    *   A Button entity to manually trigger an image update.
    *   A Number entity to adjust the delay between packets.
    *   Select entities to choose the source image entity and color mode.
    *   A Switch entity to enable/disable automatic updates.
4.  **Services:**
    *   `aintinksmart.send_image`: Send an image to the display (base64 data or entity ID, plus mode).
    *   `aintinksmart.force_update`: Force an update from the currently selected source entity.

## How it Works

The integration operates by managing device instances (`device.py`) for each configured e-ink display.

-   **Configuration:** The `config_flow.py` handles the initial setup, allowing users to add devices via BLE discovery or manual MAC entry.
-   **Device Management:** The `device.py` class maintains the state for a single device. It listens for Bluetooth advertisements to determine device availability and status.
-   **Image Sending:** When an update is triggered, `device.py` fetches the image, processes it using `helpers.ImageProcessor` to create black and red bitplanes, formats the data using `helpers.ProtocolFormatter` (choosing between RLE and packed formats), and builds the final packets using `helpers.PacketBuilder` (including CRC and XOR encryption).
-   **Communication:** The prepared packets are sent via `ble_comms.py` using the `bleak` library.
-   **Entity Updates:** Entities subscribe to state changes from their corresponding `device.py` manager instance via a listener pattern.

This structure allows for a clear separation of concerns, with `device.py` acting as the central hub for each display.
