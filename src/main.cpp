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
    // Initialize MQTT topics (using constants from config.h)
    MQTT_START_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/start";
    MQTT_PACKET_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/packet";
    MQTT_END_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/end";
    MQTT_SCAN_COMMAND_TOPIC = MQTT_COMMAND_TOPIC_BASE + "scan/command";
    MQTT_SCAN_RESULT_TOPIC = MQTT_STATUS_TOPIC_BASE + "scan/result";

    Serial.print("MQTT Client ID: "); Serial.println(MQTT_CLIENT_ID);
    // Log base topics, specific topics are now dynamic or used internally
    Serial.print("MQTT Command Topic Base: "); Serial.println(MQTT_COMMAND_TOPIC_BASE);
    Serial.print("MQTT Status Topic Base: "); Serial.println(MQTT_STATUS_TOPIC_BASE);
    Serial.print("MQTT Scan Command Topic: "); Serial.println(MQTT_SCAN_COMMAND_TOPIC);
    Serial.print("MQTT Scan Result Topic: "); Serial.println(MQTT_SCAN_RESULT_TOPIC);

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
                    Serial.println("Retrying in 5s...");
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

        // 2. Process Packet Queue if Connected
        if (transferAborted) return; // Check again after potential connection attempt
        if (bleConnected && !packetQueue.empty()) {
            std::vector<uint8_t> packet = packetQueue.front();
            mqttClient.loop(); // Allow MQTT processing before potential block
            if (writePacketToBLE(packet)) { // writePacketToBLE is in ble_utils.cpp
                packetQueue.pop();
                packetsWrittenCount++;
                lastActionTime = millis(); // Reset timer on successful write
                if (packetQueue.empty() && endCommandReceived) {
                    transferInProgress = false; // Mark transfer complete
                    Serial.println("All queued packets sent after END command.");
                    publishStatus("complete", currentTargetMac);
                } else {
                    publishStatus("writing", currentTargetMac);
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
        if (!currentTargetMac.empty()) {
             Serial.printf(" -> Cleaning up state for completed/aborted transfer: %s\n", currentTargetMac.c_str());
             endCommandReceived = false;
             lastActionTime = 0;
             bleConnectRetries = 0;
             transferAborted = false; // Reset abort flag for next transfer
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
