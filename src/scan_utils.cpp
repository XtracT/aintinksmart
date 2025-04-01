#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include <Arduino.h> // For Serial, String, delay

#include "config.h"
#include "globals.h"
#include "mqtt_utils.h" // For publishStatus
#include "scan_utils.h"

// --- BLE Scan Callback Instance ---
// Class definition is now in scan_utils.h
ScanCallbacks scanCallbacks; // Define the global instance (already declared in globals.h)

// --- ScanCallbacks Method Implementations ---

// Called for each advertising packet received. - Not used with blocking getResults()
void ScanCallbacks::onResult(const NimBLEAdvertisedDevice* advertisedDevice) {
    // Empty implementation - needed for vtable but not called by getResults()
}

// Called when the scan completes (after duration or manually stopped). - Not used with blocking getResults()
void ScanCallbacks::onScanEnd(const NimBLEScanResults& results, int reason) {
    // Empty implementation - needed for vtable but not called by getResults()
}


// --- Scan Function ---
void performBleScanAndReport() {
    Serial.println("Starting BLE scan for EasyTag devices...");
    publishStatus("scanning", ""); // Publish general scanning status

    NimBLEScan* pScan = NimBLEDevice::getScan();

    // Stop any previous scan that might be running
    if(pScan && pScan->isScanning()) { // Check if pScan is valid before calling isScanning
        Serial.println("Stopping previous scan...");
        pScan->stop();
        delay(50); // Short delay after stopping
    }
    if (!pScan) {
        Serial.println("Error getting BLE scanner instance.");
        publishStatus("error_scan_init", "");
        return;
    }

    // Clear any previous scan results before starting
    pScan->clearResults();
    Serial.println("Cleared previous scan results.");
    // Set scan parameters before starting the scan
    pScan->setScanCallbacks(&scanCallbacks, false); // Disable duplicate filtering like example
    pScan->setActiveScan(true); // Active scan uses more power but gets results faster
    pScan->setInterval(100);    // Scan interval (milliseconds)
    pScan->setWindow(100);      // Scan window (match interval like example)

    // Perform blocking scan using getResults()
    Serial.printf("Attempting to start blocking scan for %d seconds...\n", SCAN_DURATION_SECONDS);
    NimBLEScanResults results = pScan->getResults(SCAN_DURATION_SECONDS * 1000, false); // Duration in ms

    // Process results immediately
    int count = results.getCount();
    Serial.printf("Blocking scan finished. Found %d devices.\n", count);

    for (int i = 0; i < count; i++) {
        const NimBLEAdvertisedDevice* advertisedDevice = results.getDevice(i);

        // Log every device found for debugging
        Serial.printf("Device %d: Addr: %s, ", i, advertisedDevice->getAddress().toString().c_str());
        if (advertisedDevice->haveName()) {
            Serial.printf("Name: %s, ", advertisedDevice->getName().c_str());
        }
        if (advertisedDevice->haveServiceUUID()) {
             Serial.printf("Service UUID: %s, ", advertisedDevice->getServiceUUID().toString().c_str());
        }
         Serial.printf("RSSI: %d\n", advertisedDevice->getRSSI());


        // Check if the device has a name and if it starts with "easytag" (case-insensitive)
        if (advertisedDevice->haveName()) {
            std::string devName = advertisedDevice->getName();
            String devNameStr = String(devName.c_str()); // Convert to Arduino String for startsWith
            devNameStr.toLowerCase(); // Case-insensitive comparison

            if (devNameStr.startsWith("easytag")) {
                std::string mac = advertisedDevice->getAddress().toString();
                Serial.printf("Found EasyTag Device: Name: %s, Address: %s\n", devName.c_str(), mac.c_str());

                // Prepare JSON payload
                StaticJsonDocument<200> doc; // Adjust size as needed
                doc["name"] = devName;
                doc["address"] = mac;

                String jsonOutput;
                serializeJson(doc, jsonOutput);

                // Publish to result topic
                if (mqttClient.connected()) { // Need access to mqttClient global
                    mqttClient.publish(MQTT_SCAN_RESULT_TOPIC.c_str(), jsonOutput.c_str());
                } else {
                    Serial.println("MQTT not connected, cannot publish scan result.");
                }
            }
        }
    } // End for loop

    // Clear results buffer after processing
    pScan->clearResults();
    Serial.println("Cleared results buffer.");

    publishStatus("scan_complete", ""); // Publish scan completion status
}

// --- Old Scan Ended Callback (Removed) ---
// void scanEndedCB(NimBLEScanResults results) { ... }