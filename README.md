# BLE E-Ink Image Sender Service (Hybrid: Direct BLE + MQTT)

This project provides a Dockerized web service (using FastAPI) to send black/white or black/white/red images to certain types of Bluetooth Low Energy (BLE) e-ink displays.

It operates in a **hybrid mode**:
1.  It can attempt to send images **directly via BLE** if the container has access to the host's Bluetooth stack.
2.  It can **publish commands via MQTT to a custom ESP32 gateway firmware** (provided in `src/`), which then handles the BLE communication with the target display specified in the MQTT topic.

This offers flexibility for different deployment scenarios. The service provides both a simple Web UI and a JSON API.

## Description

The service implements a communication protocol based on reverse engineering. It takes an image file, processes it, builds the necessary BLE packets (including CRC and encryption), and then attempts to send them using one or both configured methods:
*   **Direct BLE:** Using the host system's Bluetooth adapter.
*   **MQTT Gateway:** Publishing start/packet/end commands to the custom ESP32 gateway firmware via MQTT.

The core logic is separated into distinct Python classes within the `app/` directory.

## Disclaimer

This service is unofficial and based on reverse engineering efforts. It is provided "as is" without warranty of any kind. Use at your own discretion and ensure you comply with any relevant terms of service for your device.

## Requirements

*   **Docker:** Required to build and run the service container.
*   **MQTT Broker (Optional):** Required if using the MQTT publishing feature.
*   **Host System (for Direct BLE):**
*   A compatible BLE adapter (e.g., BlueZ on Linux).
*   Working Bluetooth stack accessible by Docker (see Running the Service).
*   **Custom ESP32 Firmware (Optional, for MQTT Mode):** An ESP32 device running the custom gateway firmware provided in the `src/` directory of this project. This firmware receives commands via MQTT and performs the BLE transmission to the target display.
*   **(For Development):** Python 3.7+ and the libraries listed in `requirements.txt`.

## Configuration (Environment Variables)

The service is configured using environment variables when running the Docker container:

*   `BLE_ENABLED` (Optional): Set to `true` (default) or `false`. If `false`, direct BLE attempts (including discovery) will be skipped.
*   `MQTT_ENABLED` (Optional): Set to `true` or `false`. Defaults to `true` if `MQTT_BROKER` is set, otherwise `false`. Controls whether MQTT publishing occurs.
*   `MQTT_BROKER` (Optional): Address/hostname of your MQTT broker (e.g., `192.168.1.100`). Setting this enables MQTT functionality by default.
*   `MQTT_PORT` (Optional): Port of the MQTT broker (default: `1883`).
*   `MQTT_USERNAME` (Optional): Username for MQTT authentication.
*   `MQTT_PASSWORD` (Optional): Password for MQTT authentication.
*   `MQTT_EINK_TOPIC_BASE` (Optional): Base topic used for communicating with the custom ESP32 firmware (default: `eink_display`). Commands are sent to `{MQTT_EINK_TOPIC_BASE}/{MAC_NO_COLONS}/command/{start|packet|end}` and status is received from `{MQTT_EINK_TOPIC_BASE}/{MAC_NO_COLONS}/status`. `{MAC_NO_COLONS}` is the target device's MAC address without colons (e.g., `AABBCCDDEEFF`).
*   `EINK_PACKET_DELAY_MS` (Optional): Delay in milliseconds between sending individual packet messages via MQTT to the custom firmware. Defaults to `20`. This value (20ms) was found to work reliably with the custom firmware.

## Setup & Running the Service

1.  **Build the Docker Image:**
    ```bash
    docker build -t ble-sender-service .
    ```

2.  **Run the Docker Container:**
    Choose options based on whether you need direct BLE, MQTT, or both.

    *   **Example: Direct BLE + MQTT:** (Requires host BLE access)
        ```bash
        docker run --rm -it --net=host \
          -e MQTT_BROKER=<your_broker_ip> \
          -e MQTT_USERNAME=<your_mqtt_user> \
          -e MQTT_PASSWORD=<your_mqtt_pass> \
          # -e MQTT_COMMAND_TOPIC=custom/topic # Optional: Override default topic
          ble-sender-service
        ```

    *   **Example: MQTT Only:** (Container doesn't need host BLE access)
        ```bash
        docker run --rm -it -p 8000:8000 \
          -e MQTT_BROKER=<your_broker_ip> \
          -e MQTT_USERNAME=<your_mqtt_user> \
          -e MQTT_PASSWORD=<your_mqtt_pass> \
          -e BLE_ENABLED=false \
          ble-sender-service
        ```

    *   **Example: Direct BLE Only:** (Requires host BLE access)
        ```bash
        docker run --rm -it --net=host \
          # Ensure MQTT_BROKER is NOT set, or set MQTT_ENABLED=false
          ble-sender-service
        ```
        *(Note on BLE Access: Use `--net=host` or `-v /var/run/dbus:/var/run/dbus` plus potentially other privileges as needed for your host system.)*

    The service should now be running on port 8000.

## Usage

### Web UI

1.  Open your web browser to `http://localhost:8000` (or the IP address of your Docker host).
2.  Use the form to:
    *   Select an image file.
    *   Enter the target display's BLE MAC address **OR** click "Discover".
        *   **Note:** The "Discover" button uses a hybrid approach. If `BLE_ENABLED=true` and the container has Bluetooth access, it performs a direct BLE scan. If `MQTT_ENABLED=true`, it *also* triggers a scan via the ESP32 gateway by publishing to `{MQTT_EINK_TOPIC_BASE}/scan/command`. The service waits briefly for results published by the ESP32 to `{MQTT_EINK_TOPIC_BASE}/scan/result` and combines them with any direct scan results. Discovery works if *either* method is enabled and functional.
        *   If devices are found, select one from the dropdown to populate the MAC address field.
    *   Choose the color mode (`bwr` or `bw`).
    *   Click "Send Image".
3.  Status messages will indicate success (via BLE or MQTT) or failure.

### JSON API

Send a `POST` request to the `/send_image` endpoint (e.g., `http://localhost:8000/send_image`).

> **Note:** Interactive API documentation (Swagger UI) is available at `/docs` and alternative documentation (ReDoc) is at `/redoc` when the service is running.

*   **Method:** `POST`
*   **URL:** `/send_image`
*   **Headers:** `Content-Type: application/json`
*   **Body (JSON):**
    ```json
    {
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "image_data": "base64_encoded_image_string_here...",
      "mode": "bwr" // Optional, defaults to "bwr"
    }
    ```
*   **Responses:**
    *   **Success (200 OK):** Message indicates if sent via BLE, MQTT, or both.
        ```json
        {
          "status": "success",
          "message": "Image sent successfully via direct BLE to AA:BB:CC:DD:EE:FF. (Also published to MQTT)."
        }
        ```
        ```json
        {
          "status": "success",
          "message": "Direct BLE failed. Image packets published successfully via MQTT for AA:BB:CC:DD:EE:FF. Final ESP Status: complete."
        }
        ```
    *   **Error (4xx or 5xx):** Indicates failure in processing or both communication methods.
        ```json
        {
          "status": "error",
          "message": "Both direct BLE communication and MQTT publishing failed."
          // Or other specific error message
        }
        ```

## Custom ESP32 Firmware (MQTT Gateway Mode)

The MQTT functionality relies on the custom ESP32 firmware located in the `src/` directory of this project. This firmware acts as a dedicated MQTT-to-BLE gateway for the E-Ink displays.

**Functionality:**
*   Connects to WiFi and the specified MQTT broker.
*   Subscribes to wildcard command topics: `{base}/+/command/start`, `{base}/+/command/packet`, `{base}/+/command/end`.
*   Parses the target device MAC address from the received topic.
*   Handles one transfer at a time. If a `start` command for a new MAC arrives while busy, it's ignored.
*   On `start`: Connects to the target BLE device specified in the topic.
*   On `packet`: Queues the received hex payload (after converting to bytes) for writing to the BLE characteristic.
*   On `end`: Signals the end of packet reception.
*   Manages BLE connection retries and packet writing.
*   Publishes status updates (e.g., `starting`, `connecting_ble`, `writing`, `complete`, `error_...`) to a device-specific status topic: `{base}/{MAC_NO_COLONS}/status`.
*   Listens for scan commands (any payload) on `{MQTT_EINK_TOPIC_BASE}/scan/command`.
*   Performs a **blocking** BLE scan for `SCAN_DURATION_SECONDS` (defined in `src/config.h`) looking for devices advertising the name "easytag" (case-insensitive).
*   Publishes discovered device details (`name`, `address`) as individual JSON messages to `{MQTT_EINK_TOPIC_BASE}/scan/result` for each matching device found during the scan.

**Setup:**
1.  Open the `src/config.h` file.
2.  Configure your `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_BROKER`, and optionally `MQTT_USER`/`MQTT_PASSWORD` placeholders. Verify `BLE_SERVICE_UUID_STR` and `BLE_CHARACTERISTIC_UUID_STR` match your display. Adjust `SCAN_DURATION_SECONDS` if needed.
3.  Compile and flash the firmware to your ESP32 device using PlatformIO (e.g., `platformio run --target upload`). Ensure the correct serial port is detected or specified in `platformio.ini`.

## Compatibility

(Same as before - based on protocol reverse engineering)

| Size  | Resolution | Colors | Part Number | Tested Status | Notes |
| :---- | :--------- | :----- | :---------- | :------------ | :---- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes           |       |

## Troubleshooting

*   **Docker Build/Run Issues:** See previous README versions. Pay attention to environment variables and BLE access permissions if needed.
*   **MQTT Issues:** Verify broker address, port, credentials. Check the base topic (`MQTT_EINK_TOPIC_BASE`) matches between the service and the firmware config (`src/config.h`). Use an MQTT client (like MQTT Explorer) to monitor the command topics (e.g., `eink_display/+/command/#`), status topics (`eink_display/+/status`), the scan command topic (`eink_display/scan/command`), and the scan result topic (`eink_display/scan/result`). Check service logs and ESP32 serial monitor output.
*   **BLE Issues (Direct or Gateway):** Ensure display is powered, in range, not connected elsewhere. Double-check MAC address. Check service/ESPHome logs for `BleakError` or connection failures.
*   **Image Appearance:** Same as before.

## Contributing

(Optional)

## License

(Optional)