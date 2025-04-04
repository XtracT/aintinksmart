#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h> // For String type

// --- Configuration Placeholders ---

// WiFi Credentials
extern const char* WIFI_SSID;
extern const char* WIFI_PASSWORD;

// MQTT Broker Configuration
extern const char* MQTT_BROKER;
const int MQTT_PORT = 1883;
extern const char* MQTT_USER;
extern const char* MQTT_PASSWORD;
extern const String MQTT_COMMAND_TOPIC_BASE;
extern const String MQTT_STATUS_TOPIC_BASE;

// BLE Target Configuration
extern const char* BLE_SERVICE_UUID_STR;
extern const char* BLE_CHARACTERISTIC_UUID_STR;

// Timing and Retries
const int MAX_BLE_CONNECT_RETRIES = 4; // Max attempts to connect before failing transfer
const int SCAN_DURATION_SECONDS = 15; // Increased duration for BLE scan
const unsigned long PACKET_RECEIVE_TIMEOUT_MS = 15000; // Timeout for receiving next packet (15 seconds)

#endif // CONFIG_H