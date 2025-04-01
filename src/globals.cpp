#include "globals.h"
#include "config.h" // Include config.h to get the extern declarations

// --- Configuration Variable Definitions (from config.h) ---
const char* WIFI_SSID = "lookmanowires";
const char* WIFI_PASSWORD = "This is WiFi PassWord";
const char* MQTT_BROKER = "192.168.1.118";
const char* MQTT_USER = "";
const char* MQTT_PASSWORD = "";
const String MQTT_COMMAND_TOPIC_BASE = "eink_display/";
const String MQTT_STATUS_TOPIC_BASE = "eink_display/";
const char* BLE_SERVICE_UUID_STR = "00001523-1212-efde-1523-785feabcd123";
const char* BLE_CHARACTERISTIC_UUID_STR = "00001525-1212-efde-1523-785feabcd123";

// --- Other Global Variables (Definitions) ---

// Network Clients
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// MQTT Topics (Initialized in setup)
String MQTT_CLIENT_ID = "esp32-eink-bridge-"; // Default prefix
String MQTT_START_TOPIC = "";
String MQTT_PACKET_TOPIC = "";
String MQTT_END_TOPIC = "";
String MQTT_SCAN_COMMAND_TOPIC = "";
String MQTT_SCAN_RESULT_TOPIC = "";

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
// bool scanIsRunning = false; // No longer needed for blocking scan

// Packet Queue
std::queue<std::vector<uint8_t>> packetQueue;
int packetsReceivedCount = 0;
int packetsWrittenCount = 0;

// Scan Callback Instance is defined in scan_utils.cpp