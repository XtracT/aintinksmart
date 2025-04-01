#include <WiFi.h>
#include <Arduino.h> // For Serial, delay, ESP
#include "config.h" // For WIFI_SSID, WIFI_PASSWORD
#include "wifi_utils.h"

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