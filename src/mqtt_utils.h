#ifndef MQTT_UTILS_H
#define MQTT_UTILS_H

#include <string>

void connectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void publishStatus(const char* status, const std::string& targetMac = "");
std::string extractMacFromTopic(const char* topic);

#endif // MQTT_UTILS_H