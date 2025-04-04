# app/service.py
"""
Handles MQTT connection, message routing, status publishing, and the main service loop.
"""
import logging
import asyncio
import json
import signal
from typing import Optional, Dict, Any

import aiomqtt

# Import necessary components from other modules within the app package
from .main import (
    logger,
    OPERATING_MODE,
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_REQUEST_TOPIC,
    MQTT_SCAN_REQUEST_TOPIC,
    MQTT_DEFAULT_STATUS_TOPIC,
    MQTT_GATEWAY_BASE_TOPIC,
    GATEWAY_STATUS_WILDCARD,
    gateway_ready_events,
    gateway_ready_lock,
    USE_GATEWAY # Needed? Not directly used here, but maybe indirectly via OPERATING_MODE logic? Let's keep for now.
)
from .processing import process_request, process_scan_request


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
                # Schedule request processing in background tasks
                if message.topic.matches(MQTT_REQUEST_TOPIC):
                     logger.debug("Creating background task for process_request")
                     asyncio.create_task(process_request(client, payload_str, publish_status))
                elif message.topic.matches(MQTT_SCAN_REQUEST_TOPIC):
                     logger.debug("Creating background task for process_scan_request")
                     asyncio.create_task(process_scan_request(client, payload_str, publish_status))
                # --- Gateway Status Relay / Flow Control ---
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
                            # Publish the relayed status
                            await client.publish(MQTT_DEFAULT_STATUS_TOPIC, payload=json.dumps(relayed_payload), qos=0)


                        else:
                            logger.warning(f"Could not parse MAC from gateway status topic: {message.topic}")
                    except Exception as relay_error:
                        logger.exception(f"Error relaying gateway status from topic {message.topic}: {relay_error}")
                else:
                     logger.warning(f"Received message on unexpected topic: {message.topic}")
            except Exception as e:
                 logger.exception(f"Error processing message from topic {message.topic}")
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
                await client.subscribe(MQTT_REQUEST_TOPIC, qos=1)
                await client.subscribe(MQTT_SCAN_REQUEST_TOPIC, qos=1)
                logger.info(f"Subscribed to service request topics.")
                if OPERATING_MODE == 'mqtt':
                     await client.subscribe(GATEWAY_STATUS_WILDCARD, qos=0)
                     logger.info(f"Subscribed to gateway status topic: {GATEWAY_STATUS_WILDCARD}")

                # Start the message handler task
                message_handler_task = asyncio.create_task(message_handler(client, stop_event))

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
             if message_handler_task and not message_handler_task.done():
                  logger.warning("Main loop exiting, ensuring message handler task is cancelled.")
                  message_handler_task.cancel()
                  try:
                       await asyncio.wait_for(message_handler_task, timeout=1.0)
                  except Exception:
                       logger.warning("Exception/Timeout during final message handler cancellation.")

    logger.info("Service loop exiting.")
    logger.info("Service shutting down.")