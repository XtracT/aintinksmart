#include <vector>
#include <string>
#include <stdexcept> // For std::invalid_argument, std::out_of_range
#include <Arduino.h> // For Serial

#include "utils.h"

// --- Helper Functions ---
std::vector<uint8_t> hexStringToBytes(const std::string& hex) {
    std::vector<uint8_t> bytes;
    if (hex.length() % 2 != 0) {
        Serial.println("Error: Hex string must have an even number of digits.");
        return bytes; // Return empty vector
    }
    bytes.reserve(hex.length() / 2); // Pre-allocate memory

    for (unsigned int i = 0; i < hex.length(); i += 2) {
        std::string byteString = hex.substr(i, 2);
        try {
            // Use strtoul for robust conversion
            char* end; // To check if the whole string was converted
            unsigned long val = std::strtoul(byteString.c_str(), &end, 16);

            // Check for conversion errors
            if (*end != '\0') { // Check if there were non-hex characters
                 throw std::invalid_argument("Invalid hex character");
            }
            if (val > 255) { // Check if value fits in uint8_t
                 throw std::out_of_range("Hex value out of range for uint8_t");
            }
            bytes.push_back(static_cast<uint8_t>(val));
        } catch (const std::invalid_argument& ia) {
             Serial.printf("Error: Invalid hex character in string: %s\n", byteString.c_str());
             bytes.clear(); // Clear potentially partially filled vector
             return bytes;
        } catch (const std::out_of_range& oor) {
             Serial.printf("Error: Hex value out of range: %s\n", byteString.c_str());
             bytes.clear();
             return bytes;
        } catch (...) { // Catch any other unexpected errors during conversion
             Serial.printf("Error: Unknown error converting hex byte string: %s\n", byteString.c_str());
             bytes.clear();
             return bytes;
        }
    }
    return bytes;
}