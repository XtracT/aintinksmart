#ifndef SCAN_UTILS_H
#define SCAN_UTILS_H

#include <NimBLEDevice.h> // For NimBLEScanResults

// --- BLE Scan Callback Class ---
// Use NimBLEScanCallbacks for scan start/stop events
// Device results will be processed after blocking scan completes
class ScanCallbacks : public NimBLEScanCallbacks {
public:
    // Called for each advertising packet received.
    void onResult(const NimBLEAdvertisedDevice* advertisedDevice) override;

    // Called when the scan completes (after duration or manually stopped).
    void onScanEnd(const NimBLEScanResults& results, int reason) override;
};

// Declare the global instance (defined in scan_utils.cpp)
extern ScanCallbacks scanCallbacks;

void performBleScanAndReport();

#endif // SCAN_UTILS_H