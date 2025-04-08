# Ain't Ink Smart Home Assistant Integration

This document explains how to install, configure, and use the Ain't Ink Smart custom integration for Home Assistant.

## Installation

1.  **Copy Files:** Copy the `custom_components/aintinksmart` directory into your Home Assistant `config/custom_components/` directory.
2.  **Restart Home Assistant:** Restart your Home Assistant instance to load the new integration.

## Configuration

1.  **Add Integration:** Go to **Settings > Devices & Services > Add Integration**.
2.  **Search:** Search for "Ain't Ink Smart E-Ink Display" and select it.
3.  **Device Discovery:**
    *   If your display is discovered via Bluetooth, select it from the list.
    *   If not discovered, choose "Enter MAC address manually" and provide the display's Bluetooth MAC address (e.g., `AA:BB:CC:DD:EE:FF`).
4.  **Setup Complete:** The integration will set up the device and its associated entities.

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

*   **Force Update Button (`button.<display_name>_force_update_display`):**
    *   Pressing this button immediately triggers an attempt to send the image from the currently selected **Source Entity** to the display, using the currently selected **Update Mode**.
    *   This bypasses the check for image differences, useful for forcing a refresh.

## Automatic Updates

-   The integration automatically monitors the **Source Entity Select**.
-   When you change the selected entity in the dropdown, the integration fetches the new source image.
-   It compares the fetched image to the last image successfully sent to the display.
-   If the images are different, it sends the new image to the display using the mode selected in the **Update Mode Select**.
-   Updates are **not** performed on Home Assistant startup to prevent unnecessary refreshes; updates only occur when the selected source entity changes.

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