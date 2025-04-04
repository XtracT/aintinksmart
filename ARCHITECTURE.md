# System Architecture: Headless BLE E-Ink Sender

This document outlines the architecture of the `aintinksmart` project, which comprises a Python headless service and an optional ESP32 firmware, working together to send images or perform BLE scans for specific BLE E-Ink displays.

## 1. Overall System Overview

The system operates as a headless service, listening for requests on MQTT topics. Based on environment variables set at startup, it performs actions using one of two methods:

1.  **Direct BLE Mode (`BLE_ENABLED=true`, `USE_GATEWAY=false`):** The Python service directly interacts with the host system's Bluetooth adapter to send image data or perform scans.
2.  **MQTT Gateway Mode (`USE_GATEWAY=true`):** The Python service publishes image commands or scan triggers via MQTT to a dedicated ESP32 device running the custom firmware (`src/`). The ESP32 firmware acts as a gateway, handling the BLE communication.

The service does not provide a Web UI or a direct HTTP API. Interaction occurs solely via MQTT messages, typically initiated by the provided CLI scripts (`send_image_cli.py`, `scan_ble_cli.py`) or other MQTT clients.

```mermaid
graph TD
    subgraph Python Service (Docker Container)
        A[MQTT Listener - main.py] -- Request Msg (Send/Scan) --> B{Request Processor - main.py};
        B -- Process Image --> C[Image Processor];
        B -- Format Payload --> D[Protocol Formatter];
        B -- Build Packets --> E[Packet Builder];
        B -- Mode? --> F{Method Dispatch};
        F -- Direct BLE Mode (Send) --> G[BLE Communicator];
        F -- MQTT Gateway Mode (Send) --> H[aiomqtt Client - main.py];
        F -- Direct BLE Mode (Scan) --> SB[Bleak Scanner];
        F -- MQTT Gateway Mode (Scan) --> H;
        B -- Response Msg --> H;
    end

    subgraph Host System
        G -- Host BLE Stack --> J((BLE E-Ink Display));
        SB -- Host BLE Stack --> J;
    end

    subgraph ESP32 Gateway (Optional)
        K[MQTT Client - mqtt_utils.cpp] <--> I(MQTT Broker);
        K -- Transfer Cmds --> L(Main Loop - main.cpp);
        L -- BLE Ops --> M[BLE Client - ble_utils.cpp];
        K -- Scan Cmd --> N[Scan Logic - scan_utils.cpp];
        N -- BLE Scan --> M;
        K -- Status Updates --> I;
        K -- Scan Results --> I;
        M -- BLE Stack --> J;
    end

    subgraph CLI Scripts / Other Clients
        CLI(send_image_cli.py / scan_ble_cli.py) -- Request --> I;
        CLI -- Listen for Response/Results --> I;
    end


    A <--> I;
    H <--> I;

    style J fill:#f9f,stroke:#333,stroke-width:2px
```

## 2. Python Headless Service (`app/`)

### Purpose

The Python service runs as a background process, listening for image sending and scan requests on configured MQTT topics. It validates requests, processes image data (base64 encoded) if applicable, formats data, builds BLE packets, and then attempts the requested action (send or scan) using either direct BLE or the MQTT gateway, based on the mode configured at startup. It can optionally publish results/status back to an MQTT topic specified in the request.

### Key Components

*   **`main.py`:** The main application entry point.
    *   Reads environment variables to determine operating mode (Direct BLE or MQTT Gateway).
    *   Initializes and manages the `aiomqtt` client connection.
    *   Subscribes to request topics (`MQTT_REQUEST_TOPIC`, `MQTT_SCAN_REQUEST_TOPIC`).
    *   Contains the main `async` loop (`run_service`) to listen for messages.
    *   Contains `async` request processing logic (`process_request`, `process_scan_request`).
    *   Calls image processing modules (`image_processor`, `protocol_formatter`, `packet_builder`).
    *   Calls the appropriate sending/scanning function (`attempt_direct_ble`, `attempt_mqtt_publish`, direct `BleakScanner.discover`, or MQTT scan trigger publish) based on operating mode and request type.
    *   Publishes results to a response topic if requested.
    *   Contains helper `async` functions for BLE sending (`attempt_direct_ble`) and MQTT command publishing (`attempt_mqtt_publish`).
*   **`ble_communicator.py`:** Handles direct BLE communication for *sending* images using `bleak`. Used only in Direct BLE mode for send requests. (Direct BLE scanning uses `BleakScanner` directly in `main.py`).
*   **`image_processor.py`:** Processes the input image bytes.
*   **`protocol_formatter.py`:** Formats raw pixel data.
*   **`packet_builder.py`:** Chunks formatted data into BLE packets.
*   **`models.py`:** Defines Pydantic models for request validation and shared types.
*   **`config.py`:** May contain shared constants.

### Workflow: Image Sending

1.  Service starts, determines operating mode (BLE or MQTT Gateway).
2.  Connects to MQTT broker, subscribes to `MQTT_REQUEST_TOPIC` and `MQTT_SCAN_REQUEST_TOPIC`.
3.  Enters loop awaiting messages.
4.  Image request message received on `MQTT_REQUEST_TOPIC`.
5.  `process_request` function is called.
6.  Payload parsed, image decoded, packets built.
7.  If mode is Direct BLE: `attempt_direct_ble` is called.
8.  If mode is MQTT Gateway: `attempt_mqtt_publish` is called.
9.  Result published to `response_topic` (if provided).
10. Returns to loop.

### Workflow: Scanning

1.  Service starts (as above).
2.  Enters loop awaiting messages.
3.  Scan request message received on `MQTT_SCAN_REQUEST_TOPIC`.
4.  `process_scan_request` function is called.
5.  Payload parsed.
6.  If mode is Direct BLE: `BleakScanner.discover()` is called, results filtered. Result payload containing device list is prepared.
7.  If mode is MQTT Gateway: Scan command published to `{MQTT_EINK_TOPIC_BASE}/scan/command`. Result payload indicating trigger success/failure is prepared.
8.  Result published to `response_topic` (if provided).
9.  Returns to loop.

### Configuration

Primarily configured via environment variables (see `README.md`). `BLE_ENABLED` and `USE_GATEWAY` determine the operating mode at startup.

## 3. ESP32 Firmware (`src/`)

(Remains the same as previous version, describing its role in MQTT Gateway mode for both sending and scanning).

## 4. Communication Protocols

### MQTT

*   **Service Input:**
    *   Listens on `MQTT_REQUEST_TOPIC` for JSON image send requests.
    *   Listens on `MQTT_SCAN_REQUEST_TOPIC` for JSON scan requests.
*   **Service Output (Gateway Mode - Send):** Publishes `start` command (JSON payload with `total_packets`) to `{MQTT_GATEWAY_BASE_TOPIC}/display/{MAC}/command/start`. Waits for the gateway to publish `connected_ble` status (relayed via the service status topic). Once ready, publishes all `packet` commands (raw hex payload) sequentially to `{MQTT_GATEWAY_BASE_TOPIC}/display/{MAC}/command/packet` using QoS 1. Does not send an `end` command. This improves reliability by ensuring the gateway is connected before sending bulk data and leveraging MQTT ordering for packets.
*   **Service Output (Gateway Mode - Scan):** Publishes trigger command to `{MQTT_GATEWAY_BASE_TOPIC}/bridge/command/scan`.
*   **Service Output (Status/Results):** Publishes JSON status/results to `MQTT_DEFAULT_STATUS_TOPIC` and optionally to the `response_topic` provided in the request.
*   **ESP32 Input:** Subscribes to `{MQTT_GATEWAY_BASE_TOPIC}/display/+/command/start` and `{MQTT_GATEWAY_BASE_TOPIC}/display/+/command/packet` (plus scan command). Parses `total_packets` from the `start` command. Receives packets sequentially on the `packet` topic. Determines transfer completion based on receiving the expected number of packets or an internal packet receive timeout (to handle potential packet loss).
*   **ESP32 Output:** Publishes display status updates to `{MQTT_GATEWAY_BASE_TOPIC}/display/{MAC}/status`, bridge status to `{MQTT_GATEWAY_BASE_TOPIC}/bridge/status`, and scan results to `{MQTT_GATEWAY_BASE_TOPIC}/bridge/scan_result`.

### BLE Protocol (E-Ink Display)

Handled either directly by the Python service (`BleCommunicator` for sending, `BleakScanner` for scanning) or by the ESP32 firmware. Data formatting by Python service.

## 5. CLI Scripts

*   **`send_image_cli.py`:** Publishes image send requests to `MQTT_REQUEST_TOPIC`. Can optionally listen for results on a specified response topic.
*   **`scan_ble_cli.py`:** Publishes scan requests to `MQTT_SCAN_REQUEST_TOPIC`. Listens for results on *both* the service's status topic (`MQTT_DEFAULT_STATUS_TOPIC`) and the ESP32's scan result topic (`{MQTT_GATEWAY_BASE_TOPIC}/bridge/scan_result`).