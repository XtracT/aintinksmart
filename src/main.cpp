#include <Arduino.h>
#include "config.h"
#include "globals.h"
#include "wifi_utils.h"
#include "mqtt_utils.h"
#include "ble_utils.h"
#include "scan_utils.h"
#include "utils.h"

// Configuration constants moved to config.h
// Global variables moved to globals.h/globals.cpp

// Function declarations moved to respective .h files

// Scan related definitions moved to scan_utils.cpp/scan_utils.h




// --- Setup Function --- (Remains in main.cpp)
void setup() {
    Serial.begin(115200);
    while (!Serial);
    Serial.println("ESP32 E-Ink Bridge Starting (3-Topic Protocol)...");

    // Generate unique MQTT client ID
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    MQTT_CLIENT_ID += mac;
    // MQTT Topics are now defined directly in globals.cpp

    Serial.print("MQTT Client ID: "); Serial.println(MQTT_CLIENT_ID);
    // Log base topics, specific topics are now dynamic or used internally
    // Log the defined topics
    // Base topic is implicitly shown in the topics below
    Serial.println("Subscribing to:");
    Serial.print(" - Start: "); Serial.println(MQTT_START_TOPIC);
    Serial.print(" - Packet: "); Serial.println(MQTT_PACKET_TOPIC);
    // Serial.print(" - End: "); Serial.println(MQTT_END_TOPIC); // Removed
    Serial.print(" - Scan Cmd: "); Serial.println(MQTT_SCAN_COMMAND_TOPIC);
    Serial.println("Publishing to:");
    Serial.print(" - Display Status Base: "); Serial.println(MQTT_DISPLAY_STATUS_TOPIC_BASE);
    Serial.print(" - Bridge Status: "); Serial.println(MQTT_BRIDGE_STATUS_TOPIC);
    Serial.print(" - Scan Result: "); Serial.println(MQTT_SCAN_RESULT_TOPIC);

    connectWiFi();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback); // mqttCallback is now in mqtt_utils.cpp
    mqttClient.setKeepAlive(60); // Increase keepalive to 60 seconds (PubSubClient default is 15s)
    // mqttClient.loop() must be called within this interval. We call it frequently.
    // Increase MQTT buffer size if needed (PubSubClient default is small)
    // mqttClient.setBufferSize(1024); // Example if needed

    Serial.println("Initializing NimBLE...");
    NimBLEDevice::init(""); // Initialize NimBLE subsystem
// Scan parameters are now set within performBleScanAndReport()

    // Initialize BLE UUIDs from config constants
    serviceUUID = NimBLEUUID(BLE_SERVICE_UUID_STR);
    characteristicUUID = NimBLEUUID(BLE_CHARACTERISTIC_UUID_STR);
    // NimBLEDevice::setPower(ESP_PWR_LVL_P9); // Optional
    // Connection timeout is set per-connection attempt on the client

    Serial.println("Setup complete.");
    publishStatus("idle", ""); // Publish initial idle status (no specific target MAC)
}

// --- Main Loop --- (Remains in main.cpp)
void loop() {
    // Ensure WiFi and MQTT connections are maintained
    if (!WiFi.isConnected()) {
        connectWiFi(); // connectWiFi is now in wifi_utils.cpp
    }
    if (!mqttClient.connected()) {
        connectMQTT(); // connectMQTT is now in mqtt_utils.cpp
    }
    mqttClient.loop(); // Process MQTT messages (keepalives, incoming data)

    // --- BLE Transfer Logic ---
    if (transferInProgress) {
        if (transferAborted) return; // Check if transfer was aborted by error

        // 1. Ensure BLE Connection (with retries)
        if (!bleConnected) {
            mqttClient.loop(); // Allow MQTT processing before potential block
            if (!connectBLE(currentTargetMac)) { // connectBLE is now in ble_utils.cpp
                bleConnectRetries++;
                Serial.printf("BLE connection failed (Attempt %d/%d). ", bleConnectRetries, MAX_BLE_CONNECT_RETRIES);
                if (bleConnectRetries >= MAX_BLE_CONNECT_RETRIES) {
                    Serial.println("Max retries reached. Aborting transfer.");
                    publishStatus("error_ble_connect_failed", currentTargetMac); // publishStatus is in mqtt_utils.cpp
                    transferAborted = true;
                    transferInProgress = false; // Signal loop to clean up
                    disconnectBLE(true); // Force disconnect state cleanup (ble_utils.cpp)
                    return;
                } else {
                    Serial.println("Publishing retry status and retrying in 5s...");
                    publishStatus("retrying_ble_connect", currentTargetMac); // Publish retry status
                    delay(5000);
                    mqttClient.loop(); // Allow MQTT processing during delay
                    return; // Skip rest of loop iteration
                }
            } else {
                 bleConnectRetries = 0; // Reset on success
            }
        } else {
             bleConnectRetries = 0; // Reset if already connected
        }

        // 2. Check for Packet Receive Timeout
        // Only check if we have received at least one packet and haven't received the expected count yet
        if (packetsReceivedCount > 0 && packetsReceivedCount < expectedPacketCount) {
             if (millis() - lastActionTime > PACKET_RECEIVE_TIMEOUT_MS) {
                  Serial.printf("Packet receive timeout! Expected %d, got %d. Last packet received > %lums ago.\n",
                                expectedPacketCount, packetsReceivedCount, PACKET_RECEIVE_TIMEOUT_MS);
                  publishStatus("error_packet_timeout", currentTargetMac);
                  transferAborted = true;
                  transferInProgress = false; // Signal loop to clean up
                  disconnectBLE(true); // Force disconnect state cleanup
                  return; // Exit transfer processing
             }
        }

        // 3. Process Packet Queue if Connected
        if (transferAborted) return; // Check again after potential connection attempt
        if (bleConnected && !packetQueue.empty()) {
            std::vector<uint8_t> packet = packetQueue.front();
            mqttClient.loop(); // Allow MQTT processing before potential block
            if (writePacketToBLE(packet)) { // writePacketToBLE is in ble_utils.cpp
                packetQueue.pop();
                packetsWrittenCount++;
                lastActionTime = millis(); // Reset timer on successful write
                // Check if this was the last expected packet based on count
                if (packetsReceivedCount == expectedPacketCount && packetsWrittenCount == expectedPacketCount) {
                    transferInProgress = false; // Mark transfer complete
                    Serial.printf("%d/%d packets received and written.\n", packetsWrittenCount, expectedPacketCount);
                    // Add debug log before publishing final status
                    Serial.printf("DEBUG: Publishing final success. MQTT State: %d\n", mqttClient.state());
                    publishStatus("success", currentTargetMac);
                } else {
                    // Publish "writing" status only once at the start of writing
                    if (!writingStatusPublished) {
                        publishStatus("writing", currentTargetMac);
                        writingStatusPublished = true;
                    }
                    // Optional: Add a less frequent serial log for progress if desired
                    // e.g., log every 10 packets written
                    if (packetsWrittenCount % 10 == 0) {
                         Serial.printf(" -> Wrote packet %d\n", packetsWrittenCount);
                    }
                }
            } else {
                Serial.println("Packet write failed.");
                publishStatus("error_write", currentTargetMac);
                transferAborted = true;
                transferInProgress = false; // Signal loop to clean up
                disconnectBLE(true); // Force disconnect state cleanup
                return;
            }
        }
    } else {
        // --- Cleanup Logic (when transferInProgress is false) ---
        // This block runs once after a transfer completes or is aborted.

        // Disconnect if still connected (e.g., successful completion)
        if (bleConnected) {
             Serial.println("Transfer finished or aborted, disconnecting idle BLE connection.");
             disconnectBLE(false); // Normal disconnect
        }

        // Perform final state cleanup only if a target was active
        // Perform final state cleanup only if a target was active
        if (!currentTargetMac.empty()) {
             expectedPacketCount = 0; // Reset expected count
             Serial.printf(" -> Cleaning up state for completed/aborted transfer: %s\n", currentTargetMac.c_str());
             lastActionTime = 0;
             bleConnectRetries = 0;
             transferAborted = false; // Reset abort flag for next transfer
             writingStatusPublished = false; // Reset writing status flag
             // Clear queue
             std::queue<std::vector<uint8_t>> empty;
             std::swap(packetQueue, empty);
             // Clear the target MAC *last*
             currentTargetMac = "";
             // Publish general idle status
             publishStatus("idle", "");
        }
    }

    delay(10); // Small main loop delay
}
