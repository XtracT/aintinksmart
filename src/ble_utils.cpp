#include <NimBLEDevice.h>
#include <Arduino.h> // For Serial, delay

#include "globals.h" // For pClient, bleConnected, currentTargetAddress etc.
#include "mqtt_utils.h" // For publishStatus
#include "ble_utils.h"

bool connectBLE(const std::string& targetMac) {
    if (bleConnected) return true;

    // Use the targetMac passed as argument
    Serial.print("Attempting BLE connection to "); Serial.println(targetMac.c_str());
    publishStatus("connecting_ble", targetMac); // Pass MAC to status

    // Create client if it doesn't exist
    if (!pClient) {
        pClient = NimBLEDevice::createClient();
        if (!pClient) {
            Serial.println("Failed to create BLE client");
            publishStatus("error_ble_client", targetMac); // Pass MAC to status
            return false;
        }
        // Optional: Set connection parameters like pClient->setConnectionParams(12,12,0,51);
    }

    // Check if already connected
    if (pClient->isConnected()) {
         Serial.println("Client already connected (state mismatch). Forcing disconnect first.");
         pClient->disconnect();
         delay(100); // Short delay after disconnect
    }

    // Initiate connection
    // Use currentTargetAddress which should have been set by mqttCallback
    // Set connection timeout (e.g., 10 seconds)
    if (!pClient->connect(currentTargetAddress, false)) { // address, is_initiator (use default timeout)
        Serial.println("Connection failed");
        // Don't delete client here, allow retry in main loop
        return false;
    }
    Serial.println("BLE Connected!");

    // Get service
    NimBLERemoteService* pService = pClient->getService(serviceUUID);
    if (!pService) {
        Serial.print("Failed to find service UUID: "); Serial.println(serviceUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_service", targetMac); // Pass MAC to status
        return false;
    }
    Serial.print("Found service: "); Serial.println(serviceUUID.toString().c_str());

    // Get characteristic
    pRemoteCharacteristic = pService->getCharacteristic(characteristicUUID);
    if (!pRemoteCharacteristic) {
        Serial.print("Failed to find characteristic UUID: "); Serial.println(characteristicUUID.toString().c_str());
        pClient->disconnect();
        publishStatus("error_ble_char", targetMac); // Pass MAC to status
        return false;
    }
    Serial.print("Found characteristic: "); Serial.println(characteristicUUID.toString().c_str());

    bleConnected = true;
    publishStatus("connected_ble", targetMac); // Pass MAC to status
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
    // We no longer clear currentTargetMac here.
    // The main loop() cleanup logic handles this reliably after transferInProgress becomes false.
    // Remove status publish from here, let loop() handle it.
}

bool writePacketToBLE(const std::vector<uint8_t>& packetData) {
    if (!bleConnected || !pRemoteCharacteristic) {
        Serial.println("BLE write failed: Not connected or characteristic invalid.");
        return false;
    }

    // Check if characteristic supports write without response
    bool needsResponse = !pRemoteCharacteristic->canWriteNoResponse();

    bool success = pRemoteCharacteristic->writeValue(packetData.data(), packetData.size(), needsResponse);

    if (success) {
        delay(20); // Crucial delay after successful write
        return true;
    } else {
        return false;
    }
}