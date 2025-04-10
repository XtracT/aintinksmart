# BLE E-Ink Image Sender Service (Headless MQTT/BLE)

This project provides a Dockerized headless service to send black/white or black/white/red images to certain types of Bluetooth Low Energy (BLE) e-ink displays.

It operates in one of two modes, determined at startup by environment variables:

1.  **Direct BLE Mode (`BLE_ENABLED=true`, `USE_GATEWAY=false`):** Sends images and performs scans directly via BLE if the container has access to the host's Bluetooth stack.
2.  **MQTT Gateway Mode (`USE_GATEWAY=true`):** Publishes image commands and scan triggers via MQTT to a custom ESP32 gateway firmware (provided in `src/`), which then handles the BLE communication.

The service listens for image sending and scan requests on configured MQTT topics and publishes intermediate status updates to a default topic.

For a detailed overview of the system components and their interactions, please refer to the [System Architecture document](ARCHITECTURE.md).

## Description

The service implements a communication protocol based on reverse engineering. It listens for requests on MQTT topics.
- **Send Image:** When a request arrives (either via the default topic with JSON/base64 payload, or a mapped topic with raw bytes), it takes the image data, processes it, builds the necessary BLE packets, publishes status updates (e.g., "processing", "sending") to a default status topic, and attempts to send the packets using the configured method (Direct BLE or MQTT Gateway).
- **Scan:** When a scan request arrives, it either performs a direct BLE scan or triggers a scan via the MQTT gateway, based on the configured mode.

If a `response_topic` is included in the **default request topic's JSON payload**, the service will publish a final status message (success/error) back to that specific topic after the attempt is complete. `response_topic` is not supported for mapped topics receiving raw bytes.

The core logic uses `aiomqtt` for asynchronous MQTT communication and `bleak` for direct BLE interactions.

## Disclaimer

This service is unofficial and based on reverse engineering efforts. It is provided "as is" without warranty of any kind. Use at your own discretion and ensure you comply with any relevant terms of service for your device.

## Requirements

*   **Docker:** Required to build and run the service container.
*   **MQTT Broker:** Required for receiving requests and optionally for using the MQTT Gateway mode.
*   **Host System (for Direct BLE Mode):**
    *   A compatible BLE adapter (e.g., BlueZ on Linux).
    *   Working Bluetooth stack accessible by Docker (see Running the Service).
*   **Custom ESP32 Firmware (for MQTT Gateway Mode):** An ESP32 device running the custom gateway firmware provided in the `src/` directory.
*   **(For Development/CLI):** Python 3.10+ and the libraries listed in `requirements.txt` (includes `paho-mqtt` for CLI scripts).

## Configuration (Environment Variables)

The service is configured using environment variables when running the Docker container:

*   `BLE_ENABLED` (Optional): Set to `true` (default) or `false`. Required for Direct BLE mode.
*   `USE_GATEWAY` (Optional): Set to `true` or `false` (default). If `true`, MQTT Gateway mode is used (requires `MQTT_BROKER` to be set). If `false`, Direct BLE mode is used (requires `BLE_ENABLED=true`).
*   `MQTT_BROKER` (Required): Address/hostname of your MQTT broker (e.g., `192.168.1.100`).
*   `MQTT_PORT` (Optional): Port of the MQTT broker (default: `1883`).
*   `MQTT_USERNAME` (Optional): Username for MQTT authentication.
*   `MQTT_PASSWORD` (Optional): Password for MQTT authentication.
*   `MQTT_REQUEST_TOPIC` (Optional): Topic for image send requests using JSON/base64 payload (default: `aintinksmart/service/request/send_image`).
*   `MQTT_SCAN_REQUEST_TOPIC` (Optional): Topic for scan requests (default: `aintinksmart/service/request/scan`).
*   `MQTT_DEFAULT_STATUS_TOPIC` (Optional): Topic for service status updates and direct BLE scan results (default: `aintinksmart/service/status/default`).
*   `MQTT_GATEWAY_BASE_TOPIC` (Optional, for MQTT Gateway Mode): Base topic for communicating with the ESP32 gateway (default: `aintinksmart/gateway`). Commands are sent to specific sub-topics under this base. Gateway status and results are also published under this base. For a complete list and description of all MQTT topics, see [mqtt_topics.md](mqtt_topics.md).
*   `EINK_PACKET_DELAY_MS` (Optional, for MQTT Gateway Mode): Delay in milliseconds between sending individual packet messages via MQTT to the custom firmware. Defaults to `20`.
*   `MQTT_IMAGE_TOPIC_MAPPINGS` (Optional): A JSON string mapping specific MQTT topics to target MAC addresses. Allows receiving **raw image bytes** (e.g., PNG file content) directly on these topics. The service internally converts this to the expected base64 format. Example: `'{"mealiemate/image/kitchen": "AA:BB:CC:DD:EE:FF", "another/topic/office": "11:22:33:44:55:66"}'`. Defaults to `{}` (disabled). Images received via these topics are assumed to be `bwr` mode.

**Note:** The service will exit on startup if a valid operating mode cannot be determined (e.g., `USE_GATEWAY=true` but `MQTT_BROKER` is not set, or `USE_GATEWAY=false` and `BLE_ENABLED=false`).

## Setup & Running the Service

1.  **(Optional) Configure ESP32 Firmware:** If using MQTT Gateway mode, configure and flash the firmware in the `src/` directory to your ESP32 (see "Custom ESP32 Firmware" section below).
2.  **Build the Docker Image:**
    ```bash
    docker build -t ble-sender-service .
    ```
3.  **Run the Docker Container:** (Choose one mode)

    *   **Example: MQTT Gateway Mode:**
        ```bash
        docker run --rm -it \
          -e MQTT_BROKER=<your_broker_ip> \
          -e MQTT_USERNAME=<your_mqtt_user> \
          -e MQTT_PASSWORD=<your_mqtt_pass> \
          -e USE_GATEWAY=true \
          # -e MQTT_REQUEST_TOPIC=custom/request/topic # Optional
          # -e MQTT_SCAN_REQUEST_TOPIC=custom/scan/topic # Optional
          # -e MQTT_DEFAULT_STATUS_TOPIC=custom/status/topic # Optional
          # -e MQTT_GATEWAY_BASE_TOPIC=custom/gateway # Optional
          # -e MQTT_IMAGE_TOPIC_MAPPINGS='{"topic/one":"MAC1", "topic/two":"MAC2"}' # Optional
          ble-sender-service
        ```

    *   **Example: Direct BLE Mode:** (Requires host BLE access)
        ```bash
        # Ensure container has BLE access by mounting the host's D-Bus socket.
        # This is often more reliable than --net=host for BLE access via D-Bus.
        docker run --rm -it -v /var/run/dbus:/var/run/dbus \
          -e MQTT_BROKER=<your_broker_ip> \
          -e MQTT_USERNAME=<your_mqtt_user> \
          -e MQTT_PASSWORD=<your_mqtt_pass> \
          -e BLE_ENABLED=true \
          -e USE_GATEWAY=false \
          # -e MQTT_REQUEST_TOPIC=custom/request/topic # Optional
          # -e MQTT_SCAN_REQUEST_TOPIC=custom/scan/topic # Optional
          # -e MQTT_DEFAULT_STATUS_TOPIC=custom/status/topic # Optional
          # -e MQTT_IMAGE_TOPIC_MAPPINGS='{"topic/one":"MAC1", "topic/two":"MAC2"}' # Optional
          ble-sender-service
        ```

## Usage (via MQTT or CLI Scripts)

Communication primarily happens via MQTT messages. See [mqtt_topics.md](mqtt_topics.md) for details on the specific topics used for requests and status updates.

### 1. Sending an Image

*   **Via MQTT (Two Methods):**

    1.  **Default Request Topic:** Publish a JSON payload to the configured `MQTT_REQUEST_TOPIC` (default: `aintinksmart/service/request/send_image`). The MAC address *must* be included in the payload.
        ```json
        {
          "mac_address": "AA:BB:CC:DD:EE:FF",
          "image_data": "base64_encoded_image_string_here...",
          "mode": "bwr", // or "bw"
          "response_topic": "optional/topic/for/result" // Optional
        }
        ```

    2.  **Mapped Image Topics:** If `MQTT_IMAGE_TOPIC_MAPPINGS` is configured, publish the **raw image bytes** (e.g., the content of a PNG file) directly as the payload to one of the topics defined as a key in the mapping. The MAC address is determined from the mapping based on the topic used. The image `mode` is assumed to be `bwr` for these topics. `response_topic` is **not supported** for this method.
        ```bash
        # Example: Publishing raw PNG data to "mealiemate/image/kitchen"
        # (Using mosquitto_pub)
        mosquitto_pub -h <broker> -t mealiemate/image/kitchen -f /path/to/image.png
        ```

    *   **Monitoring:** Monitor the `MQTT_DEFAULT_STATUS_TOPIC` (default: `aintinksmart/service/status/default`) for intermediate status updates (JSON payload: `{"mac_address": "...", "status": "...", ...}`). For MQTT Gateway mode, the service initially returns `gateway_start_sent`. You must monitor subsequent status updates (like `gateway_sending_packets`, `gateway_success`, `gateway_error_*`) relayed from the ESP32 on this topic to know the final outcome. If `response_topic` was provided *only* in the **Default Request Topic** payload, the final result (`success` or `error`) will also be published there.

*   **Via CLI Script (`send_image_cli.py`):**
    (Requires Python and `paho-mqtt` installed locally: `pip install paho-mqtt`)
    ```bash
    python send_image_cli.py \
      --broker <your_broker_ip> \
      --user <your_mqtt_user> \
      --pass <your_mqtt_pass> \
      --mac AA:BB:CC:DD:EE:FF \
      --image /path/to/your/image.png \
      --mode bwr \
      --response-topic sender/result # Optional: wait for specific final result
      # --default-status-topic aintinksmart/service/status/custom # Optional
      # --timeout 60 # Optional: seconds to wait for status/response
    ```
    The script automatically subscribes to the default status topic and prints updates for the target MAC address. If `--response-topic` is given, it waits for a message on that topic or until the timeout. Use `python send_image_cli.py --help` for all options.

### 2. Scanning for Devices

*   **Via MQTT:**
    Publish a JSON payload to the configured `MQTT_SCAN_REQUEST_TOPIC` (default: `aintinksmart/service/request/scan`).
    ```json
    {
      "action": "scan",
      "response_topic": "optional/topic/for/result" // Optional
    }
    ```
    If `response_topic` is provided:
    *   In Direct BLE mode, monitor the `MQTT_DEFAULT_STATUS_TOPIC` (default: `aintinksmart/service/status/default`) for a JSON result: `{"status": "success", "method": "ble", "devices": [...]}`.
    *   In MQTT Gateway mode, monitor the `response_topic` (if provided) for a confirmation: `{"status": "success", "method": "mqtt", ...}`. You must *also* separately monitor the gateway's result topic (default: `aintinksmart/gateway/bridge/scan_result`) for the actual devices found by the ESP32.

*   **Via CLI Script (`scan_ble_cli.py`):**
    (Requires Python and `paho-mqtt` installed locally: `pip install paho-mqtt`)
    ```bash
    python scan_ble_cli.py \
      --broker <your_broker_ip> \
      --user <your_mqtt_user> \
      --pass <your_mqtt_pass> \
      --timeout 20 # Optional: seconds to wait
    ```
    This script automatically subscribes to the service status topic (`--service-status-topic`) and the gateway result topic (`--gateway-result-topic`), publishing the scan request and printing any discovered devices received on either topic within the timeout. Use `python scan_ble_cli.py --help` for all options.

## Reference Scripts

### `send_bwr_ble.py`

This script represents the original proof-of-concept developed during the reverse engineering of the e-ink display's BLE communication protocol. It demonstrates the core logic for connecting and sending image data directly via BLE using the `bleak` library, without the surrounding service infrastructure (MQTT, Docker, etc.).

It is included in the repository primarily for reference purposes, allowing users to understand the fundamental BLE interaction sequence without needing to navigate the more complex service application code.

## Custom ESP32 Firmware (MQTT Gateway Mode)

The MQTT functionality relies on the custom ESP32 firmware located in the `src/` directory. See [ARCHITECTURE.md](ARCHITECTURE.md) for more details on the gateway's role and interaction with the service.

**Functionality:**
*   Connects to WiFi and MQTT broker.
*   Subscribes to display command topics: `{base}/display/+/command/start`, `{base}/display/+/command/packet`. (The `.../end` topic is no longer used).
*   Subscribes to bridge scan command topic: `{base}/bridge/command/scan`.
*   Handles image transfer commands: Receives the expected packet count in the `start` payload. Waits for the BLE connection to the display to be established (publishing `connected_ble` status) before processing packets. Receives packets sequentially on the `packet` topic (MQTT QoS 1 ensures order). Determines completion based on receiving the expected number of packets or a packet receive timeout (to handle potential packet loss).
*   Publishes display status updates to `{base}/display/{MAC_NO_COLONS}/status`.
*   Publishes bridge status updates to `{base}/bridge/status`.
*   On receiving message on `{base}/bridge/command/scan`, performs BLE scan and publishes results to `{base}/bridge/scan_result`.

**Setup:**
1.  Configure `src/config.h`.
2.  Compile and flash using PlatformIO.

## Compatibility

| Size  | Resolution | Colors | Part Number | Tested Status | Notes |
| :---- | :--------- | :----- | :---------- | :------------ | :---- |
| 7.5"  | 800x480    | BWR    | AES0750     | Yes           |       |

## Troubleshooting

*   **Docker Build/Run Issues:** Check environment variables, BLE access permissions if using Direct BLE mode. Ensure correct operating mode is selected via `USE_GATEWAY` and `BLE_ENABLED`.
*   **MQTT Issues:** Verify broker details. Check service request topics (`MQTT_REQUEST_TOPIC`, `MQTT_SCAN_REQUEST_TOPIC`) and status topic (`MQTT_DEFAULT_STATUS_TOPIC`). If using Gateway Mode, check `MQTT_GATEWAY_BASE_TOPIC`. Use an MQTT client (like `mqttx` or `mosquitto_sub`) to monitor topics. Check service logs.
*   **BLE Issues (Direct or Gateway):** Ensure display is powered, in range. Double-check MAC address. Check service logs for `BleakError`. Check ESP32 serial monitor output if using Gateway Mode.
*   **Image Appearance:** Ensure correct `mode` ("bw" or "bwr") is specified.

## Contributing

## License