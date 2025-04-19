# Ain't Ink Smart Home Assistant Integration

This document explains the structure, purpose, and usage of the Ain't Ink Smart custom component for Home Assistant.

## Intended Purpose

The Ain't Ink Smart integration allows users to control and display images on compatible e-ink displays from within Home Assistant. It supports sending images via either Bluetooth Low Energy (BLE) or an MQTT gateway, providing flexibility depending on the user's setup and the display's capabilities.

It provides entities to:
- Display the last sent image (Camera).
- Show the current status of the device (Sensor).
- Manually trigger an update from a configured source entity (Button).
- Configure the delay between sending packets (Number).
- Select the source image entity and the update mode (Select).

## Structure

The integration follows the standard Home Assistant custom component structure, residing in the `custom_components/aintinksmart/` directory.

- `__init__.py`: The entry point of the integration. It handles the setup and unloading of the integration, sets up the platforms (sensor, camera, button, select, number), and registers the custom services.
- `const.py`: Defines constants used throughout the integration, including domain name, platform names, configuration keys, device states, communication modes, and service attributes.
- `config_flow.py`: Manages the configuration flow for adding devices. It handles discovery (currently primarily BLE) and manual entry of device details, including MAC address and communication mode (BLE or MQTT).
- `device.py`: Contains the core logic for managing a single Ain't Ink Smart device instance. It handles the communication (delegating to `ble_comms.py` or `mqtt_comms.py`), tracks the device's state, processes image data, formats the protocol payload, builds packets, and provides state data to the entities.
- `ble_comms.py`: Provides functions for sending image packets to the e-ink display via BLE. It handles connecting to the BLE device and writing data to the appropriate characteristic.
- `mqtt_comms.py`: Provides functions for sending image packets to the e-ink display via an MQTT gateway. It publishes packets to specific MQTT topics based on the configured base topic and device MAC address.
- `helpers.py`: Contains helper classes and functions for image processing (converting images to bitplanes), protocol formatting (generating RLE or packed hex payloads), and packet building (calculating CRC and applying XOR encryption).
- `manifest.json`: Standard Home Assistant manifest file, specifying the integration's domain, name, version, documentation links, code owners, required Python packages, and dependencies on other Home Assistant integrations (like `bluetooth` and `mqtt`).
- `services.yaml`: Defines the custom services exposed by the integration (`send_image` and `force_update`), including their names, descriptions, and input fields with validation schemas.
- `strings.json`: Contains translatable strings used in the configuration flow and potentially other parts of the integration's UI.
- `button.py`: Defines the `Force Update Display` button entity, which triggers the `force_update` service call using the currently selected source entity and update mode.
- `camera.py`: Defines the `Display Image` camera entity, which displays the last image successfully sent to the device. It retrieves the image data from the `device.py` manager.
- `entity.py`: A base class for all entities within the `aintinksmart` domain. It provides common functionality like setting up unique IDs, device information, and handling state updates by registering listeners with the `device.py` manager.
- `number.py`: Defines the `Packet Delay` number entity, allowing users to configure the delay in milliseconds between sending packets to the display. This can be useful for optimizing communication stability.
- `select.py`: Defines two select entities: `Source Entity` (to choose which Home Assistant image or camera entity to use as the source for updates) and `Update Mode` (to select between 'bw' and 'bwr' color modes for updates).

## Usage

1.  **Installation:** Copy the `aintinksmart` folder into the `custom_components` directory of your Home Assistant configuration.
2.  **Configuration:**
    *   Go to **Settings -> Devices & Services**.
    *   Click **+ Add Integration**.
    *   Search for "Ain't Ink Smart E-Ink Display".
    *   The integration will attempt to discover devices via Bluetooth. If your device is found, you can select it.
    *   Alternatively, choose "Enter device details manually" and provide the MAC address.
    *   Select the communication mode (Direct BLE or MQTT Gateway). If choosing MQTT, provide the base topic used by your MQTT gateway firmware.
    *   Complete the configuration flow.
3.  **Entities:** Once configured, the integration will create several entities for your device:
    *   A Camera entity (`camera.aint_ink_smart_display_display_image`) to show the last image sent.
    *   A Sensor entity (`sensor.aint_ink_smart_display_status`) to show the device's current status (Idle, Sending, Error, etc.).
    *   A Button entity (`button.aint_ink_smart_display_force_update_display`) to manually trigger an image update from the selected source.
    *   A Number entity (`number.aint_ink_smart_display_packet_delay`) to adjust the delay between packets.
    *   Select entities (`select.aint_ink_smart_display_source_entity` and `select.aint_ink_smart_display_update_mode`) to choose the source image entity and color mode for updates.
4.  **Services:** The integration provides two services under the `aintinksmart` domain:
    *   `aintinksmart.send_image`: Send an image to the display. You can provide the image as base64 data (`image_data`) or by specifying the entity ID of a Home Assistant image or camera entity (`image_entity_id`). You must also specify the `mode` ('bw' or 'bwr').
    *   `aintinksmart.force_update`: Force the display to update using the image from the entity selected in the `Source Entity` select helper and the mode selected in the `Update Mode` select helper. This service targets the device entity.

## How it Works

The integration operates by managing device instances (`device.py`) for each configured e-ink display.

-   **Configuration:** The `config_flow.py` handles the initial setup, allowing users to add devices and specify their communication method.
-   **Device Management:** The `device.py` class maintains the state for a single device. It listens for Bluetooth advertisements (in BLE mode) or MQTT status messages (in MQTT mode) to determine device availability and status.
-   **Image Sending:** When the `aintinksmart.send_image` service is called, the `device.py` manager fetches the image (either from base64 data or a Home Assistant entity), processes it using `helpers.ImageProcessor` to create black and red bitplanes, formats the data using `helpers.ProtocolFormatter` (choosing between RLE and packed formats), and builds the final packets using `helpers.PacketBuilder` (including CRC and XOR encryption).
-   **Communication:** The prepared packets are then sent via either `ble_comms.py` (for direct BLE communication) or `mqtt_comms.py` (for publishing to an MQTT gateway), depending on the configured mode.
-   **Entity Updates:** Entities (`sensor.py`, `camera.py`, `button.py`, `number.py`, `select.py`) subscribe to state changes from their corresponding `device.py` manager instance. When the manager's state updates (e.g., status changes, last image sent), it notifies its listeners, and the entities update their representation in Home Assistant.
-   **Force Update:** The `force_update` service and the `Force Update Display` button trigger the `device.py` manager to fetch the image from the entity currently selected in the `Source Entity` select helper and send it using the mode selected in the `Update Mode` select helper.

This structure allows for a clear separation of concerns, with `device.py` acting as the central hub for each display, managing its state and delegating communication and processing tasks to dedicated helper modules.