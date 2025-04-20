# Ain't Ink Smart Home Assistant Integration

This document provides comprehensive information on the Ain't Ink Smart custom component for Home Assistant, covering its purpose, installation, configuration, usage, and internal structure.

## Intended Purpose

The Ain't Ink Smart integration allows users to control and display images on compatible e-ink displays from within Home Assistant. It supports sending images via either Bluetooth Low Energy (BLE) or an MQTT gateway, providing flexibility depending on the user's setup and the display's capabilities.

It provides entities to:
- Display the last sent image (Camera).
- Show the current status of the device (Sensor).
- Manually trigger an update from a configured source entity (Button).
- Configure the delay between sending packets (Number).
- Select the source image entity and the update mode (Select).

## Installation

### Method 1: HACS (Recommended)

1.  **Ensure HACS is installed.**
2.  **Add Custom Repository:**
    *   Go to HACS > Integrations > Click the three dots in the top right > Custom Repositories.
    *   Enter the URL of this GitHub repository (`<YOUR_REPOSITORY_URL>`).
    *   Select "Integration" as the category.
    *   Click "Add".
3.  **Install Integration:**
    *   Search for "Ain't Ink Smart E-Ink Display" in HACS > Integrations.
    *   Click "Install".
4.  **Restart Home Assistant:** Restart your Home Assistant instance.

### Method 2: Manual Installation

1.  **Copy Files:** Copy the `custom_components/aintinksmart` directory from this repository into your Home Assistant `config/custom_components/` directory.
2.  **Restart Home Assistant:** Restart your Home Assistant instance.

## Configuration

1.  **Add Integration:** Go to **Settings > Devices & Services > Add Integration**.
2.  **Search:** Search for "Ain't Ink Smart E-Ink Display" and select it.
3.  **Device Discovery:**
    *   If your display is discovered via Bluetooth, select it from the list.
    *   If not discovered, choose "Enter MAC address manually" and provide the display's Bluetooth MAC address (e.g., `AA:BB:CC:DD:EE:FF`).
4.  **Communication Mode:** Select the communication mode (Direct BLE or MQTT Gateway). If choosing MQTT, provide the base topic used by your MQTT gateway firmware.
5.  **Setup Complete:** Complete the configuration flow. The integration will set up the device and its associated entities.

## Entities

For each configured display, the integration creates the following entities:

*   **Status Sensor (`sensor.<display_name>_status`):**
    *   Shows the current operational status of the display connection and updates.
    *   **States:**
        *   `idle`: Ready for commands.
        *   `connecting`: Attempting to connect via BLE.
        *   `sending_image`: Actively sending image data.
        *   `success`: Last image send operation completed successfully.
        *   `connection_error`: Failed to connect or communicate via BLE.
        *   `timeout_error`: BLE operation timed out.
        *   `send_error`: Error during BLE packet sending.
        *   `image_fetch_error`: Failed to retrieve image from the source entity.
        *   `image_process_error`: Failed during local image processing (e.g., invalid base64).
        *   `unknown_error`: An unexpected error occurred.
        *   `unavailable`: Device is not currently detected via Bluetooth.
    *   **Attributes:**
        *   `last_update`: Timestamp of the last status change.
        *   `last_error`: Detailed message for the last error encountered (if any).

*   **Display Image Camera (`camera.<display_name>_display_image`):**
    *   Shows the last image that was **successfully** sent to the display.
    *   This acts as a visual confirmation of the display's current content.
    *   The state is restored across Home Assistant restarts.

*   **Source Entity Select (`select.<display_name>_source_entity`):**
    *   A dropdown list containing all available `camera` and `image` entities in your Home Assistant instance.
    *   Select the entity you want the e-ink display to automatically mirror.
    *   Changing the selection here will trigger an update check.

*   **Update Mode Select (`select.<display_name>_update_mode`):**
    *   A dropdown to choose the color mode for automatic updates.
    *   **Options:**
        *   `bw`: Black and White
        *   `bwr`: Black, White, and Red (Default)
    *   Select the mode appropriate for your display hardware and desired image output.

*   **Packet Delay Number (`number.<display_name>_packet_delay`):**
    *   Allows users to configure the delay in milliseconds between sending packets to the display. This can be useful for optimizing communication stability.

*   **Force Update Button (`button.<display_name>_force_update_display`):**
    *   Pressing this button immediately triggers an attempt to send the image from the currently selected **Source Entity** to the display, using the currently selected **Update Mode**.
    *   This bypasses the check for image differences, useful for forcing a refresh.

*   **Enable Auto Update Switch (`switch.<display_name>_enable_auto_update`):**
    *   A switch to enable or disable the automatic update functionality.
    *   When **ON** (default), the integration monitors the selected **Source Entity** and sends updates to the display when the source image changes.
    *   When **OFF**, automatic updates based on source entity changes are disabled. Manual updates via the **Force Update Button** or the `send_image` service are still possible.
    *   The state of this switch is restored across Home Assistant restarts.

## Automatic Updates

-   The integration automatically monitors the **Source Entity Select**.
-   When you change the selected entity in the dropdown, the integration fetches the new source image.
-   It compares the fetched image to the last image successfully sent to the display.
-   If the images are different **and the Enable Auto Update switch is ON**, it sends the new image to the display using the mode selected in the **Update Mode Select**.
-   Updates are **not** performed on Home Assistant startup to prevent unnecessary refreshes; updates only occur when the selected source entity changes **and auto-update is enabled**.

## Services

*   **`aintinksmart.send_image`:**
    *   Manually send an image to one or more displays.
    *   **Target:** Select the target device(s).
    *   **Fields:**
        *   `image_data` (Optional): Base64 encoded image data.
        *   `image_entity_id` (Optional): Entity ID of a `camera` or `image` entity to fetch from. (Provide one of `image_data` or `image_entity_id`).
        *   `mode` (Required): Color mode (`bw` or `bwr`).

*   **`aintinksmart.force_update`:**
    *   Triggers an immediate update from the source entity selected in the device's **Source Entity Select** dropdown.
    *   Equivalent to pressing the **Force Update Button**.
    *   **Target:** Select the target device(s).
    *   **Fields:** None (uses the current select entity values).

## Error Handling

-   If an error occurs during connection, sending, or image processing, the **Status Sensor** will change to a specific error state (e.g., `connection_error`, `image_fetch_error`).
-   A detailed error message is available in the `last_error` attribute of the status sensor.

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

This structure allows for a clear separation of concerns, with `device.py` acting as the central hub for each display, managing its state and delegating communication and processing tasks to dedicated helper modules.