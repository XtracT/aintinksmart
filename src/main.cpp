#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <NimBLEDevice.h>
#include <vector>
#include <queue>
#include <string> // Required for std::string, std::stoul

// --- Configuration Placeholders ---
// WiFi Credentials
const char* WIFI_SSID = "lookmanowires"; // <<< SET YOUR WIFI SSID
const char* WIFI_PASSWORD = "This is WiFi PassWord"; // <<< SET YOUR WIFI PASSWORD

// MQTT Broker Configuration
const char* MQTT_BROKER = "192.168.1.118"; // <<< SET YOUR MQTT BROKER IP/HOSTNAME
const int MQTT_PORT = 1883;
const char* MQTT_USER = ""; // <<< SET MQTT USERNAME (or leave empty)
const char* MQTT_PASSWORD = ""; // <<< SET MQTT PASSWORD (or leave empty)
String MQTT_CLIENT_ID = "esp32-eink-bridge-"; // Unique client ID (MAC added in setup)
String MQTT_COMMAND_TOPIC_BASE = "eink_display/"; // Base topic part
String MQTT_STATUS_TOPIC_BASE = "eink_display/";  // Base topic part
String MQTT_START_TOPIC = "";   // Full topic set in setup
String MQTT_PACKET_TOPIC = "";  // Full topic set in setup
String MQTT_END_TOPIC = "";     // Full topic set in setup
String MQTT_STATUS_TOPIC = "";  // Full topic set in setup

// BLE Target Configuration
// const char* BLE_TARGET_MAC = "44:00:00:0A:91:40"; // <<< REMOVED - Now dynamic
const char* BLE_SERVICE_UUID_STR = "00001523-1212-efde-1523-785feabcd123"; // <<< VERIFY THIS SERVICE UUID
const char* BLE_CHARACTERISTIC_UUID_STR = "00001525-1212-efde-1523-785feabcd123";

// --- Global Variables ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// NimBLEAddress targetAddress(std::string(BLE_TARGET_MAC), BLE_ADDR_PUBLIC); // REMOVED - Now dynamic
NimBLEUUID serviceUUID(BLE_SERVICE_UUID_STR);
NimBLEUUID characteristicUUID(BLE_CHARACTERISTIC_UUID_STR);

// Dynamic Target State
std::string currentTargetMac = ""; // MAC address of the device currently being handled (e.g., "AA:BB:CC:DD:EE:FF")
NimBLEAddress currentTargetAddress; // BLE address object for the current target

NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pRemoteCharacteristic = nullptr;
bool bleConnected = false;
bool transferInProgress = false; // Flag to manage connection state and packet queuing
unsigned long lastActionTime = 0; // For inactivity timeout
// const unsigned long TRANSFER_TIMEOUT_MS = 30000; // REMOVED - Replaced by retry mechanism
const int MAX_BLE_CONNECT_RETRIES = 4; // Max attempts to connect before failing transfer
bool endCommandReceived = false; // Flag to indicate END command was received
bool transferAborted = false; // Flag to signal immediate stop within loop iteration

// Packet Queue
std::queue<std::vector<uint8_t>> packetQueue;
int packetsReceivedCount = 0;
int packetsWrittenCount = 0;
int bleConnectRetries = 0; // Counter for BLE connection attempts

// --- Function Declarations ---
void connectWiFi();
void connectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
bool connectBLE(const std::string& targetMac); // Add targetMac param
void disconnectBLE(bool force = false);
bool writePacketToBLE(const std::vector<uint8_t>& packetData);
std::vector<uint8_t> hexStringToBytes(const std::string& hex);
void publishStatus(const char* status, const std::string& targetMac = ""); // Add targetMac param with default

// --- Setup Function ---
void setup() {
    Serial.begin(115200);
    while (!Serial);
    Serial.println("ESP32 E-Ink Bridge Starting (3-Topic Protocol)...");

    // Generate unique MQTT client ID and topics
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    MQTT_CLIENT_ID += mac;
    // Construct wildcard command topics
    MQTT_START_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/start";
    MQTT_PACKET_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/packet";
    MQTT_END_TOPIC = MQTT_COMMAND_TOPIC_BASE + "+/command/end";
    // Status topic base remains, full topic constructed dynamically in publishStatus

    Serial.print("MQTT Client ID: "); Serial.println(MQTT_CLIENT_ID);
    Serial.print("MQTT Start Topic: "); Serial.println(MQTT_START_TOPIC);
    Serial.print("MQTT Packet Topic: "); Serial.println(MQTT_PACKET_TOPIC);
    Serial.print("MQTT End Topic: "); Serial.println(MQTT_END_TOPIC);
    Serial.print("MQTT Status Topic Base: "); Serial.println(MQTT_STATUS_TOPIC_BASE);

    connectWiFi();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setKeepAlive(60); // Increase keepalive to 60 seconds (PubSubClient default is 15s)
    // mqttClient.loop() must be called within this interval. We call it frequently.
    // Increase MQTT buffer size if needed (PubSubClient default is small)
    // mqttClient.setBufferSize(1024); // Example if needed

    Serial.println("Initializing NimBLE...");
    NimBLEDevice::init("");
    // NimBLEDevice::setPower(ESP_PWR_LVL_P9); // Optional
    // Connection timeout is set per-connection attempt on the client

    Serial.println("Setup complete.");
    publishStatus("idle", ""); // Publish initial idle status (no specific target MAC)
}

// --- Main Loop ---
void loop() {
    if (!WiFi.isConnected()) {
        connectWiFi(); // Handles reconnecting WiFi
    }
    if (!mqttClient.connected()) {
        connectMQTT(); // Handles reconnecting MQTT
    }
    mqttClient.loop(); // Process MQTT messages

    // --- BLE Transfer Logic ---
    if (transferInProgress) {
        // REMOVED Inactivity Timeout Check - Replaced by connection retry logic below

        // If transfer is active, ensure BLE is connected
        if (transferAborted) return; // Don't proceed if aborted in this iteration

        if (!bleConnected) {
            mqttClient.loop(); // Process MQTT just before potentially blocking BLE connect
            if (!connectBLE(currentTargetMac)) {
                // Connection failed
                bleConnectRetries++;
                Serial.printf("BLE connection failed (Attempt %d/%d). ", bleConnectRetries, MAX_BLE_CONNECT_RETRIES);
                if (bleConnectRetries >= MAX_BLE_CONNECT_RETRIES) { // Use >= to correctly limit to MAX_BLE_CONNECT_RETRIES attempts
                    Serial.println("Max retries reached. Aborting transfer.");
                    publishStatus("error_ble_connect_failed", currentTargetMac);
                    transferAborted = true;
                    transferInProgress = false;
                    disconnectBLE(true); // Force disconnect state cleanup
                    return; // Exit loop iteration
                } else {
                    Serial.println("Retrying in 5s...");
                    delay(5000); // Wait longer (5s) before retrying
                    mqttClient.loop(); // Allow MQTT processing during delay
                    return; // Skip packet processing for this iteration
                }
            } else {
                 // Connection successful
                 bleConnectRetries = 0; // Reset counter on successful connection
            }
        } else {
             // Already connected, ensure retry counter is reset
             bleConnectRetries = 0;
        }

        // If connected and packets are waiting, process one
        if (transferAborted) return; // Don't proceed if aborted in this iteration
        if (bleConnected && !packetQueue.empty()) {
            std::vector<uint8_t> packet = packetQueue.front();
            mqttClient.loop(); // Process MQTT just before potentially blocking BLE write
            if (writePacketToBLE(packet)) {
                packetQueue.pop(); // Remove packet only if write succeeded
                packetsWrittenCount++;
                // Serial.printf("Packet %d written. Queue size: %d\n", packetsWrittenCount, packetQueue.size());
                // publishStatus("writing"); // Status is now handled by start/end/complete
                lastActionTime = millis(); // Reset timeout timer on successful write
                // Check if this was the last packet AND the end command was received
                if (packetQueue.empty() && endCommandReceived) {
                    transferInProgress = false; // Mark transfer as complete
                    Serial.println("All queued packets sent after END command.");
                    publishStatus("complete", currentTargetMac); // Publish completion status
                } else {
                    publishStatus("writing", currentTargetMac); // Still writing packets
                }
            } else {
                Serial.println("Packet write failed. Will retry connection/write.");
                publishStatus("error_write", currentTargetMac);
                transferAborted = true; // Signal abort
                disconnectBLE(true); // Disconnect on write failure
                transferInProgress = false; // Mark transfer as failed/stopped
                return; // Exit loop iteration immediately after write failure handling
                // Packet remains in queue to be retried
                delay(500); // Wait before retrying
                mqttClient.loop(); // Allow MQTT processing during delay
            }
        }
    } else {
        // Transfer is NOT in progress (transferInProgress == false)
        // This block executes once after transferInProgress becomes false (due to completion, timeout, or error)
        // We need to ensure cleanup happens regardless of bleConnected state at this exact moment.

        // Check if we *were* connected and need to disconnect now.
        if (bleConnected) {
             Serial.println("Transfer finished or aborted, disconnecting idle BLE connection.");
             disconnectBLE(false); // Normal disconnect, force=false
        }

        // Perform cleanup if the target MAC is still set (meaning the transfer ended)
        if (!currentTargetMac.empty()) {
             Serial.printf(" -> Cleaning up state for completed/aborted transfer: %s\n", currentTargetMac.c_str());
             // Reset flags for next transfer
             endCommandReceived = false;
             lastActionTime = 0; // Reset timer
             bleConnectRetries = 0; // Reset retry counter
             // Clear queue
             std::queue<std::vector<uint8_t>> empty;
             std::swap(packetQueue, empty);
             // Clear the target MAC *here* after all actions related to it are done
             currentTargetMac = "";
             // Publish general idle status
             publishStatus("idle", "");
        }
        // If currentTargetMac was already empty (e.g., initial state), do nothing here.
    }

    delay(10); // Small delay
}

// --- WiFi Connection ---
void connectWiFi() {
    if(WiFi.isConnected()) return;
    Serial.print("Connecting to WiFi ");
    Serial.print(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
        retries++;
        if (retries > 30) { // Increased retries
            Serial.println("\nWiFi connection failed, restarting...");
            ESP.restart();
        }
    }
    Serial.println("\nWiFi connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
}

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
        if (sub_start && sub_packet && sub_end) {
             Serial.println("Subscribed to wildcard command topics:");
             Serial.print(" - "); Serial.println(MQTT_START_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_PACKET_TOPIC);
             Serial.print(" - "); Serial.println(MQTT_END_TOPIC);
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
// Topic format: eink_display/AABBCCDDEEFF/command/start
// Returns MAC with colons, or empty string if invalid
std::string extractMacFromTopic(const char* topic) {
    String topicStr = String(topic);
    int firstSlash = topicStr.indexOf('/');
    if (firstSlash == -1) return "";
    int secondSlash = topicStr.indexOf('/', firstSlash + 1);
    if (secondSlash == -1) return "";

    String macPart = topicStr.substring(firstSlash + 1, secondSlash);
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
    bool isPacket = topicStr.endsWith("/command/packet");

    // Only print the full arrival message for non-packet commands to avoid serial clutter/corruption
    if (!isPacket) {
        Serial.print("Message arrived ["); Serial.print(topic); Serial.print("] ");
    }

    // Extract MAC address from the topic
    std::string formattedMac = extractMacFromTopic(topic);
    if (formattedMac.empty()) {
        Serial.println(" -> Ignoring message on invalid topic format.");
        return;
    }
    Serial.print(" -> Target MAC: "); Serial.print(formattedMac.c_str());

    // Reset inactivity timer only if message is for the active transfer or a new start command
    bool isStartCommand = topicStr.endsWith("/command/start");
    if (isStartCommand || (transferInProgress && formattedMac == currentTargetMac)) {
         lastActionTime = millis();
         Serial.print(" (Timer Reset)");
    }
     // End initial log line only if it was started
     if (!isPacket) {
         Serial.println();
     }


    if (topicStr.endsWith("/command/start")) {
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

    } else if (topicStr.endsWith("/command/packet")) {
        if (!transferInProgress || formattedMac != currentTargetMac) {
            Serial.println(" -> Warning: Received 'packet' for inactive/wrong transfer. Ignoring.");
            return;
        }
        // Payload is the raw hex string
        std::string hexPacket((char*)payload);
        // Serial.printf("Received PACKET %d: %s\n", packetsReceivedCount + 1, hexPacket.c_str());

        std::vector<uint8_t> packetBytes = hexStringToBytes(hexPacket);
        if (!packetBytes.empty()) {
            packetQueue.push(packetBytes);
            packetsReceivedCount++;
            // Serial.printf("Packet queued. Queue size: %d\n", packetQueue.size());
        } else {
             Serial.println(" -> Error converting hex packet data.");
             publishStatus("error_packet_format", currentTargetMac); // Use the currently active MAC
        }

    } else if (topicStr.endsWith("/command/end")) {
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
    } else {
         Serial.println(" -> Ignoring message on unknown command topic suffix.");
    }
}

// --- BLE Functions ---
// Updated connectBLE to accept target MAC
bool connectBLE(const std::string& targetMac) {
    if (bleConnected) return true;

    // Use the targetMac passed as argument
    Serial.print("Attempting BLE connection to "); Serial.println(targetMac.c_str());
    publishStatus("connecting_ble", targetMac); // Pass MAC to status

    // Create client if it doesn't exist
    if (!pClient) {
        pClient = NimBLEDevice::createClient();
        if (!pClient) {
            Serial.println("Failed to create BLE client");
            publishStatus("error_ble_client", targetMac); // Pass MAC to status
            return false;
        }
        // Optional: Set connection parameters
        // pClient->setConnectionParams(12,12,0,51);
    }

    // Check if already connected
    if (pClient->isConnected()) {
         Serial.println("Client already connected (state mismatch). Forcing disconnect first.");
         pClient->disconnect();
         delay(100); // Short delay after disconnect
    }

    // Initiate connection
    // Use currentTargetAddress which should have been set by mqttCallback
    // Set connection timeout (e.g., 10 seconds)
    if (!pClient->connect(currentTargetAddress, false, 10000)) { // address, is_initiator, timeout_ms
        Serial.println("Connection failed");
        // Don't delete client here, allow retry in main loop
        publishStatus("error_ble_connect", targetMac); // Pass MAC to status
        return false;
    }
    Serial.println("BLE Connected!");

    // Get service
    NimBLERemoteService* pService = pClient->getService(serviceUUID);
    if (!pService) {
        Serial.print("Failed to find service UUID: "); Serial.println(serviceUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_service", targetMac); // Pass MAC to status
        return false;
    }
    Serial.print("Found service: "); Serial.println(serviceUUID.toString().c_str());

    // Get characteristic
    pRemoteCharacteristic = pService->getCharacteristic(characteristicUUID);
    if (!pRemoteCharacteristic) {
        Serial.print("Failed to find characteristic UUID: "); Serial.println(characteristicUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_char", targetMac); // Pass MAC to status
        return false;
    }
    Serial.print("Found characteristic: "); Serial.println(characteristicUUID.toString().c_str());

    bleConnected = true;
    publishStatus("connected_ble", targetMac); // Pass MAC to status
    return true;
}

void disconnectBLE(bool force) {
    if (pClient && (pClient->isConnected() || force)) {
        Serial.println("Disconnecting BLE...");
        pClient->disconnect();
    }
    // Don't delete the client object itself unless absolutely necessary
    // NimBLEDevice::deleteClient(pClient);
    // pClient = nullptr;
    bleConnected = false;
    pRemoteCharacteristic = nullptr;
    // Clear target MAC only if the transfer is truly finished or aborted by timeout/completion,
    // NOT if we are forcing a disconnect due to a write error during an ongoing transfer where a retry might happen.
    // The main loop's cleanup logic handles the final clearing when transferInProgress becomes false.
    // We only clear here if force=false (meaning normal completion disconnect)
    // We no longer clear currentTargetMac here.
    // The main loop() cleanup logic handles this reliably after transferInProgress becomes false.
    // Remove status publish from here, let loop() handle it.
}

bool writePacketToBLE(const std::vector<uint8_t>& packetData) {
    if (!bleConnected || !pRemoteCharacteristic) {
        Serial.println("BLE write failed: Not connected or characteristic invalid.");
        return false;
    }

    // Check if characteristic supports write without response
    bool needsResponse = !pRemoteCharacteristic->canWriteNoResponse();
    // Serial.printf("Writing packet %d (%d bytes, Response:%s)... ", packetsWrittenCount + 1, packetData.size(), needsResponse ? "Yes" : "No");

    bool success = pRemoteCharacteristic->writeValue(packetData.data(), packetData.size(), needsResponse);

    if (success) {
        // Serial.println("OK.");
        delay(20); // Crucial delay after successful write
        return true;
    } else {
        // Serial.println("FAILED!");
        return false;
    }
}

// --- Helper Functions ---
std::vector<uint8_t> hexStringToBytes(const std::string& hex) {
    std::vector<uint8_t> bytes;
    if (hex.length() % 2 != 0) {
        Serial.println("Error: Hex string must have an even number of digits.");
        return bytes;
    }
    for (unsigned int i = 0; i < hex.length(); i += 2) {
        std::string byteString = hex.substr(i, 2);
        try {
            // Use strtoul for robust conversion
            unsigned long val = std::strtoul(byteString.c_str(), nullptr, 16);
            if (val > 255) { // Check if value fits in uint8_t
                 throw std::out_of_range("Hex value out of range for uint8_t");
            }
            bytes.push_back(static_cast<uint8_t>(val));
        } catch (const std::invalid_argument& ia) {
             Serial.printf("Error: Invalid hex character in string: %s\n", byteString.c_str());
             bytes.clear();
             return bytes;
        } catch (const std::out_of_range& oor) {
             Serial.printf("Error: Hex value out of range: %s\n", byteString.c_str());
             bytes.clear();
             return bytes;
        }
    }
    return bytes;
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
        topic = MQTT_STATUS_TOPIC_BASE + macPart + "/status";
    } else {
        // For generic statuses like initial 'idle', maybe publish to a general topic?
        // Or just log locally? Let's publish to a base status topic for now.
        topic = MQTT_STATUS_TOPIC_BASE + "bridge/status"; // e.g., eink_display/bridge/status
        Serial.print("(Publishing general status) ");
    }

    mqttClient.publish(topic.c_str(), status);
    Serial.printf("Status (%s): %s\n", targetMac.empty() ? "general" : targetMac.c_str(), status);
}