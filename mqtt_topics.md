# Default MQTT Topics (aintinksmart Structure)

This document lists the default MQTT topics used by the BLE E-Ink Sender service and the optional ESP32 firmware gateway, following the unified `aintinksmart/` structure.

## Service Topics (`aintinksmart/service/...`)

These topics handle direct interaction with the main Python service.

*   **`aintinksmart/service/request/send_image`**
    *   **Direction:** Client -> Service
    *   **Function:** Clients publish image sending requests (JSON payload) to this topic. The service listens here.
    *   *Default Value:* `aintinksmart/service/request/send_image`

*   **`aintinksmart/service/request/scan`**
    *   **Direction:** Client -> Service
    *   **Function:** Clients publish scan requests (JSON payload) to this topic. The service listens here.
    *   *Default Value:* `aintinksmart/service/request/scan`

*   **`aintinksmart/service/status/default`**
    *   **Direction:** Service -> Client(s)
    *   **Function:** The service publishes intermediate status updates (e.g., `processing_request`, `connecting_ble`) and the final result (`success` or `error`) for operations to this topic. This includes results from Direct BLE scans. Clients subscribe here to monitor progress.
    *   *Default Value:* `aintinksmart/service/status/default`

## Gateway Topics (`aintinksmart/gateway/...`)

These topics handle communication specifically with the ESP32 gateway device when operating in **MQTT Gateway Mode**.

### Bridge Control/Status (`aintinksmart/gateway/bridge/...`)

Topics for controlling the gateway itself or getting general gateway status/results.

*   **`aintinksmart/gateway/bridge/command/scan`**
    *   **Direction:** Service -> ESP32
    *   **Function:** The service publishes an empty message here to command the ESP32 gateway to perform a BLE scan.
    *   *Default Value:* `aintinksmart/gateway/bridge/command/scan`

*   **`aintinksmart/gateway/bridge/status`**
    *   **Direction:** ESP32 -> Service/Client(s)
    *   **Function:** The ESP32 publishes general status updates about itself (e.g., `idle`, `connecting_wifi`, `online`).
    *   *Default Value:* `aintinksmart/gateway/bridge/status`

*   **`aintinksmart/gateway/bridge/scan_result`**
    *   **Direction:** ESP32 -> Service/Client(s)
    *   **Function:** The ESP32 publishes the results (JSON payload with a list of found devices) after completing a scan triggered via the `.../bridge/command/scan` topic.
    *   *Default Value:* `aintinksmart/gateway/bridge/scan_result`

### Display Control/Status (`aintinksmart/gateway/display/{MAC}/...`)

Topics for controlling or getting status about operations targeting a specific display via the gateway. `{MAC}` is a placeholder for the target device's MAC address without colons (e.g., `AABBCCDDEEFF`).

*   **`aintinksmart/gateway/display/+/command/start`**
    *   **Direction:** Service -> ESP32
    *   **Function:** The service publishes the start command for an image transfer to the specific device identified by the MAC address replacing the `+` wildcard. The ESP32 subscribes to this pattern.
    *   *Subscription Pattern (ESP32):* `aintinksmart/gateway/display/+/command/start`

*   **`aintinksmart/gateway/display/+/command/packet`**
    *   **Direction:** Service -> ESP32
    *   **Function:** The service publishes individual image data packets (hex string) for the target device.
    *   *Subscription Pattern (ESP32):* `aintinksmart/gateway/display/+/command/packet`

*   **~~`aintinksmart/gateway/display/+/command/end`~~** (Removed)
    *   *Function:* This command is no longer used. The gateway determines completion based on the packet count received in the `start` command payload and an internal timeout.

*   **`aintinksmart/gateway/display/{MAC}/status`**
    *   **Direction:** ESP32 -> Service/Client(s)
    *   **Function:** The ESP32 publishes status updates specific to the ongoing image transfer for the given device (e.g., `starting`, `writing`, `ble_connected`, `error_connect`, `complete`).
    *   *Publish Topic Example (ESP32):* `aintinksmart/gateway/display/AABBCCDDEEFF/status`