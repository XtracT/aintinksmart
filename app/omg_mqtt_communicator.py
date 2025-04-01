"""
Handles sending BLE packets via MQTT using the OpenMQTTGateway (OMG) protocol.
"""

import logging
import json
import binascii
import time
from typing import List
import paho.mqtt.client as mqtt

# Use relative import for config if needed within the same package structure
# from . import config # Assuming config is needed, but it seems only char_uuid is passed

logger = logging.getLogger(__name__)

class OmgMqttCommunicationError(Exception):
    """Custom exception for OMG MQTT communication failures."""
    pass

class OmgMqttCommunicator:
    """
    Sends BLE packets to a target device via an OpenMQTTGateway using MQTT.
    Supports sending packets individually or as one consolidated message.
    """
    def __init__(self, mqtt_client: mqtt.Client, omg_base_topic: str, char_uuid: str,
                 use_consolidated_message: bool = False, packet_delay_ms: int = 50):
        """
        Initializes the OmgMqttCommunicator.

        Args:
            mqtt_client: An initialized and connected paho.mqtt.client instance.
            omg_base_topic: The base topic of the OpenMQTTGateway device (e.g., "home/OMG_ESP32_BLE").
            char_uuid: The UUID of the target BLE characteristic to write to.
            use_consolidated_message: If True, sends all packets in one message. If False (default), sends one message per packet.
            packet_delay_ms: Delay in milliseconds between sending individual packet messages (default: 50). Only used if use_consolidated_message is False.
        """
        if not mqtt_client or not mqtt_client.is_connected():
            raise OmgMqttCommunicationError("MQTT client is not provided or not connected.")
        if not omg_base_topic:
             raise OmgMqttCommunicationError("OMG base topic cannot be empty.")
        if not char_uuid:
             raise OmgMqttCommunicationError("Target characteristic UUID cannot be empty.")

        self.mqtt_client = mqtt_client
        self.omg_command_topic = f"{omg_base_topic.rstrip('/')}/commands/MQTTtoBT"
        self.char_uuid = char_uuid
        self.use_consolidated_message = use_consolidated_message
        self.packet_delay_sec = packet_delay_ms / 1000.0 # Convert ms to seconds for time.sleep()
        logger.info(f"OMG MQTT Communicator initialized. Target topic: {self.omg_command_topic}, Char UUID: {self.char_uuid}")
        logger.info(f"Using consolidated message: {self.use_consolidated_message}, Individual packet delay: {packet_delay_ms}ms")

    def send_packets(self, mac_address: str, packets: List[bytes]) -> bool:
        """
        Sends a list of BLE packets via MQTT to the configured OMG topic,
        using either the consolidated or individual message method.

        Args:
            mac_address: The target BLE device's MAC address.
            packets: A list of byte arrays, each representing a packet from PacketBuilder.

        Returns:
            True if the operation was successful (all packets published without immediate error),
            False otherwise.
        """
        if not packets:
            logger.warning("No packets provided to send via OMG MQTT.")
            return True # Nothing to send, technically successful

        if self.use_consolidated_message:
            return self._send_consolidated_message(mac_address, packets)
        else:
            return self._send_individual_messages(mac_address, packets)

    def _send_consolidated_message(self, mac_address: str, packets: List[bytes]) -> bool:
        """Sends all packets in a single MQTT message."""
        logger.info(f"Sending {len(packets)} packets as a single consolidated MQTT message to {mac_address}...")
        try:
            hex_packets_list = [binascii.hexlify(packet).upper().decode() for packet in packets]
            service_uuid_placeholder = "00001523-1212-efde-1523-785feabcd123" # Placeholder
            payload = {
                "id": mac_address, "ble_write_address": mac_address, "mac_type": 0,
                "ble_write_service": service_uuid_placeholder, "ble_write_char": self.char_uuid,
                "packets": hex_packets_list, "value_type": "HEX", "immediate": True
            }
            payload_json = json.dumps(payload)
            logger.debug(f"Publishing consolidated message ({len(packets)} packets) to {self.omg_command_topic}")
            msg_info = self.mqtt_client.publish(self.omg_command_topic, payload_json, qos=1)
            try:
                 msg_info.wait_for_publish(timeout=10.0)
                 if not msg_info.is_published():
                     logger.warning(f"MQTT publish confirmation not received for consolidated message (mid={msg_info.mid}).")
                     return False
                 else:
                      logger.info(f"Consolidated message published successfully.")
                      return True
            except Exception as e:
                 logger.error(f"Error waiting for publish confirmation for consolidated message: {e}")
                 return False
        except Exception as e:
            logger.exception(f"Unexpected error publishing consolidated message: {e}")
            return False

    def _send_individual_messages(self, mac_address: str, packets: List[bytes]) -> bool:
        """Sends one MQTT message per packet with a delay."""
        logger.info(f"Sending {len(packets)} packets as individual MQTT messages to {mac_address} with {self.packet_delay_sec*1000:.0f}ms delay...")
        all_published_confirmed = True
        service_uuid_placeholder = "00001523-1212-efde-1523-785feabcd123" # Placeholder

        for i, packet in enumerate(packets):
            try:
                hex_packet = binascii.hexlify(packet).upper().decode()
                payload = {
                    "id": mac_address, "ble_write_address": mac_address, "mac_type": 0,
                    "ble_write_service": service_uuid_placeholder, "ble_write_char": self.char_uuid,
                    "ble_write_value": hex_packet, "value_type": "HEX" # Removed "immediate": True
                }
                payload_json = json.dumps(payload)
                logger.debug(f"Publishing packet {i+1}/{len(packets)} ({len(packet)} bytes) to {self.omg_command_topic} (immediate=false)")
                msg_info = self.mqtt_client.publish(self.omg_command_topic, payload_json, qos=1)
                try:
                    msg_info.wait_for_publish(timeout=5.0)
                    if not msg_info.is_published():
                        logger.warning(f"MQTT publish confirmation not received for packet {i+1} (mid={msg_info.mid}).")
                        all_published_confirmed = False # Mark as failed if any confirmation fails
                        # Continue sending other packets? Or break? Let's continue for now.
                except Exception as e:
                    logger.error(f"Error waiting for publish confirmation for packet {i+1}: {e}")
                    all_published_confirmed = False
                    # Continue sending other packets? Or break? Let's continue for now.

                # Delay before sending the next packet
                if i < len(packets) - 1: # Don't sleep after the last packet
                    time.sleep(self.packet_delay_sec)

            except Exception as e:
                logger.exception(f"Unexpected error publishing packet {i+1}: {e}")
                all_published_confirmed = False
                # Decide whether to break or continue on error
                # Let's break on unexpected errors during publish itself
                break

        if all_published_confirmed:
            logger.info(f"All {len(packets)} individual packets published successfully.")
        else:
            logger.error(f"Failed to publish or confirm all {len(packets)} individual packets.")

        return all_published_confirmed