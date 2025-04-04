#include "globals.h"
#include "config.h" // Provides extern declarations for config values defined here

// --- Configuration Variable Definitions ---
const char* WIFI_SSID = "lookmanowires";
const char* WIFI_PASSWORD = "This is WiFi PassWord";
const char* MQTT_BROKER = "192.168.1.118";
const char* MQTT_USER = "";
const char* MQTT_PASSWORD = "";
const String MQTT_GATEWAY_BASE_TOPIC = "aintinksmart/gateway/";
const char* BLE_SERVICE_UUID_STR = "00001523-1212-efde-1523-785feabcd123";
const char* BLE_CHARACTERISTIC_UUID_STR = "00001525-1212-efde-1523-785feabcd123";

// --- Global Variable Definitions ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

String MQTT_CLIENT_ID = "esp32-eink-bridge-"; // Default prefix, will be appended in setup()
// Subscription Topics
String MQTT_START_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "display/+/command/start";
String MQTT_PACKET_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "display/+/command/packet";
String MQTT_SCAN_COMMAND_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/command/scan";
// Publish Topics
String MQTT_DISPLAY_STATUS_TOPIC_BASE = MQTT_GATEWAY_BASE_TOPIC + "display/"; // Needs /{MAC}/status appended
String MQTT_BRIDGE_STATUS_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/status";
String MQTT_SCAN_RESULT_TOPIC = MQTT_GATEWAY_BASE_TOPIC + "bridge/scan_result";

// BLE UUIDs (Initialized in setup)
NimBLEUUID serviceUUID;
NimBLEUUID characteristicUUID;

std::string currentTargetMac = "";
NimBLEAddress currentTargetAddress;

NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pRemoteCharacteristic = nullptr;
bool bleConnected = false;
bool transferInProgress = false;
unsigned long lastActionTime = 0;
bool transferAborted = false;
int bleConnectRetries = 0;
bool writingStatusPublished = false; // Initialize flag

std::queue<std::vector<uint8_t>> packetQueue;
int packetsReceivedCount = 0;
int packetsWrittenCount = 0;
uint16_t expectedPacketCount = 0; // Initialize expected count

// ScanCallbacks instance is defined in scan_utils.cpp