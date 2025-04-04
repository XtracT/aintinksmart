#include <PubSubClient.h>
#include <Arduino.h> // For String, Serial, etc.
#include <NimBLEDevice.h> // For NimBLEAddress
#include <queue>          // For packetQueue
#include <vector>         // For packetQueue
#include <string>         // For std::string
#include <algorithm>      // For std::transform
#include <exception>      // For std::exception

#include "config.h"
#include "globals.h"
#include "mqtt_utils.h"
#include "ble_utils.h" // For disconnectBLE
#include "scan_utils.h" // For performBleScanAndReport
// Include other necessary headers, e.g., for hexStringToBytes if moved elsewhere
#include "utils.h" // Assuming hexStringToBytes will be moved here

// --- MQTT Connection ---
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
        bool sub_end = mqttClient.subscribe(MQTT_END_TOPIC.c_str());
        bool sub_scan = mqttClient.subscribe(MQTT_SCAN_COMMAND_TOPIC.c_str()); // Subscribe to scan command
        if (sub_start && sub_packet && sub_end && sub_scan) {
             Serial.println("Subscribed to wildcard command topics:");
             Serial.print(" - "); Serial.println(MQTT_START_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_PACKET_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_END_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_SCAN_COMMAND_TOPIC);
        } else {
            Serial.println("Subscription failed!");
        }
        publishStatus("idle", ""); // Report initial idle status (no specific target MAC)
    } else {
        Serial.print(" failed, rc="); Serial.print(mqttClient.state());
        Serial.println(" Retrying in 5 seconds...");
        // Don't block here, loop will retry
    }
}

// Helper function to extract MAC from topic
// Topic format: aintinksmart/gateway/display/AABBCCDDEEFF/command/start
// Returns MAC with colons, or empty string if invalid
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
    // Basic validation (ensure it looks like hex) - could be more robust
    for (char c : formattedMac) {
         if (!isxdigit(c) && c != ':') return "";
    }
    // Convert to uppercase for consistency
    std::transform(formattedMac.begin(), formattedMac.end(), formattedMac.begin(), ::toupper);
    return formattedMac;
}


// --- MQTT Message Callback ---
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    payload[length] = '\0'; // Null-terminate payload
    String topicStr = String(topic);
    // Check based on the new structure
    bool isPacket = topicStr.indexOf("/display/") != -1 && topicStr.endsWith("/command/packet");

    // Only print the full arrival message for non-packet commands to avoid serial clutter/corruption
    if (!isPacket) {
        Serial.print("Message arrived ["); Serial.print(topic); Serial.print("] ");
    }

    // First, check for the specific scan command topic which doesn't have a MAC
    if (topicStr.equals(MQTT_SCAN_COMMAND_TOPIC)) {
         if (!isPacket) Serial.println(); // End the "Message arrived" line if printed
         Serial.println("Received SCAN command.");
         // Check if transfer is in progress, maybe defer scan?
         if (transferInProgress) {
             Serial.println(" -> Transfer in progress. Scan deferred/ignored for now.");
             // Optionally publish a "busy_transfer" status?
             // publishStatus("busy_transfer", "");
         } else {
             performBleScanAndReport();
         }
         return; // Handled scan command, exit callback
    }

    // For all other commands, extract the MAC address
    std::string formattedMac = extractMacFromTopic(topic);
    if (formattedMac.empty()) {
        if (!isPacket) Serial.println(); // End the "Message arrived" line if printed
        Serial.println(" -> Ignoring message on invalid topic format (or not scan command).");
        return;
    }
    Serial.print(" -> Target MAC: "); Serial.print(formattedMac.c_str());

    // Reset inactivity timer only if message is for the active transfer or a new start command
    bool isStartCommand = topicStr.endsWith("/command/start");
    if (isStartCommand || (transferInProgress && formattedMac == currentTargetMac)) {
         lastActionTime = millis();
         Serial.print(" (Timer Reset)");
    }
     // End initial log line only if it was started (and wasn't scan command)
     if (!isPacket) {
         Serial.println();
     }


    // Check based on the new structure
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

        // --- Start new transfer ---
        currentTargetMac = formattedMac; // Store the target MAC for this transfer
        Serial.printf(" -> Starting transfer for %s\n", currentTargetMac.c_str());

        // Attempt to create NimBLEAddress for validation
        try {
             // NimBLEAddress constructor might throw on invalid format
             currentTargetAddress = NimBLEAddress(currentTargetMac, BLE_ADDR_PUBLIC); // Use std::string constructor + type
             // Check if the address is valid (optional, NimBLEAddress might handle internally)
             // if (!currentTargetAddress.isValid()) { ... }
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


        // Clear queue and reset counters
        std::queue<std::vector<uint8_t>> empty;
        std::swap(packetQueue, empty);
        packetsReceivedCount = 0;
        endCommandReceived = false; // Reset flag on new transfer
        packetsWrittenCount = 0;
        transferAborted = false; // Reset abort flag for new transfer
        bleConnectRetries = 0; // Reset retry counter for new transfer

        transferInProgress = true; // Set flag AFTER validation and state reset
        publishStatus("starting", currentTargetMac);

        // Attempt initial connection immediately
        // connectBLE now takes the target MAC
        if (!bleConnected) connectBLE(currentTargetMac); // Pass MAC

    // Check based on the new structure
    } else if (isPacket) { // Reuse the check from above
        if (!transferInProgress || formattedMac != currentTargetMac) {
            Serial.println(" -> Warning: Received 'packet' for inactive/wrong transfer. Ignoring.");
            return;
        }
        // Payload is the raw hex string
        std::string hexPacket((char*)payload);
        // Serial.printf("Received PACKET %d: %s\n", packetsReceivedCount + 1, hexPacket.c_str());

        std::vector<uint8_t> packetBytes = hexStringToBytes(hexPacket); // Assumes hexStringToBytes is available
        if (!packetBytes.empty()) {
            packetQueue.push(packetBytes);
            packetsReceivedCount++;
            // Serial.printf("Packet queued. Queue size: %d\n", packetQueue.size());
        } else {
             Serial.println(" -> Error converting hex packet data.");
             publishStatus("error_packet_format", currentTargetMac); // Use the currently active MAC
        }

    // Check based on the new structure
    } else if (topicStr.indexOf("/display/") != -1 && topicStr.endsWith("/command/end")) {
        if (!transferInProgress || formattedMac != currentTargetMac) {
            Serial.println(" -> Warning: Received 'end' for inactive/wrong transfer. Ignoring.");
            return;
        }
        Serial.printf("Received END command after %d packets received.\n", packetsReceivedCount);
        endCommandReceived = true; // Set flag
        publishStatus("ending", currentTargetMac);
        // If queue is already empty when END arrives, finish immediately
        if (packetQueue.empty()) {
            transferInProgress = false; // Loop will handle disconnect
        }
    // Scan command handled above
    } else {
         Serial.println(" -> Ignoring message on unknown command topic suffix.");
    }
}

// Updated publishStatus to accept target MAC and construct topic dynamically
void publishStatus(const char* status, const std::string& targetMac) {
    // Check connection status using the client's state
    if (mqttClient.state() != MQTT_CONNECTED) {
        Serial.printf("MQTT not connected (state: %d), cannot publish status '%s'\n", mqttClient.state(), status);
        return;
    }

    String topic;
    if (!targetMac.empty()) {
        String macPart = targetMac.c_str();
        macPart.replace(":", ""); // Remove colons for topic
        // Use base topic constant defined in globals.cpp
        topic = MQTT_DISPLAY_STATUS_TOPIC_BASE + macPart + "/status";
    } else {
        // Use bridge status topic constant defined in globals.cpp
        topic = MQTT_BRIDGE_STATUS_TOPIC;
        Serial.print("(Publishing general status) ");
    }

    mqttClient.publish(topic.c_str(), status);
    Serial.printf("Status (%s): %s\n", targetMac.empty() ? "general" : targetMac.c_str(), status);
}