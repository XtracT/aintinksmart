#include <Arduino.h>
#include "config.h"
#include "globals.h"
#include "wifi_utils.h"
#include "mqtt_utils.h"
#include "ble_utils.h"
#include "scan_utils.h"
#include "utils.h"





// --- Setup Function ---
void setup() {
    Serial.begin(115200);
    while (!Serial);
    Serial.println("ESP32 E-Ink Bridge Starting...");

    // Generate unique MQTT client ID
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    MQTT_CLIENT_ID += mac;

    Serial.print("MQTT Client ID: "); Serial.println(MQTT_CLIENT_ID);
    // Log defined topics for debugging
    Serial.println("Subscribing to:");
    Serial.print(" - Start: "); Serial.println(MQTT_START_TOPIC);
    Serial.print(" - Packet: "); Serial.println(MQTT_PACKET_TOPIC);
    Serial.print(" - Scan Cmd: "); Serial.println(MQTT_SCAN_COMMAND_TOPIC);
    Serial.println("Publishing to:");
    Serial.print(" - Display Status Base: "); Serial.println(MQTT_DISPLAY_STATUS_TOPIC_BASE);
    Serial.print(" - Bridge Status: "); Serial.println(MQTT_BRIDGE_STATUS_TOPIC);
    Serial.print(" - Scan Result: "); Serial.println(MQTT_SCAN_RESULT_TOPIC);

    connectWiFi();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setKeepAlive(60); // Increase keepalive to 60 seconds (PubSubClient default is 15s)
    // MQTT buffer size can be increased via build_flags in platformio.ini if needed

    Serial.println("Initializing NimBLE...");
    NimBLEDevice::init(""); // Initialize NimBLE subsystem

    serviceUUID = NimBLEUUID(BLE_SERVICE_UUID_STR);
    characteristicUUID = NimBLEUUID(BLE_CHARACTERISTIC_UUID_STR);
    // NimBLEDevice::setPower(ESP_PWR_LVL_P9); // Optional: Adjust BLE transmit power
    // BLE connection timeout is handled internally by NimBLE client connect()

    Serial.println("Setup complete.");
    publishStatus("idle", ""); // Publish initial idle status
}

// --- Main Loop ---
void loop() {
    if (!WiFi.isConnected()) {
        connectWiFi();
    }
    if (!mqttClient.connected()) {
        connectMQTT();
    }
    mqttClient.loop(); // Process MQTT messages

    // --- BLE Transfer Logic ---
    if (transferInProgress) {
        if (transferAborted) return; // Exit loop iteration if transfer aborted

        // 1. Ensure BLE Connection
        if (!bleConnected) {
            mqttClient.loop(); // Allow MQTT processing during potential BLE block
            if (!connectBLE(currentTargetMac)) {
                bleConnectRetries++;
                Serial.printf("BLE connection failed (Attempt %d/%d). ", bleConnectRetries, MAX_BLE_CONNECT_RETRIES);
                if (bleConnectRetries >= MAX_BLE_CONNECT_RETRIES) {
                    Serial.println("Max retries reached. Aborting transfer.");
                    publishStatus("error_ble_connect_failed", currentTargetMac);
                    transferAborted = true;
                    transferInProgress = false; // Signal loop to cleanup
                    disconnectBLE(true); // Force disconnect state cleanup
                    return;
                } else {
                    Serial.println("Publishing retry status and retrying in 5s...");
                    publishStatus("retrying_ble_connect", currentTargetMac);
                    delay(5000);
                    mqttClient.loop(); // Allow MQTT processing during retry delay
                    return; // Skip rest of loop iteration to retry connection
                }
            } else {
                 bleConnectRetries = 0; // Reset retry count on successful connection
            }
        } else {
             bleConnectRetries = 0; // Reset retry count if already connected
        }

        // 2. Check for Packet Receive Timeout
        // Check only if transfer has started and isn't complete yet
        if (packetsReceivedCount > 0 && packetsReceivedCount < expectedPacketCount) {
             if (millis() - lastActionTime > PACKET_RECEIVE_TIMEOUT_MS) {
                  Serial.printf("Packet receive timeout! Expected %d, got %d. Last packet received > %lums ago.\n",
                                expectedPacketCount, packetsReceivedCount, PACKET_RECEIVE_TIMEOUT_MS);
                  publishStatus("error_packet_timeout", currentTargetMac);
                  transferAborted = true;
                  transferInProgress = false; // Signal loop to cleanup
                  disconnectBLE(true); // Force disconnect state cleanup
                  return; // Exit this loop iteration; cleanup happens next
             }
        }

        // 3. Process Packet Queue
        if (transferAborted) return; // Check again after connection attempt
        if (bleConnected && !packetQueue.empty()) {
            std::vector<uint8_t> packet = packetQueue.front();
            mqttClient.loop(); // Allow MQTT processing during potential BLE block
            if (writePacketToBLE(packet)) {
                packetQueue.pop();
                packetsWrittenCount++;
                lastActionTime = millis(); // Update last activity time on successful write
                // Check if this was the last expected packet based on count
                if (packetsReceivedCount == expectedPacketCount && packetsWrittenCount == expectedPacketCount) {
                    transferInProgress = false; // Mark transfer as complete
                    Serial.printf("%d/%d packets received and written.\n", packetsWrittenCount, expectedPacketCount);
                    publishStatus("success", currentTargetMac);
                } else {
                    // Publish "writing" status only once
                    if (!writingStatusPublished) {
                        publishStatus("writing", currentTargetMac);
                        writingStatusPublished = true;
                    }
                    // Optional: Log progress less frequently
                    if (packetsWrittenCount > 0 && packetsWrittenCount % 10 == 0) {
                         Serial.printf(" -> Wrote packet %d\n", packetsWrittenCount);
                    }
                }
            } else {
                Serial.println("Packet write failed.");
                publishStatus("error_write", currentTargetMac);
                transferAborted = true;
                transferInProgress = false; // Signal loop to cleanup
                disconnectBLE(true); // Force disconnect state cleanup
                return; // Exit this loop iteration; cleanup happens next
            }
        }
    } else {
        // --- Cleanup Logic (when transferInProgress is false) ---
        // Runs once after transferInProgress becomes false (completion or abort)

        // Ensure BLE is disconnected
        if (bleConnected) {
             Serial.println("Transfer finished or aborted, disconnecting idle BLE connection.");
             disconnectBLE(false); // Attempt normal disconnect
        }

        // Cleanup state if a transfer was active
        if (!currentTargetMac.empty()) {
             expectedPacketCount = 0; // Reset expected count
             Serial.printf(" -> Cleaning up state for completed/aborted transfer: %s\n", currentTargetMac.c_str());
             lastActionTime = 0;
             bleConnectRetries = 0;
             packetsWrittenCount = 0; // Reset written count
             transferAborted = false; // Reset abort flag
             writingStatusPublished = false; // Reset writing status flag
             std::queue<std::vector<uint8_t>> empty;
             std::swap(packetQueue, empty);
             // Clear target MAC *last* after using it for logs/status
             currentTargetMac = "";
             // Publish general 'idle' status for the bridge
             publishStatus("idle", "");
        }
    }

    delay(10); // Prevent tight loop/watchdog issues
}
