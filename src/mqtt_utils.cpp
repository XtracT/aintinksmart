#include <PubSubClient.h>
#include <Arduino.h> // For String, Serial, etc.
#include <NimBLEDevice.h> // For NimBLEAddress
#include <queue>          // For packetQueue
#include <vector>         // For packetQueue
#include <string>         // For std::string
#include <algorithm>      // For std::transform
#include <exception>      // For std::exception
#include <ArduinoJson.h>  // For parsing START command payload

#include "config.h"
#include "globals.h"
#include "mqtt_utils.h"
#include "ble_utils.h" // For disconnectBLE
#include "scan_utils.h" // For performBleScanAndReport
#include "utils.h" // For hexStringToBytes

void connectMQTT() {
    if(mqttClient.connected()) return;
    Serial.print("Connecting to MQTT broker...");
    bool connected;
    if (strlen(MQTT_USER) > 0) {
        connected = mqttClient.connect(MQTT_CLIENT_ID.c_str(), MQTT_USER, MQTT_PASSWORD);
    } else {
        connected = mqttClient.connect(MQTT_CLIENT_ID.c_str());
    }

    if (connected) {
        Serial.println(" connected!");
        // Subscribe to command topics
        bool sub_start = mqttClient.subscribe(MQTT_START_TOPIC.c_str());
        bool sub_packet = mqttClient.subscribe(MQTT_PACKET_TOPIC.c_str());
        bool sub_scan = mqttClient.subscribe(MQTT_SCAN_COMMAND_TOPIC.c_str()); // Subscribe to scan command
        if (sub_start && sub_packet && sub_scan) { // Removed sub_end check
             Serial.println("Subscribed to wildcard command topics:");
             Serial.print(" - "); Serial.println(MQTT_START_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_PACKET_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_SCAN_COMMAND_TOPIC);
        } else {
            Serial.println("Subscription failed!");
        }
        publishStatus("idle", ""); // Report initial idle status (no specific target MAC)
    } else {
        Serial.print(" failed, rc="); Serial.print(mqttClient.state());
        Serial.println(" Retrying in 5 seconds...");
        // Don't block here; main loop() handles retries
    }
}

// Extracts MAC address from MQTT topic string.
// Expected Topic format: aintinksmart/gateway/display/AABBCCDDEEFF/...
// Returns MAC with colons (e.g., AA:BB:CC:DD:EE:FF) or empty string if invalid.
std::string extractMacFromTopic(const char* topic) {
    String topicStr = String(topic);
    // Find the relevant slashes for the new structure
    int firstSlash = topicStr.indexOf('/'); // after aintinksmart
    if (firstSlash == -1) return "";
    int secondSlash = topicStr.indexOf('/', firstSlash + 1); // after gateway
    if (secondSlash == -1) return "";
    int thirdSlash = topicStr.indexOf('/', secondSlash + 1); // after display
    if (thirdSlash == -1) return "";
    int fourthSlash = topicStr.indexOf('/', thirdSlash + 1); // after MAC
    if (fourthSlash == -1) return "";

    String macPart = topicStr.substring(thirdSlash + 1, fourthSlash);
    if (macPart.length() != 12) return ""; // Expect 12 hex chars

    // Reconstruct MAC with colons
    std::string formattedMac = "";
    for (int i = 0; i < 12; i += 2) {
        formattedMac += macPart.substring(i, i + 2).c_str();
        if (i < 10) {
            formattedMac += ":";
        }
    }
    // Basic validation (ensure it looks like hex)
    for (char c : formattedMac) {
         if (!isxdigit(c) && c != ':') return "";
    }
    // Convert to uppercase for consistency
    std::transform(formattedMac.begin(), formattedMac.end(), formattedMac.begin(), ::toupper);
    return formattedMac;
}


void mqttCallback(char* topic, byte* payload, unsigned int length) {
    payload[length] = '\0'; // Null-terminate payload
    String topicStr = String(topic);
    bool isPacket = topicStr.indexOf("/display/") != -1 && topicStr.endsWith("/command/packet");

    // Only print full arrival message for non-packet commands to avoid serial clutter
    if (!isPacket) {
        Serial.print("Message arrived ["); Serial.print(topic); Serial.print("] ");
    }

    // Check for scan command topic first (no MAC)
    if (topicStr.equals(MQTT_SCAN_COMMAND_TOPIC)) {
         if (!isPacket) Serial.println(); // End the "Message arrived" line if printed
         Serial.println("Received SCAN command.");
         // Defer scan if image transfer is in progress
         if (transferInProgress) {
             Serial.println(" -> Transfer in progress. Scan deferred/ignored for now.");
             // Optionally publish a "busy_transfer" status? (Not implemented)
         } else {
             performBleScanAndReport();
         }
         return; // Handled scan command, exit callback
    }

    // For display commands, extract the MAC address
    std::string formattedMac = extractMacFromTopic(topic);
    if (formattedMac.empty()) {
        if (!isPacket) Serial.println(); // End the "Message arrived" line if printed
        Serial.println(" -> Ignoring message on invalid topic format (or not scan command).");
        return;
    }
    if (!isPacket) { // Print Target MAC only for START command
         Serial.print(" -> Target MAC: "); Serial.print(formattedMac.c_str());
    }

    // Reset inactivity timer for START or PACKET messages for the active transfer
    bool isStartCommand = topicStr.endsWith("/command/start");
    if (isStartCommand || (transferInProgress && formattedMac == currentTargetMac)) {
         lastActionTime = millis();
    }
     // End the "Message arrived" log line if it was started
     if (!isPacket) {
         Serial.println();
     }


    if (topicStr.indexOf("/display/") != -1 && topicStr.endsWith("/command/start")) {
        Serial.println("Received START command.");
        if (transferInProgress) {
            if (formattedMac != currentTargetMac) {
                 Serial.printf(" -> Warning: Busy with transfer for %s. Ignoring START for %s.\n", currentTargetMac.c_str(), formattedMac.c_str());
                 return; // Ignore START for different MAC if busy
            } else {
                 Serial.println(" -> Warning: Received duplicate START for ongoing transfer. Resetting state.");
                 // Resetting state might be desired if previous transfer stalled
                 disconnectBLE(true); // Force disconnect previous attempt
            }
        }

        // Parse payload to get total_packets
        ArduinoJson::JsonDocument doc; // Use recommended JsonDocument
        ArduinoJson::DeserializationError error = ArduinoJson::deserializeJson(doc, payload, length);
        if (error) {
             Serial.print(" -> ERROR: Failed to parse START JSON: "); Serial.println(error.c_str());
             publishStatus("error_start_format", formattedMac);
             return;
        }
        // Use recommended check: doc["key"].is<T>()
        if (!doc["total_packets"].is<unsigned int>()) {
             Serial.println(" -> ERROR: START JSON missing or invalid 'total_packets'.");
             publishStatus("error_start_format", formattedMac);
             return;
        }
        expectedPacketCount = doc["total_packets"];
        if (expectedPacketCount == 0) {
             Serial.println(" -> ERROR: 'total_packets' cannot be zero.");
             publishStatus("error_start_format", formattedMac);
             return;
        }

        currentTargetMac = formattedMac; // Store the target MAC for this transfer
        Serial.printf(" -> Starting transfer for %s (expecting %d packets)\n", currentTargetMac.c_str(), expectedPacketCount);

        try {
             // NimBLEAddress constructor might throw on invalid format
             currentTargetAddress = NimBLEAddress(currentTargetMac, BLE_ADDR_PUBLIC); // Use std::string constructor + type
        } catch (const std::exception& e) { // Catch potential exceptions from NimBLEAddress constructor
             Serial.printf(" -> ERROR: Invalid MAC address format received: %s. Exception: %s\n", currentTargetMac.c_str(), e.what());
             publishStatus("error_invalid_mac", formattedMac); // Pass the MAC we tried
             currentTargetMac = ""; // Clear invalid target
             return;
        } catch (...) { // Catch any other potential errors
             Serial.printf(" -> ERROR: Unknown error creating NimBLEAddress for %s.\n", currentTargetMac.c_str());
             publishStatus("error_invalid_mac", formattedMac); // Pass the MAC we tried
             currentTargetMac = "";
             return;
        }


        // Reset state for the new transfer
        std::queue<std::vector<uint8_t>> empty;
        std::swap(packetQueue, empty);
        packetsReceivedCount = 0;
        // packetsWrittenCount = 0; // Reset in main loop cleanup
        transferAborted = false; // Reset abort flag for new transfer
        bleConnectRetries = 0; // Reset retry counter for new transfer
        writingStatusPublished = false; // Reset writing status flag

        transferInProgress = true; // Set flag AFTER validation and state reset
        publishStatus("starting", currentTargetMac);

        // Attempt initial BLE connection immediately
        if (!bleConnected) connectBLE(currentTargetMac); // Pass MAC

    } else if (isPacket) {
        if (!transferInProgress || formattedMac != currentTargetMac) {
            Serial.println(" -> Warning: Received 'packet' for inactive/wrong transfer. Ignoring.");
            return;
        }
        std::string hexPacket((char*)payload);

        std::vector<uint8_t> packetBytes = hexStringToBytes(hexPacket);
        if (!packetBytes.empty()) {
            packetQueue.push(packetBytes);
            packetsReceivedCount++;
        } else {
             Serial.println(" -> Error converting hex packet data.");
             publishStatus("error_packet_format", currentTargetMac); // Use the currently active MAC
        }
    // Note: END command is no longer handled here.
    // Note: Scan command is handled earlier.
    } else {
         Serial.println(" -> Ignoring message on unknown command topic suffix.");
    }
}

// Publishes status to the appropriate MQTT topic (display-specific or bridge general).
void publishStatus(const char* status, const std::string& targetMac) {
    // Prevent publishing if MQTT is disconnected
    if (mqttClient.state() != MQTT_CONNECTED) {
        Serial.printf("MQTT not connected (state: %d), cannot publish status '%s'\n", mqttClient.state(), status);
        return;
    }

    String topic;
    if (!targetMac.empty()) {
        String macPart = targetMac.c_str();
        macPart.replace(":", ""); // Remove colons for topic
        // Construct display-specific status topic
        topic = MQTT_DISPLAY_STATUS_TOPIC_BASE + macPart + "/status";
    } else {
        // Use general bridge status topic
        topic = MQTT_BRIDGE_STATUS_TOPIC;
        Serial.print("(Publishing general status) ");
    }

    mqttClient.publish(topic.c_str(), status);
    Serial.printf("Status (%s): %s\n", targetMac.empty() ? "general" : targetMac.c_str(), status);
}