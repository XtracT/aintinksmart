import logging
import base64
import binascii
import io
import asyncio
import os
import json
import signal
from typing import Optional, Dict, Any, List, Literal

import aiomqtt
from bleak import BleakScanner
from bleak.exc import BleakError

from . import config # For DEFAULT_COLOR_MODE
from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError
from .models import SendImageBaseRequest # Potentially useful for request structure reference

# Stores asyncio.Event objects keyed by MAC address, signaling gateway readiness
gateway_ready_events: Dict[str, asyncio.Event] = {}
gateway_ready_lock = asyncio.Lock() # Protects access to gateway_ready_events
GATEWAY_CONNECT_TIMEOUT = 60.0 # Seconds to wait for gateway 'connected_ble' status

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_GATEWAY_BASE_TOPIC = os.getenv("MQTT_GATEWAY_BASE_TOPIC", "aintinksmart/gateway")
MQTT_REQUEST_TOPIC = os.getenv("MQTT_REQUEST_TOPIC", "aintinksmart/service/request/send_image")
MQTT_SCAN_REQUEST_TOPIC = os.getenv("MQTT_SCAN_REQUEST_TOPIC", "aintinksmart/service/request/scan")
MQTT_DEFAULT_STATUS_TOPIC = os.getenv("MQTT_DEFAULT_STATUS_TOPIC", "aintinksmart/service/status/default")
EINK_PACKET_DELAY_MS = int(os.getenv("EINK_PACKET_DELAY_MS", "20"))

USE_GATEWAY = os.getenv("USE_GATEWAY", "false").lower() == "true"
BLE_ENABLED = os.getenv("BLE_ENABLED", "true").lower() == "true"

OPERATING_MODE: Optional[Literal['mqtt', 'ble']] = None
if USE_GATEWAY and MQTT_BROKER:
    OPERATING_MODE = 'mqtt'
    logger.info("Operating Mode: MQTT Gateway")
elif BLE_ENABLED:
    OPERATING_MODE = 'ble'
    logger.info("Operating Mode: Direct BLE")
else:
    logger.error("Configuration Error: Neither USE_GATEWAY (with MQTT_BROKER) nor BLE_ENABLED is set. Service cannot operate.")
    # Exit if no valid operating mode could be determined
    exit(1)

async def attempt_direct_ble(client: aiomqtt.Client, mac_address: str, packets_bytes_list: List[bytes]) -> Dict[str, Any]:
    """
    Attempts to send packets directly via BLE with timeout, publishing status updates.
    """
    logger.info(f"Attempting direct BLE to {mac_address}...")
    ble_timeout = 60.0 # seconds
    try:
        async with asyncio.timeout(ble_timeout):
            communicator = BleCommunicator(mac_address)

            await publish_status(client, mac_address, "connecting_ble")

            async with communicator: # Context manager handles connect/disconnect
                await publish_status(client, mac_address, "sending_packets")
                await communicator.send_packets(packets_bytes_list)
                await publish_status(client, mac_address, "waiting_device")

            await publish_status(client, mac_address, "ble_complete")
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
    then publishes PACKET and END commands via MQTT.
    """
    logger.info(f"Attempting MQTT publish to gateway for {mac_address}...")
    mac_topic_part = mac_address.replace(":", "")
    start_topic = f"{gateway_base_topic}/display/{mac_topic_part}/command/start"
    packet_topic = f"{gateway_base_topic}/display/{mac_topic_part}/command/packet"
    end_topic = f"{gateway_base_topic}/display/{mac_topic_part}/command/end"
    delay_sec = delay_ms / 1000.0

    try:
        # 1. Send Start
        start_payload = json.dumps({"total_packets": len(packets_bytes_list)})
        logger.debug(f"Publishing START to {start_topic}")
        await client.publish(start_topic, payload=start_payload, qos=1)
        await asyncio.sleep(0.1) # Delay after start

        # 2. Wait for Gateway Readiness
        ready_event = asyncio.Event()
        async with gateway_ready_lock:
            if mac_address in gateway_ready_events:
                 logger.warning(f"Gateway request already pending for {mac_address}. Aborting new request.")
                 # TODO: Handle concurrent requests for the same MAC?
                 return {"status": "error", "method": "mqtt", "message": f"Gateway busy with previous request for {mac_address}."}
            gateway_ready_events[mac_address] = ready_event

        logger.info(f"Waiting up to {GATEWAY_CONNECT_TIMEOUT}s for gateway {mac_address} (Event ID: {id(ready_event)}) to connect to BLE...")
        await publish_status(client, mac_address, "gateway_waiting_connect")

        try:
            async with asyncio.timeout(GATEWAY_CONNECT_TIMEOUT):
                await ready_event.wait()
            logger.info(f"Gateway {mac_address} signaled ready (connected_ble received).")

            # 3. Send Packets
            logger.info(f"Publishing {len(packets_bytes_list)} packets via MQTT for {mac_address}...")
            await publish_status(client, mac_address, "gateway_sending_packets")
            for i, packet_bytes in enumerate(packets_bytes_list):
                hex_packet_payload = binascii.hexlify(packet_bytes).upper().decode()
                await client.publish(packet_topic, payload=hex_packet_payload, qos=1)
                await asyncio.sleep(delay_sec)


            logger.info(f"MQTT command sequence published successfully for {mac_address}.")
            # Return intermediate status; final status is relayed from gateway
            return {"status": "gateway_commands_sent", "method": "mqtt", "message": "Command sequence published via MQTT."}

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for gateway {mac_address} to connect to BLE.")
            return {"status": "error", "method": "mqtt", "message": f"Gateway connect timeout for {mac_address}."}
        finally:
            async with gateway_ready_lock:
                gateway_ready_events.pop(mac_address, None)

    except aiomqtt.MqttError as e:
        logger.error(f"MQTT publishing error for {mac_address}: {e}")
        return {"status": "error", "method": "mqtt", "message": f"MQTT publish error: {e}"}
    except Exception as e:
        logger.exception(f"Unexpected error during MQTT publishing for {mac_address}: {e}")
        return {"status": "error", "method": "mqtt", "message": f"Unexpected MQTT error: {e}"}

async def publish_status(client: aiomqtt.Client, mac: str, status_msg: str, details: Optional[Dict] = None):
    """Helper to publish status to the default topic."""
    if not MQTT_DEFAULT_STATUS_TOPIC:
        return # Don't attempt publish if topic isn't configured
    try:
        payload = {"mac_address": mac, "status": status_msg}
        if details:
            payload.update(details)
        logger.debug(f"Publishing default status: {payload} to {MQTT_DEFAULT_STATUS_TOPIC}")
        await client.publish(MQTT_DEFAULT_STATUS_TOPIC, payload=json.dumps(payload), qos=0) # Use QoS 0 for status messages
    except Exception as e:
        logger.error(f"Failed to publish default status: {e}")

async def process_request(client: aiomqtt.Client, payload_str: str):
    """Parses request, processes image, and triggers BLE/MQTT attempt."""
    request_data: Optional[Dict] = None
    response_topic: Optional[str] = None
    result_payload: Dict[str, Any] = {"status": "error", "message": "Initial processing failed."}

    try:
        request_data = json.loads(payload_str)
        mac_address = request_data.get("mac_address")
        image_data_b64 = request_data.get("image_data")
        mode = request_data.get("mode", config.DEFAULT_COLOR_MODE)
        response_topic = request_data.get("response_topic") # Optional topic for direct result publishing

        if not mac_address or not image_data_b64:
            raise ValueError("Missing 'mac_address' or 'image_data' in request.")
        import re
        if not re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', mac_address):
             raise ValueError('Invalid MAC address format')
        mac_address = mac_address.upper()

        if mode not in ['bw', 'bwr']:
             raise ValueError("Invalid 'mode'. Must be 'bw' or 'bwr'.")

        logger.info(f"Processing request for MAC: {mac_address}, Mode: {mode}")

        try:
            image_bytes = base64.b64decode(image_data_b64)
            if not image_bytes: raise ValueError("Decoded image data is empty.")
        except (binascii.Error, TypeError) as e:
            raise ValueError(f"Invalid Base64 image data: {e}") from e

        await publish_status(client, mac_address, "processing_request")

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

        if OPERATING_MODE == 'ble':
            result_payload = await attempt_direct_ble(client, mac_address, packets_bytes_list)
        elif OPERATING_MODE == 'mqtt':
            await publish_status(client, mac_address, "publishing_mqtt")
            result_payload = await attempt_mqtt_publish(client, mac_address, packets_bytes_list, MQTT_GATEWAY_BASE_TOPIC, EINK_PACKET_DELAY_MS)
        else:
             # Should not happen due to startup check
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
    # This covers the final status for both BLE mode and relayed MQTT mode.
    final_mac = mac_address if 'mac_address' in locals() and mac_address else (request_data.get("mac_address", "unknown") if request_data else "unknown")
    await publish_status(client, final_mac, result_payload.get('status', 'unknown_final_status'), result_payload)

    # Also publish result to specific response topic if provided
    if response_topic:
        try:
            logger.info(f"Publishing result to {response_topic}: {result_payload}")
            await client.publish(response_topic, payload=json.dumps(result_payload), qos=1)
        except aiomqtt.MqttError as e:
            logger.error(f"Failed to publish result to {response_topic}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error publishing result to {response_topic}")
async def process_scan_request(client: aiomqtt.Client, payload_str: str):
    """Handles incoming scan requests."""
    response_topic: Optional[str] = None
    result_payload: Dict[str, Any] = {"status": "error", "message": "Scan failed."}
    devices = []

    try:
        request_data = json.loads(payload_str)
        response_topic = request_data.get("response_topic") # Optional topic for direct result publishing
        logger.info("Processing scan request...")

        if OPERATING_MODE == 'ble':
            logger.info("Performing direct BLE scan...")
            ble_scan_timeout = 15.0
            try:
                logger.debug(f"Starting BleakScanner.discover with timeout {ble_scan_timeout}s")
                direct_devices = await asyncio.wait_for(
                    BleakScanner.discover(timeout=ble_scan_timeout - 1.0), # Scanner timeout slightly less than wait_for
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

    # Also publish result to specific response topic if provided
    if response_topic:
        try:
            logger.info(f"Publishing scan result to {response_topic}: {result_payload}")
            await client.publish(response_topic, payload=json.dumps(result_payload), qos=1)
        except aiomqtt.MqttError as e:
            logger.error(f"Failed to publish scan result to {response_topic}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error publishing scan result to {response_topic}")



GATEWAY_STATUS_WILDCARD = f"{MQTT_GATEWAY_BASE_TOPIC}/display/+/status"

async def message_handler(client: aiomqtt.Client, stop_event: asyncio.Event):
    """Handles incoming MQTT messages and processes them."""
    logger.info("Message handler task started.")
    try:
        async for message in client.messages:
            if stop_event.is_set():
                logger.info("Stop event set, stopping message handler.")
                break

            logger.info(f"Received message on topic: {message.topic}")
            try:
                payload_str = message.payload.decode()
                # Schedule request processing in background tasks to avoid blocking this loop
                if message.topic.matches(MQTT_REQUEST_TOPIC):
                     logger.debug("Creating background task for process_request")
                     asyncio.create_task(process_request(client, payload_str))
                elif message.topic.matches(MQTT_SCAN_REQUEST_TOPIC):
                     logger.debug("Creating background task for process_scan_request")
                     asyncio.create_task(process_scan_request(client, payload_str))
                # --- Gateway Status Relay ---
                elif message.topic.matches(GATEWAY_STATUS_WILDCARD):
                    logger.debug(f"Received gateway status on {message.topic}")
                    try:
                        topic_parts = message.topic.value.split('/')
                        if len(topic_parts) == 5 and topic_parts[2] == 'display' and topic_parts[4] == 'status':
                            mac_no_colons = topic_parts[3]
                            mac_with_colons = ':'.join(mac_no_colons[i:i+2] for i in range(0, len(mac_no_colons), 2)).upper()

                            logger.debug(f"Gateway status payload for {mac_with_colons}: '{payload_str}'")
                            if payload_str == "connected_ble":
                                async with gateway_ready_lock:
                                    if mac_with_colons in gateway_ready_events:
                                        event_to_set = gateway_ready_events[mac_with_colons]
                                        logger.info(f"Gateway {mac_with_colons} reported connected_ble. Signaling Event ID: {id(event_to_set)}.")
                                        event_to_set.set()
                                    else:
                                        logger.warning(f"Received connected_ble for {mac_with_colons}, but no task was waiting in gateway_ready_events.")

                            # Construct relayed payload
                            relayed_payload = {
                                "mac_address": mac_with_colons,
                                "source": "gateway",
                                "gateway_status": payload_str
                            }
                            # Add top-level 'status' for CLI
                            if payload_str == "success":
                                relayed_payload["status"] = "success"
                            elif payload_str.startswith("error_"):
                                relayed_payload["status"] = "error"
                                relayed_payload["message"] = f"Gateway error: {payload_str}"
                            else:
                                relayed_payload["status"] = f"gateway_{payload_str}"

                            logger.info(f"Relaying gateway status for {mac_with_colons}: {payload_str}")
                            # Publish relayed payload
                            await client.publish(MQTT_DEFAULT_STATUS_TOPIC, payload=json.dumps(relayed_payload), qos=0)
                        else:
                            logger.warning(f"Could not parse MAC from gateway status topic: {message.topic}")
                    except Exception as relay_error:
                        logger.exception(f"Error relaying gateway status from topic {message.topic}: {relay_error}")
                else:
                     logger.warning(f"Received message on unexpected topic: {message.topic}")
            except Exception as e:
                 logger.exception(f"Error processing message from topic {message.topic}")
            # Check stop event again after handling
            if stop_event.is_set():
                logger.info("Stop event set after processing, stopping message handler.")
                break
    except asyncio.CancelledError:
         logger.info("Message handler task cancelled.")
    except Exception as e:
         logger.exception("Error in message handler task.")
    finally:
         logger.info("Message handler task finished.")


async def run_service():
    """Main service loop connecting to MQTT and managing tasks."""
    logger.info(f"Starting headless service in '{OPERATING_MODE}' mode.")
    logger.info(f"Listening for image requests on: {MQTT_REQUEST_TOPIC}")
    logger.info(f"Listening for scan requests on: {MQTT_SCAN_REQUEST_TOPIC}")

    reconnect_interval = 5 # seconds
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    def signal_handler(sig, frame):
        logger.warning(f"Received signal {sig}, setting stop event.")
        stop_event.set()
    loop.add_signal_handler(signal.SIGINT, signal_handler, signal.SIGINT, None)
    loop.add_signal_handler(signal.SIGTERM, signal_handler, signal.SIGTERM, None)

    while not stop_event.is_set():
        message_handler_task = None
        try:
            async with aiomqtt.Client(
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            ) as client:
                logger.info("MQTT client connected.")
                # Subscribe to service request topics
                await client.subscribe(MQTT_REQUEST_TOPIC, qos=1)
                await client.subscribe(MQTT_SCAN_REQUEST_TOPIC, qos=1)
                logger.info(f"Subscribed to service request topics.")
                # Subscribe to gateway status if needed
                if OPERATING_MODE == 'mqtt':
                     await client.subscribe(GATEWAY_STATUS_WILDCARD, qos=0)
                     logger.info(f"Subscribed to gateway status topic: {GATEWAY_STATUS_WILDCARD}")

                message_handler_task = asyncio.create_task(message_handler(client, stop_event))

                stop_wait_task = asyncio.create_task(stop_event.wait())

                done, pending = await asyncio.wait(
                    [stop_wait_task, message_handler_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Check if the message handler task finished unexpectedly
                if message_handler_task in done and not stop_event.is_set():
                    # If message_handler finished first, cancel the stop_wait_task
                    if stop_wait_task in pending:
                        stop_wait_task.cancel()
                    logger.warning("Message handler task finished unexpectedly.")
                    try:
                         message_handler_task.result()
                    except Exception as e:
                         logger.exception("Exception from message handler task:")

                # Handle stop event
                if stop_wait_task in done:
                     logger.info("Stop event received, cancelling message handler task.")
                     if message_handler_task in pending:
                          message_handler_task.cancel()
                          try:
                               await asyncio.wait_for(message_handler_task, timeout=2.0)
                          except asyncio.TimeoutError:
                               logger.warning("Timeout waiting for message handler task to cancel.")
                          except asyncio.CancelledError:
                               logger.info("Message handler task successfully cancelled.")
                     elif message_handler_task.done():
                          logger.debug("Message handler task already done when stop event was processed.")


        except aiomqtt.MqttError as error:
            logger.error(f"MQTT connection error: {error}. Reconnecting in {reconnect_interval} seconds.")
            if stop_event.is_set(): break
            await asyncio.sleep(reconnect_interval)
        except asyncio.CancelledError:
             logger.info("Service run task cancelled.")
             break
        except Exception as e:
             logger.exception(f"Unexpected error in main service loop: {e}. Retrying connection.")
             if stop_event.is_set(): break
             await asyncio.sleep(reconnect_interval)
        finally:
             # Final cancellation check for message handler
             if message_handler_task and not message_handler_task.done():
                  logger.warning("Main loop exiting, ensuring message handler task is cancelled.")
                  message_handler_task.cancel()
                  try:
                       await asyncio.wait_for(message_handler_task, timeout=1.0)
                  except Exception:
                       logger.warning("Exception/Timeout during final message handler cancellation.")

    logger.info("Service loop exiting.")
    # Note: 'async with client:' handles MQTT disconnection.
    # We need the client object here, maybe pass it out or handle disconnect differently
    # For now, rely on 'async with' context manager for cleanup.
    logger.info("Service shutting down.")


# --- Main Execution Guard ---
if __name__ == "__main__":
    if OPERATING_MODE: # Only run if a mode was successfully determined
        try:
             asyncio.run(run_service())
        except KeyboardInterrupt:
             logger.info("Service interrupted by user (KeyboardInterrupt).")
        except Exception as e:
             logger.exception("Unhandled exception during service execution.")
    else:
         logger.error("Service cannot start due to configuration error (no valid operating mode).")