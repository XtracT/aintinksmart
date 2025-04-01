#ifndef BLE_UTILS_H
#define BLE_UTILS_H

#include <string>
#include <vector>
#include <stdint.h> // For uint8_t

bool connectBLE(const std::string& targetMac);
void disconnectBLE(bool force = false);
bool writePacketToBLE(const std::vector<uint8_t>& packetData);

#endif // BLE_UTILS_H