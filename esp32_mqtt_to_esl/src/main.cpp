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
const char* BLE_TARGET_MAC = "44:00:00:0A:91:40"; // <<< VERIFY/SET YOUR DISPLAY MAC
const char* BLE_SERVICE_UUID_STR = "00001523-1212-efde-1523-785feabcd123"; // <<< VERIFY THIS SERVICE UUID
const char* BLE_CHARACTERISTIC_UUID_STR = "00001525-1212-efde-1523-785feabcd123";

// --- Global Variables ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

NimBLEAddress targetAddress(std::string(BLE_TARGET_MAC), BLE_ADDR_PUBLIC);
NimBLEUUID serviceUUID(BLE_SERVICE_UUID_STR);
NimBLEUUID characteristicUUID(BLE_CHARACTERISTIC_UUID_STR);

NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pRemoteCharacteristic = nullptr;
bool bleConnected = false;
bool transferInProgress = false; // Flag to manage connection state and packet queuing
unsigned long lastActionTime = 0; // For inactivity timeout
const unsigned long TRANSFER_TIMEOUT_MS = 30000; // Timeout for transfer inactivity (30s)
bool endCommandReceived = false; // Flag to indicate END command was received

// Packet Queue
std::queue<std::vector<uint8_t>> packetQueue;
int packetsReceivedCount = 0;
int packetsWrittenCount = 0;

// --- Function Declarations ---
void connectWiFi();
void connectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
bool connectBLE();
void disconnectBLE(bool force = false);
bool writePacketToBLE(const std::vector<uint8_t>& packetData);
std::vector<uint8_t> hexStringToBytes(const std::string& hex);
void publishStatus(const char* status);

// --- Setup Function ---
void setup() {
    Serial.begin(115200);
    while (!Serial);
    Serial.println("ESP32 E-Ink Bridge Starting (3-Topic Protocol)...");

    // Generate unique MQTT client ID and topics
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    MQTT_CLIENT_ID += mac;
    String macTopicPart = BLE_TARGET_MAC; // Use target MAC for topic clarity
    macTopicPart.replace(":", "");
    MQTT_START_TOPIC = MQTT_COMMAND_TOPIC_BASE + macTopicPart + "/command/start";
    MQTT_PACKET_TOPIC = MQTT_COMMAND_TOPIC_BASE + macTopicPart + "/command/packet";
    MQTT_END_TOPIC = MQTT_COMMAND_TOPIC_BASE + macTopicPart + "/command/end";
    MQTT_STATUS_TOPIC = MQTT_STATUS_TOPIC_BASE + macTopicPart + "/status";

    Serial.print("MQTT Client ID: "); Serial.println(MQTT_CLIENT_ID);
    Serial.print("MQTT Start Topic: "); Serial.println(MQTT_START_TOPIC);
    Serial.print("MQTT Packet Topic: "); Serial.println(MQTT_PACKET_TOPIC);
    Serial.print("MQTT End Topic: "); Serial.println(MQTT_END_TOPIC);
    Serial.print("MQTT Status Topic: "); Serial.println(MQTT_STATUS_TOPIC);

    connectWiFi();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    // Increase MQTT buffer size if needed (PubSubClient default is small)
    // mqttClient.setBufferSize(1024); // Example if needed

    Serial.println("Initializing NimBLE...");
    NimBLEDevice::init("");
    // NimBLEDevice::setPower(ESP_PWR_LVL_P9); // Optional

    Serial.println("Setup complete.");
    publishStatus("idle");
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
        // Check for inactivity timeout
        if (millis() - lastActionTime > TRANSFER_TIMEOUT_MS) {
            Serial.println("Transfer timed out due to inactivity.");
            publishStatus("error_timeout");
            disconnectBLE(true); // Force disconnect on timeout
            transferInProgress = false;
            // Clear queue
            std::queue<std::vector<uint8_t>> empty;
            std::swap(packetQueue, empty);
        }

        // If transfer is active, ensure BLE is connected
        if (!bleConnected) {
            if (!connectBLE()) {
                Serial.println("BLE connection failed during transfer, retrying...");
                publishStatus("connecting_ble");
                delay(1000); // Wait before retrying connection
                return; // Skip packet processing this loop
            }
        }

        // If connected and packets are waiting, process one
        if (bleConnected && !packetQueue.empty()) {
            std::vector<uint8_t> packet = packetQueue.front();
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
                    publishStatus("complete"); // Publish completion status
                } else {
                    publishStatus("writing"); // Still writing packets
                }
            } else {
                Serial.println("Packet write failed. Will retry connection/write.");
                publishStatus("error_write");
                disconnectBLE(true); // Disconnect on write failure to force reconnect
                // Packet remains in queue to be retried
                delay(500); // Wait before retrying
            }
        }
    } else {
        // Transfer is NOT in progress (transferInProgress == false)
        if (bleConnected) {
             // This state is reached after transferInProgress is set to false (either by completion or timeout)
             Serial.println("Transfer finished or timed out, disconnecting idle BLE connection.");
             disconnectBLE(); // Disconnect BLE cleanly
             // Reset flags for next transfer (ensure timeout doesn't linger)
             endCommandReceived = false;
             lastActionTime = 0;
             // Clear queue just in case (e.g., timeout occurred)
             std::queue<std::vector<uint8_t>> empty;
             std::swap(packetQueue, empty);
             publishStatus("idle"); // Ready for next transfer
        }
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
             Serial.println("Subscribed to command topics:");
             Serial.println(MQTT_START_TOPIC);
             Serial.println(MQTT_PACKET_TOPIC);
             Serial.println(MQTT_END_TOPIC);
        } else {
            Serial.println("Subscription failed!");
        }
        publishStatus("idle"); // Report status after connecting
    } else {
        Serial.print(" failed, rc="); Serial.print(mqttClient.state());
        Serial.println(" Retrying in 5 seconds...");
        // Don't block here, loop will retry
    }
}

// --- MQTT Message Callback ---
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    Serial.print("Message arrived ["); Serial.print(topic); Serial.print("] ");
    payload[length] = '\0'; // Null-terminate payload for C-string functions
    String topicStr = String(topic);

    lastActionTime = millis(); // Reset inactivity timer on any command message

    if (topicStr.equals(MQTT_START_TOPIC)) {
        Serial.println("Received START command.");
        if (transferInProgress) {
            Serial.println("Warning: Received 'start' while transfer already in progress. Resetting.");
            disconnectBLE(true); // Force disconnect previous transfer
        }
        // Clear queue and reset counters
        std::queue<std::vector<uint8_t>> empty;
        std::swap(packetQueue, empty);
        packetsReceivedCount = 0;
        endCommandReceived = false; // Reset flag on new transfer
        packetsWrittenCount = 0;

        Serial.println("Starting transfer.");
        transferInProgress = true;
        publishStatus("starting");
        // Attempt initial connection immediately
        if (!bleConnected) connectBLE();

    } else if (topicStr.equals(MQTT_PACKET_TOPIC)) {
        if (!transferInProgress) {
            Serial.println("Warning: Received 'packet' but no transfer in progress. Ignoring.");
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
             Serial.println("Error converting hex packet data.");
             publishStatus("error_packet_format");
        }

    } else if (topicStr.equals(MQTT_END_TOPIC)) {
        if (!transferInProgress) {
            Serial.println("Warning: Received 'end' but no transfer in progress. Ignoring.");
            return;
        }
        Serial.printf("Received END command after %d packets received.\n", packetsReceivedCount);
        endCommandReceived = true; // Set flag
        publishStatus("ending");
        // If queue is already empty when END arrives, finish immediately
        if (packetQueue.empty()) {
            transferInProgress = false;
        }
    }
}

// --- BLE Functions ---
bool connectBLE() {
    if (bleConnected) return true;

    Serial.print("Attempting BLE connection to "); Serial.println(BLE_TARGET_MAC);
    publishStatus("connecting_ble");

    // Create client if it doesn't exist
    if (!pClient) {
        pClient = NimBLEDevice::createClient();
        if (!pClient) {
            Serial.println("Failed to create BLE client");
            publishStatus("error_ble_client");
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
    if (!pClient->connect(targetAddress)) {
        Serial.println("Connection failed");
        // Don't delete client here, allow retry in main loop
        publishStatus("error_ble_connect");
        return false;
    }
    Serial.println("BLE Connected!");

    // Get service
    NimBLERemoteService* pService = pClient->getService(serviceUUID);
    if (!pService) {
        Serial.print("Failed to find service UUID: "); Serial.println(serviceUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_service");
        return false;
    }
    Serial.print("Found service: "); Serial.println(serviceUUID.toString().c_str());

    // Get characteristic
    pRemoteCharacteristic = pService->getCharacteristic(characteristicUUID);
    if (!pRemoteCharacteristic) {
        Serial.print("Failed to find characteristic UUID: "); Serial.println(characteristicUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_char");
        return false;
    }
    Serial.print("Found characteristic: "); Serial.println(characteristicUUID.toString().c_str());

    bleConnected = true;
    publishStatus("connected_ble");
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
    if (transferInProgress && !force) {
         publishStatus("idle"); // Report idle only if disconnect wasn't forced
    }
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

void publishStatus(const char* status) {
    if (mqttClient.connected()) {
        mqttClient.publish(MQTT_STATUS_TOPIC.c_str(), status);
    }
    Serial.print("Status: "); Serial.println(status);
}