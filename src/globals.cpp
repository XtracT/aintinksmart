#include "globals.h"
#include "config.h" // Include config.h to get the extern declarations

// --- Configuration Variable Definitions (from config.h) ---
const char* WIFI_SSID = "lookmanowires";
const char* WIFI_PASSWORD = "This is WiFi PassWord";
const char* MQTT_BROKER = "192.168.1.118";
const char* MQTT_USER = "";
const char* MQTT_PASSWORD = "";
// Define the new base topic for gateway communication
const String MQTT_GATEWAY_BASE_TOPIC = "aintinksmart/gateway/";
// Base topic is defined, specific topics constructed below
const char* BLE_SERVICE_UUID_STR = "00001523-1212-efde-1523-785feabcd123";
const char* BLE_CHARACTERISTIC_UUID_STR = "00001525-1212-efde-1523-785feabcd123";

// --- Other Global Variables (Definitions) ---

// Network Clients
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// MQTT Topics (Defined directly here)
String MQTT_CLIENT_ID = "esp32-eink-bridge-"; // Default prefix, will be appended in setup()
// Subscription Topics (using wildcards where appropriate)
String MQTT_START_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "display/+/command/start";
String MQTT_PACKET_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "display/+/command/packet";
String MQTT_END_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "display/+/command/end";
String MQTT_SCAN_COMMAND_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/command/scan";
// Publish Topics (Base for dynamic construction or specific topics)
String MQTT_DISPLAY_STATUS_TOPIC_BASE = MQTT_GATEWAY_BASE_TOPIC + "display/"; // Needs /{MAC}/status appended
String MQTT_BRIDGE_STATUS_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/status";
String MQTT_SCAN_RESULT_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/scan_result";

// BLE UUIDs (Initialized in setup or globally if constant)
NimBLEUUID serviceUUID;
NimBLEUUID characteristicUUID;

// Dynamic Target State
std::string currentTargetMac = "";
NimBLEAddress currentTargetAddress;

// BLE Client & State
NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pRemoteCharacteristic = nullptr;
bool bleConnected = false;
bool transferInProgress = false;
unsigned long lastActionTime = 0;
bool endCommandReceived = false;
bool transferAborted = false;
int bleConnectRetries = 0;
bool writingStatusPublished = false; // Initialize flag
// bool scanIsRunning = false; // No longer needed for blocking scan

// Packet Queue
std::queue<std::vector<uint8_t>> packetQueue;
int packetsReceivedCount = 0;
int packetsWrittenCount = 0;

// Scan Callback Instance is defined in scan_utils.cpp