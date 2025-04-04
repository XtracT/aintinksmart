#ifndef GLOBALS_H
#define GLOBALS_H

#include <WiFi.h>
#include <PubSubClient.h>
#include <NimBLEDevice.h>
#include <queue>
#include <vector>
#include <string>

// Forward declaration for ScanCallbacks if needed, or include scan_utils.h later
class ScanCallbacks;

// --- Global Variables (Declarations) ---

// Network Clients
extern WiFiClient wifiClient;
extern PubSubClient mqttClient;

// MQTT Topics (Defined in globals.cpp)
extern String MQTT_CLIENT_ID; // Prefix, completed in setup()
extern const String MQTT_GATEWAY_BASE_TOPIC; // Declare the base topic constant
// Subscription Topics
extern String MQTT_START_TOPIC;
extern String MQTT_PACKET_TOPIC;
extern String MQTT_END_TOPIC;
extern String MQTT_SCAN_COMMAND_TOPIC;
// Publish Topics
extern String MQTT_DISPLAY_STATUS_TOPIC_BASE; // Base for display status
extern String MQTT_BRIDGE_STATUS_TOPIC;       // Topic for bridge status
extern String MQTT_SCAN_RESULT_TOPIC;         // Topic for scan results

// BLE UUIDs
extern NimBLEUUID serviceUUID;
extern NimBLEUUID characteristicUUID;

// Dynamic Target State
extern std::string currentTargetMac;
extern NimBLEAddress currentTargetAddress;

// BLE Client & State
extern NimBLEClient* pClient;
extern NimBLERemoteCharacteristic* pRemoteCharacteristic;
extern bool bleConnected;
extern bool transferInProgress;
extern unsigned long lastActionTime;
// extern bool endCommandReceived; // Removed - completion based on packet count
extern bool transferAborted;
extern int bleConnectRetries;
extern bool writingStatusPublished; // Flag to track if 'writing' status was sent

// Packet Queue
extern std::queue<std::vector<uint8_t>> packetQueue;
extern int packetsReceivedCount;
extern int packetsWrittenCount;
extern uint16_t expectedPacketCount; // Expected number of packets from START command

// Scan State & Callback Instance
// extern bool scanIsRunning; // No longer needed for blocking scan
extern ScanCallbacks scanCallbacks; // Declare the global instance

#endif // GLOBALS_H