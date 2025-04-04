#ifndef UTILS_H
#define UTILS_H

#include <vector>
#include <string>
#include <stdint.h> // For uint8_t

std::vector<uint8_t> hexStringToBytes(const std::string& hex);

#endif // UTILS_H