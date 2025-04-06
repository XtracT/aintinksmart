# app/processing.py
"""
Handles the core logic for processing specific service requests (send image, scan).
"""
import logging
import asyncio
import json
import base64
import binascii
import re
from typing import Optional, Dict, Any, List, Callable, Coroutine

import aiomqtt
from bleak import BleakScanner
from bleak.exc import BleakError

from . import config
from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError

# Import necessary components from main
from .main import (
    logger,
    OPERATING_MODE,
    MQTT_GATEWAY_BASE_TOPIC,
    EINK_PACKET_DELAY_MS,
    gateway_ready_events, 
    gateway_ready_lock,
    GATEWAY_CONNECT_TIMEOUT,
    MQTT_DEFAULT_STATUS_TOPIC # Import default status topic
)
# Import publish_status helper directly
from .mqtt_utils import publish_status 

# Define a type alias for the publish status function for clarity
# This matches the signature of the actual publish_status function
PublishStatusFunc = Callable[[aiomqtt.Client, str, str, Optional[Dict], Optional[str]], Coroutine[Any, Any, None]] 


async def attempt_direct_ble(client: aiomqtt.Client, mac_address: str, packets_bytes_list: List[bytes]) -> Dict[str, Any]:
    """
    Attempts to send packets directly via BLE with timeout, publishing status updates.
    Now calls publish_status directly.
    """
    logger.info(f"Attempting direct BLE to {mac_address}...")
    ble_timeout = 60.0 
    try:
        async with asyncio.timeout(ble_timeout):
            communicator = BleCommunicator(mac_address)

            await publish_status(client, mac_address, "connecting_ble", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 

            async with communicator:
                await publish_status(client, mac_address, "sending_packets", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC)
                await communicator.send_packets(packets_bytes_list)
                await publish_status(client, mac_address, "waiting_device", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC)

            await publish_status(client, mac_address, "ble_complete", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC)
            logger.info(f"Image sent successfully via direct BLE to {mac_address}.")
            return {"status": "success", "method": "ble", "message": "Sent via direct BLE."}
    except asyncio.TimeoutError:
        logger.warning(f"Direct BLE operation timed out after {ble_timeout}s for {mac_address}.")
        return {"status": "error", "method": "ble", "message": f"Direct BLE timeout after {ble_timeout}s"}
    except (BleakError, BleCommunicationError) as e:
        logger.warning(f"Direct BLE failed for {mac_address}: {e}.")
        return {"status": "error", "method": "ble", "message": f"Direct BLE failed: {e}"}
    except Exception as e:
         logger.exception(f"Unexpected error during direct BLE to {mac_address}: {e}")
         return {"status": "error", "method": "ble", "message": f"Unexpected BLE error: {e}"}

async def attempt_mqtt_publish(client: aiomqtt.Client, mac_address: str, packets_bytes_list: List[bytes], gateway_base_topic: str, delay_ms: int) -> Dict[str, Any]:
    """
    Sends START command, waits for gateway 'connected_ble' status,
    then publishes PACKET commands via MQTT. Uses original Event sync.
    Now calls publish_status directly.
    """
    logger.info(f"Attempting MQTT publish to gateway for {mac_address}...")
    mac_topic_part = mac_address.replace(":", "")
    start_topic = f"{gateway_base_topic}/display/{mac_topic_part}/command/start"
    packet_topic = f"{gateway_base_topic}/display/{mac_topic_part}/command/packet"
    delay_sec = delay_ms / 1000.0

    ready_event_registered = False
    ready_event = asyncio.Event() 

    try:
        # 1. Register Readiness Event FIRST
        async with gateway_ready_lock:
            if mac_address in gateway_ready_events:
                 logger.warning(f"Gateway request already pending for {mac_address}. Aborting new request.")
                 return {"status": "error", "method": "mqtt", "message": f"Gateway busy with previous request for {mac_address}."}
            gateway_ready_events[mac_address] = ready_event
            ready_event_registered = True
            logger.debug(f"Registered readiness event for {mac_address} (Event ID: {id(ready_event)})")

        # 2. Send START command
        start_payload = json.dumps({"total_packets": len(packets_bytes_list)})
        logger.debug(f"Publishing START to {start_topic}")
        await client.publish(start_topic, payload=start_payload, qos=1)
        await asyncio.sleep(0.1) 

        # 3. Wait for Gateway Readiness
        logger.info(f"Waiting up to {GATEWAY_CONNECT_TIMEOUT}s for gateway {mac_address} to connect to BLE...")
        await publish_status(client, mac_address, "gateway_waiting_connect", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 

        try:
            async with asyncio.timeout(GATEWAY_CONNECT_TIMEOUT):
                await ready_event.wait()
            logger.info(f"Gateway {mac_address} signaled ready (connected_ble received).")

            # 4. Send Packets
            logger.info(f"Publishing {len(packets_bytes_list)} packets via MQTT for {mac_address}...")
            await publish_status(client, mac_address, "gateway_sending_packets", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 
            for i, packet_bytes in enumerate(packets_bytes_list):
                hex_packet_payload = binascii.hexlify(packet_bytes).upper().decode()
                await client.publish(packet_topic, payload=hex_packet_payload, qos=1)
                await asyncio.sleep(delay_sec)

            logger.info(f"MQTT command sequence published successfully for {mac_address}.")
            return {"status": "gateway_commands_sent", "method": "mqtt", "message": "Command sequence published via MQTT."}

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for gateway {mac_address} to connect to BLE.")
            return {"status": "error", "method": "mqtt", "message": f"Gateway connect timeout for {mac_address}."}
        except aiomqtt.MqttError as e: 
             logger.error(f"MQTT publishing error during packet send for {mac_address}: {e}")
             return {"status": "error", "method": "mqtt", "message": f"MQTT publish error during packets: {e}"}
        except Exception as e: 
             logger.exception(f"Unexpected error during packet sending for {mac_address}: {e}")
             return {"status": "error", "method": "mqtt", "message": f"Unexpected error during packet send: {e}"}

    except aiomqtt.MqttError as e: 
        logger.error(f"MQTT publishing error during START send for {mac_address}: {e}")
        return {"status": "error", "method": "mqtt", "message": f"MQTT publish error (start): {e}"}
    except Exception as e: 
        logger.exception(f"Unexpected error during MQTT publish setup for {mac_address}: {e}")
        return {"status": "error", "method": "mqtt", "message": f"Unexpected MQTT setup error: {e}"}
    finally:
        # Ensure the event is always removed from the dictionary when this function exits
        if ready_event_registered:
            async with gateway_ready_lock:
                removed_event = gateway_ready_events.pop(mac_address, None)
                if removed_event:
                     logger.debug(f"Cleaned up readiness event for {mac_address} (Event ID: {id(removed_event)})")


async def process_request(
    client: aiomqtt.Client, 
    payload_str: str,
    **kwargs # Accept arbitrary keyword args to ignore unexpected ones
):
    """Parses request, processes image, and triggers BLE/MQTT attempt."""
    # Log if unexpected kwargs are received (like default_status_topic)
    if kwargs:
        logger.warning(f"process_request received unexpected keyword arguments: {kwargs.keys()}")

    request_data: Optional[Dict] = None
    response_topic: Optional[str] = None
    result_payload: Dict[str, Any] = {"status": "error", "message": "Initial processing failed."}
    mac_address = "unknown" 
    
    try:
        request_data = json.loads(payload_str)
        mac_address = request_data.get("mac_address")
        image_data_b64 = request_data.get("image_data")
        mode = request_data.get("mode", config.DEFAULT_COLOR_MODE)
        response_topic = request_data.get("response_topic") 

        if not mac_address or not image_data_b64:
             raise ValueError("Missing 'mac_address' or 'image_data' in request.")
        if not re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', mac_address):
             raise ValueError('Invalid MAC address format')
        mac_address = mac_address.upper()

        if mode not in ['bw', 'bwr']:
             raise ValueError("Invalid 'mode'. Must be 'bw' or 'bwr'.")

        logger.info(f"Processing request for MAC: {mac_address}, Mode: {mode}")

        try:
            image_bytes = base64.b64decode(image_data_b64)
            if not image_bytes: raise ValueError("Decoded image data is empty.")
        except (binascii.Error, TypeError, ValueError) as e: 
            raise ValueError(f"Invalid Base64 image data: {e}") from e

        # Call publish_status directly
        await publish_status(client, mac_address, "processing_request", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 

        logger.info("Processing image...")
        processor = ImageProcessor()
        processed_data = processor.process_image(image_bytes, mode)
        logger.info("Formatting payload...")
        formatter = ProtocolFormatter()
        hex_payload = formatter.format_payload(processed_data)
        logger.info("Building packets...")
        builder = PacketBuilder()
        packets_bytes_list = builder.build_packets(hex_payload, mac_address)
        logger.info(f"{len(packets_bytes_list)} packets built.")

        # Import OPERATING_MODE here
        from .main import OPERATING_MODE, MQTT_GATEWAY_BASE_TOPIC, EINK_PACKET_DELAY_MS

        if OPERATING_MODE == 'ble':
            # Pass client directly
            result_payload = await attempt_direct_ble(client, mac_address, packets_bytes_list) 
        elif OPERATING_MODE == 'mqtt':
            # Call publish_status directly
            await publish_status(client, mac_address, "publishing_mqtt", default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 
            # Pass client directly
            result_payload = await attempt_mqtt_publish(client, mac_address, packets_bytes_list, MQTT_GATEWAY_BASE_TOPIC, EINK_PACKET_DELAY_MS) 
        else:
             result_payload = {"status": "error", "message": "Service operating mode not configured."}

    except json.JSONDecodeError:
        logger.error("Failed to decode request JSON payload.")
        result_payload = {"status": "error", "message": "Invalid JSON payload."}
    except (ValueError, ImageProcessingError, ProtocolFormattingError, PacketBuilderError) as e:
        logger.error(f"Error processing request: {e}")
        result_payload = {"status": "error", "message": f"Processing error: {e}"}
    except Exception as e:
        logger.exception("Unexpected error handling request.")
        result_payload = {"status": "error", "message": f"Unexpected internal error: {e}"}

    # Publish final result status to default topic.
    final_mac = mac_address
    # Call publish_status directly
    await publish_status(client, final_mac, result_payload.get('status', 'unknown_final_status'), result_payload, default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 

    # Also publish result to specific response topic if provided
    if response_topic:
        try:
            logger.info(f"Publishing result to {response_topic}: {result_payload}")
            await client.publish(response_topic, payload=json.dumps(result_payload), qos=1)
        except aiomqtt.MqttError as e:
            logger.error(f"Failed to publish result to {response_topic}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error publishing result to {response_topic}")

async def process_scan_request(client: aiomqtt.Client, payload_str: str, **kwargs): # Add **kwargs
    """Handles incoming scan requests."""
    # Log if unexpected kwargs are received
    if kwargs:
        logger.warning(f"process_scan_request received unexpected keyword arguments: {kwargs.keys()}")

    response_topic: Optional[str] = None
    result_payload: Dict[str, Any] = {"status": "error", "message": "Scan failed."}
    devices = []
    # Import OPERATING_MODE here
    from .main import OPERATING_MODE, MQTT_GATEWAY_BASE_TOPIC, MQTT_DEFAULT_STATUS_TOPIC

    try:
        request_data = json.loads(payload_str)
        response_topic = request_data.get("response_topic") 
        logger.info("Processing scan request...")

        if OPERATING_MODE == 'ble':
            logger.info("Performing direct BLE scan...")
            ble_scan_timeout = 15.0
            try:
                logger.debug(f"Starting BleakScanner.discover with timeout {ble_scan_timeout}s")
                direct_devices = await asyncio.wait_for(
                    BleakScanner.discover(timeout=ble_scan_timeout - 1.0),
                    timeout=ble_scan_timeout
                )
                logger.info(f"Direct scan finished. Found {len(direct_devices)} devices.")
                for device in direct_devices:
                    if device.name and device.name.lower().startswith("easytag"):
                         devices.append({"name": device.name, "address": device.address.upper()})
                logger.info(f"Found {len(devices)} matching devices.")
                result_payload = {"status": "success", "method": "ble", "devices": devices}
            except asyncio.TimeoutError:
                 logger.warning(f"Direct BLE scan timed out after {ble_scan_timeout}s.")
                 result_payload = {"status": "error", "method": "ble", "message": f"Direct BLE scan timed out after {ble_scan_timeout}s"}
            except BleakError as e:
                logger.error(f"Direct BLE scanning failed: {e}.")
                result_payload = {"status": "error", "method": "ble", "message": f"Direct BLE scan failed: {e}"}
            except Exception as e:
                logger.exception(f"Unexpected error during direct BLE discovery: {e}.")
                result_payload = {"status": "error", "method": "ble", "message": f"Unexpected BLE scan error: {e}"}

        elif OPERATING_MODE == 'mqtt':
            logger.info("Triggering MQTT gateway scan...")
            gateway_scan_topic = f"{MQTT_GATEWAY_BASE_TOPIC}/bridge/command/scan"
            gateway_result_topic = f"{MQTT_GATEWAY_BASE_TOPIC}/bridge/scan_result"
            try:
                await client.publish(gateway_scan_topic, payload="", qos=0)
                logger.info(f"Published scan command to {gateway_scan_topic}")
                result_payload = {
                    "status": "success",
                    "method": "mqtt",
                    "message": f"Gateway scan triggered. Monitor topic '{gateway_result_topic}' for results."
                }
            except aiomqtt.MqttError as e:
                 logger.error(f"Failed to publish scan command to gateway: {e}")
                 result_payload = {"status": "error", "method": "mqtt", "message": f"Failed to trigger gateway scan: {e}"}
            except Exception as e:
                 logger.exception(f"Unexpected error triggering gateway scan: {e}")
                 result_payload = {"status": "error", "method": "mqtt", "message": f"Unexpected error triggering scan: {e}"}
        else:
             result_payload = {"status": "error", "message": "Scan not supported in current operating mode."}

    except json.JSONDecodeError:
        logger.error("Failed to decode scan request JSON payload.")
        result_payload = {"status": "error", "message": "Invalid JSON payload for scan request."}
    except Exception as e:
        logger.exception("Unexpected error handling scan request.")
        result_payload = {"status": "error", "message": f"Unexpected internal error: {e}"}

    # Publish result to default status topic
    scan_mac_placeholder = "scan_result" 
    # Call publish_status directly
    await publish_status(client, scan_mac_placeholder, result_payload.get('status', 'unknown_scan_status'), result_payload, default_status_topic=MQTT_DEFAULT_STATUS_TOPIC) 

    # Also publish result to specific response topic if provided
    if response_topic:
        try:
            logger.info(f"Publishing scan result to {response_topic}: {result_payload}")
            await client.publish(response_topic, payload=json.dumps(result_payload), qos=1)
        except aiomqtt.MqttError as e:
            logger.error(f"Failed to publish scan result to {response_topic}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error publishing scan result to {response_topic}")