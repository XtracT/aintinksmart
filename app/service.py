# app/service.py
"""
Handles MQTT connection, message routing, status publishing, and the main service loop.
Supports default request topic (JSON/base64) and mapped topics (raw bytes).
"""
import logging
import asyncio
import json
import signal
import base64 
import binascii 
from typing import Optional, Dict, Any, Callable, Coroutine, Literal

import aiomqtt 
from pydantic import ValidationError

# Import necessary components from other modules within the app package
from .main import ( 
    logger,
    gateway_ready_events, 
    gateway_ready_lock,
    MQTT_DEFAULT_STATUS_TOPIC # Import default topic for publish_status helper
)
# Import processing functions and publish_status helper
from .processing import process_request, process_scan_request
# Import publish_status from mqtt_utils
from .mqtt_utils import publish_status 
from .models import SendImageApiRequest 

# Define a type alias for the publish status function for clarity
# This matches the signature of the actual publish_status function
PublishStatusFunc = Callable[[aiomqtt.Client, str, str, Optional[Dict], Optional[str]], Coroutine[Any, Any, None]] 

# Note: publish_status is now defined in mqtt_utils.py

async def message_handler(
    client: aiomqtt.Client, # The main client object
    stop_event: asyncio.Event,
    default_image_request_topic: str,
    scan_request_topic: str,
    image_topic_map: Dict[str, str],
    gateway_status_wildcard: str,
    default_status_topic: str, # Keep receiving it for direct calls to publish_status
    gateway_base_topic: str 
):
    """Handles incoming MQTT messages and processes them."""
    logger.info("Message handler task started.")
        
    try:
        async for message in client.messages:
            if stop_event.is_set():
                logger.info("Stop event set, stopping message handler.")
                break

            topic_str = message.topic.value
            logger.info(f"Received message on topic: {topic_str}")

            try:
                # --- Request Topics ---
                if topic_str == default_image_request_topic:
                    logger.debug(f"Processing request on default topic: {topic_str}")
                    payload_str = None
                    try:
                        payload_str = message.payload.decode() 
                        request_data = SendImageApiRequest.parse_raw(payload_str)
                        try:
                             base64.b64decode(request_data.image_data, validate=True)
                        except (binascii.Error, ValueError) as b64_e:
                             raise ValueError(f"Invalid base64 image data in payload: {b64_e}") from b64_e
                        
                        logger.info(f"Processing default image request for MAC: {request_data.mac_address}")
                        # CORRECTED CALL: process_request expects only client, payload_str
                        asyncio.create_task(process_request(
                            client=client, 
                            payload_str=payload_str 
                        ))
                    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
                        logger.error(f"Invalid payload on default topic {topic_str}: {e}")
                    except Exception as e:
                         logger.exception(f"Unexpected error processing default image request from topic {topic_str}")

                elif topic_str in image_topic_map:
                    mac = image_topic_map[topic_str]
                    logger.debug(f"Processing request on mapped topic: {topic_str} for MAC: {mac}")
                    try:
                        image_bytes = message.payload 
                        if not image_bytes:
                             raise ValueError("Received empty payload on mapped image topic.")
                        image_data_b64 = base64.b64encode(image_bytes).decode('ascii')
                        payload_dict = {
                            "mac_address": mac,
                            "image_data": image_data_b64,
                            "mode": "bwr" 
                        }
                        payload_str = json.dumps(payload_dict)
                        logger.info(f"Processing mapped image request for MAC: {mac}")
                        # CORRECTED CALL: process_request expects only client, payload_str
                        asyncio.create_task(process_request(
                            client=client, 
                            payload_str=payload_str
                        ))
                    except ValueError as e: 
                        logger.error(f"Invalid payload on mapped topic {topic_str} for MAC {mac}: {e}")
                        await publish_status(client, mac, "error", {"message": str(e)}, default_status_topic=default_status_topic) 
                    except Exception as e:
                         logger.exception(f"Unexpected error processing mapped image request from topic {topic_str} for MAC {mac}")
                         await publish_status(client, mac, "error", {"message": f"Internal server error processing request."}, default_status_topic=default_status_topic) 

                elif topic_str == scan_request_topic:
                     logger.debug("Creating background task for process_scan_request")
                     payload_str = None
                     try:
                         payload_str = message.payload.decode() 
                         # CORRECTED CALL: process_scan_request expects only client, payload_str
                         asyncio.create_task(process_scan_request(
                             client, 
                             payload_str 
                         ))
                     except UnicodeDecodeError as e:
                          logger.error(f"Failed to decode payload as UTF-8 on scan topic {topic_str}: {e}")
                     except Exception as e:
                          logger.exception(f"Unexpected error processing scan request from topic {topic_str}")

                # --- Gateway Status Topic ---
                elif message.topic.matches(gateway_status_wildcard):
                    logger.debug(f"Received gateway status on {message.topic}")
                    payload_str = None
                    try:
                        payload_str = message.payload.decode() 
                        topic_parts = message.topic.value.split('/')
                        if len(topic_parts) == 5 and topic_parts[2] == 'display' and topic_parts[4] == 'status':
                            mac_no_colons = topic_parts[3]
                            mac_with_colons = ':'.join(mac_no_colons[i:i+2] for i in range(0, len(mac_no_colons), 2)).upper()

                            logger.debug(f"Gateway status payload for {mac_with_colons}: '{payload_str}'")

                            # --- Handle connected_ble using Event (Original Sync Logic) ---
                            if payload_str == "connected_ble":
                                async with gateway_ready_lock:
                                    if mac_with_colons in gateway_ready_events:
                                        event_to_set = gateway_ready_events[mac_with_colons]
                                        logger.info(f"Gateway {mac_with_colons} reported connected_ble. Signaling Event ID: {id(event_to_set)}.")
                                        event_to_set.set() 
                                    else:
                                        logger.warning(f"Received connected_ble for {mac_with_colons}, but no corresponding event was found in gateway_ready_events (likely timed out).")
                            
                            # --- Relay Status ---
                            relayed_payload = {
                                "mac_address": mac_with_colons,
                                "source": "gateway",
                                "gateway_status": payload_str
                            }
                            if payload_str == "success":
                                relayed_payload["status"] = "success"
                            elif payload_str.startswith("error_"):
                                relayed_payload["status"] = "error"
                                relayed_payload["message"] = f"Gateway error: {payload_str}"
                            else:
                                relayed_payload["status"] = f"gateway_{payload_str}"

                            logger.info(f"Relaying gateway status for {mac_with_colons}: {payload_str}")
                            # Call publish_status directly, passing client and default_status_topic
                            await publish_status(client, mac_with_colons, f"gateway_{payload_str}", relayed_payload, default_status_topic=default_status_topic) 

                        else:
                            logger.warning(f"Could not parse MAC from gateway status topic: {message.topic}")
                    except UnicodeDecodeError as e:
                         logger.error(f"Failed to decode gateway status payload as UTF-8 on topic {topic_str}: {e}")
                    except Exception as relay_error:
                        logger.exception(f"Error processing gateway status from topic {message.topic}: {relay_error}")

                else:
                     logger.warning(f"Received message on unhandled topic: {topic_str}")

            # Catch errors outside specific topic handling (e.g., initial access to message.payload)
            except Exception as e:
                 logger.exception(f"Outer error processing message from topic {topic_str}")

            if stop_event.is_set():
                logger.info("Stop event set after processing, stopping message handler.")
                break
    except asyncio.CancelledError:
         logger.info("Message handler task cancelled.")
    except Exception as e:
         logger.exception("Error in message handler task.")
    finally:
         logger.info("Message handler task finished.")


async def run_service(
    mqtt_broker: str,
    mqtt_port: int,
    mqtt_username: Optional[str],
    mqtt_password: Optional[str],
    operating_mode: Optional[Literal['mqtt', 'ble']],
    default_image_request_topic: str,
    scan_request_topic: str,
    default_status_topic: str,
    gateway_base_topic: str,
    gateway_status_wildcard: str,
    eink_packet_delay_ms: int, 
    image_topic_map: Dict[str, str]
):
    """Main service loop connecting to MQTT and managing tasks."""
    if not operating_mode: 
        logger.error("Cannot run service, invalid operating mode.")
        return

    logger.info(f"Starting headless service in '{operating_mode}' mode.")
    logger.info(f"Listening for default image requests on: {default_image_request_topic}")
    logger.info(f"Listening for scan requests on: {scan_request_topic}")
    if image_topic_map:
        logger.info(f"Listening for mapped image requests on: {list(image_topic_map.keys())}")

    reconnect_interval = 5 
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
                hostname=mqtt_broker,
                port=mqtt_port,
                username=mqtt_username,
                password=mqtt_password,
            ) as client: 
                logger.info("MQTT client connected.")
                
                topics_to_subscribe = [
                    (scan_request_topic, 1),
                    (default_image_request_topic, 1),
                ]
                for topic in image_topic_map.keys():
                    topics_to_subscribe.append((topic, 1))
                
                if operating_mode == 'mqtt':
                    topics_to_subscribe.append((gateway_status_wildcard, 0))

                for topic, qos in topics_to_subscribe:
                    await client.subscribe(topic, qos=qos)
                    logger.info(f"Subscribed to topic: {topic} (QoS: {qos})")

                message_handler_task = asyncio.create_task(message_handler(
                    client, 
                    stop_event,
                    default_image_request_topic,
                    scan_request_topic,
                    image_topic_map,
                    gateway_status_wildcard,
                    default_status_topic, 
                    gateway_base_topic 
                ))

                stop_wait_task = asyncio.create_task(stop_event.wait())

                done, pending = await asyncio.wait(
                    [stop_wait_task, message_handler_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                if message_handler_task in done and not stop_event.is_set():
                    if stop_wait_task in pending:
                        stop_wait_task.cancel()
                    logger.warning("Message handler task finished unexpectedly.")
                    try:
                         message_handler_task.result()
                    except Exception as e:
                         logger.exception("Exception from message handler task:")

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
             if message_handler_task and not message_handler_task.done():
                  logger.warning("Main loop exiting, ensuring message handler task is cancelled.")
                  message_handler_task.cancel()
                  try:
                       await asyncio.wait_for(message_handler_task, timeout=1.0)
                  except Exception:
                       logger.warning("Exception/Timeout during final message handler cancellation.")

    logger.info("Service loop exiting.")
    logger.info("Service shutting down.")