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

// MQTT Topics (Initialized in setup)
extern String MQTT_CLIENT_ID;
extern String MQTT_START_TOPIC;
extern String MQTT_PACKET_TOPIC;
extern String MQTT_END_TOPIC;
extern String MQTT_SCAN_COMMAND_TOPIC;
extern String MQTT_SCAN_RESULT_TOPIC;

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
extern bool endCommandReceived;
extern bool transferAborted;
extern int bleConnectRetries;

// Packet Queue
extern std::queue<std::vector<uint8_t>> packetQueue;
extern int packetsReceivedCount;
extern int packetsWrittenCount;

// Scan State & Callback Instance
// extern bool scanIsRunning; // No longer needed for blocking scan
extern ScanCallbacks scanCallbacks; // Declare the global instance

#endif // GLOBALS_H