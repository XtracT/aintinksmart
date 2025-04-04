#ifndef GLOBALS_H
#define GLOBALS_H

#include <WiFi.h>
#include <PubSubClient.h>
#include <NimBLEDevice.h>
#include <queue>
#include <vector>
#include <string>

// Forward declaration
class ScanCallbacks;

// --- Global Variable Declarations ---
// (Definitions are in globals.cpp)
extern WiFiClient wifiClient;
extern PubSubClient mqttClient;

extern String MQTT_CLIENT_ID; // Prefix, completed in setup()
extern const String MQTT_GATEWAY_BASE_TOPIC; // Declare the base topic constant
extern String MQTT_START_TOPIC;
extern String MQTT_PACKET_TOPIC;
extern String MQTT_SCAN_COMMAND_TOPIC;
extern String MQTT_DISPLAY_STATUS_TOPIC_BASE; // Base for display status
extern String MQTT_BRIDGE_STATUS_TOPIC;       // Topic for bridge status
extern String MQTT_SCAN_RESULT_TOPIC;         // Topic for scan results

extern NimBLEUUID serviceUUID;
extern NimBLEUUID characteristicUUID;

extern std::string currentTargetMac;
extern NimBLEAddress currentTargetAddress;

extern NimBLEClient* pClient;
extern NimBLERemoteCharacteristic* pRemoteCharacteristic;
extern bool bleConnected;
extern bool transferInProgress;
extern unsigned long lastActionTime;
extern bool transferAborted;
extern int bleConnectRetries;
extern bool writingStatusPublished; // Flag to track if 'writing' status was sent

extern std::queue<std::vector<uint8_t>> packetQueue;
extern int packetsReceivedCount;
extern int packetsWrittenCount;
extern uint16_t expectedPacketCount; // Expected number of packets from START command

extern ScanCallbacks scanCallbacks; // Declare the global instance

#endif // GLOBALS_H