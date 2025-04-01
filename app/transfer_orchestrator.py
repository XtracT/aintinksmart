"""
Orchestrates the process of sending an image to the E-Ink display,
coordinating image processing, packet building, and communication
via direct BLE and/or MQTT.
"""
import logging
import asyncio
import json
import binascii
import time # For monotonic clock
from typing import Dict, Any, List, Optional

from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError
from .mqtt_manager import MqttManager # Assuming MqttManager is passed in

# Import config for constants if needed directly, or rely on passed values
from . import config as app_config

logger = logging.getLogger(__name__)

class TransferOrchestratorError(Exception):
    """Custom exception for orchestration failures."""
    pass

async def orchestrate_image_transfer(
    mac_address: str,
    image_bytes: bytes,
    mode: str,
    mqtt_manager: Optional[MqttManager], # Pass manager instance
    ble_enabled: bool,
    mqtt_enabled: bool,
    mqtt_base_topic: str,
    packet_delay_ms: int,
    status_timeout_sec: int
) -> Dict[str, Any]:
    """
    Orchestrates image processing, packet building, and attempts sending
    via direct BLE (if enabled) and/or MQTT (if enabled using the provided manager).

    Returns:
        A dictionary containing 'status' ('success' or 'error') and 'message'.

    Raises:
        TransferOrchestratorError: For internal processing errors before communication attempts.
        ConnectionError: If MQTT manager is required but not connected.
    """
    # --- Configuration Check ---
    if not ble_enabled and not mqtt_enabled:
        logger.error("Orchestrator: Called but both BLE and MQTT are disabled.")
        # Raise HTTPException directly for client error
        from fastapi import HTTPException # Add import here for simplicity
        raise HTTPException(status_code=422, detail="Configuration Error: Neither direct BLE nor MQTT communication is enabled.")

    ble_success = False
    mqtt_published = False # Tracks if MQTT sequence completed without aborting
    final_mqtt_status = "not_attempted" # Default status if MQTT not enabled/used

    try:
        # 1. Process Image
        logger.info(f"Orchestrator: Processing image for {mac_address} (mode: {mode})...")
        processor = ImageProcessor()
        processed_data = processor.process_image(image_bytes, mode)
        logger.info("Orchestrator: Image processed successfully.")

        # 2. Format Payload
        logger.info("Orchestrator: Formatting protocol payload...")
        formatter = ProtocolFormatter()
        hex_payload = formatter.format_payload(processed_data)
        logger.info(f"Orchestrator: Payload formatted (type: {hex_payload[:3]}...). Length: {len(hex_payload)}")

        # 3. Build Packets
        logger.info("Orchestrator: Building BLE packets...")
        builder = PacketBuilder()
        packets_bytes_list = builder.build_packets(hex_payload, mac_address)
        logger.info(f"Orchestrator: {len(packets_bytes_list)} packets built successfully.")

    except (ImageProcessingError, ProtocolFormattingError, PacketBuilderError) as e:
        logger.error(f"Orchestrator: Error during image processing/packet building: {e}")
        # Re-raise as a specific orchestration error or let main handle HTTP exception?
        # Let's wrap it for clarity at this level.
        raise TransferOrchestratorError(f"Processing/Building failed: {e}") from e
    except Exception as e:
        logger.exception(f"Orchestrator: Unexpected error during processing/building: {e}")
        raise TransferOrchestratorError(f"Unexpected processing error: {e}") from e


    # --- Attempt MQTT Publishing (Using MqttManager) ---
    if mqtt_enabled and mqtt_manager:
        if not mqtt_manager.is_connected():
             logger.error("Orchestrator: MQTT Manager provided but not connected. Cannot proceed with MQTT.")
             # Raise connection error to be handled by the caller (main.py)
             raise ConnectionError("MQTT Manager is not connected.")

        mac_topic_part = mac_address.replace(":", "")
        start_topic = f"{mqtt_base_topic}/{mac_topic_part}/command/start"
        packet_topic = f"{mqtt_base_topic}/{mac_topic_part}/command/packet"
        end_topic = f"{mqtt_base_topic}/{mac_topic_part}/command/end"
        status_topic = f"{mqtt_base_topic}/{mac_topic_part}/status"
        delay_sec = packet_delay_ms / 1000.0

        mqtt_publish_success = True # Track if all publishes succeed
        transfer_aborted = False # Flag if stopped due to error/timeout
        final_mqtt_status = "unknown" # Reset status for this attempt

        mqtt_manager.init_transfer_state(mac_topic_part)

        try:
            logger.info(f"Orchestrator: Subscribing to status topic: {status_topic}")
            sub_result, _ = mqtt_manager.subscribe(status_topic, qos=1)
            if sub_result != 0: # MQTT_ERR_SUCCESS
                 logger.error(f"Orchestrator: Failed to subscribe to status topic {status_topic}, code: {sub_result}")
                 # Fail the MQTT part if subscription fails
                 raise TransferOrchestratorError(f"MQTT Error: Failed to subscribe to status topic {status_topic}")

            logger.info(f"Orchestrator: Starting MQTT transfer to {mac_address}...")

            # 1. Send Start command
            start_payload = json.dumps({"total_packets": len(packets_bytes_list)})
            logger.debug(f"Orchestrator: Publishing START to {start_topic}")
            try:
                mqtt_manager.publish(start_topic, payload=start_payload, qos=1)
                await asyncio.sleep(0.1) # Allow time for publish
                mqtt_manager.update_last_action_time(mac_topic_part)
            except Exception as pub_e:
                logger.warning(f"Orchestrator: START command publish failed: {pub_e}")
                mqtt_publish_success = False
                transfer_aborted = True
                final_mqtt_status = "error_publish_start"

            # 2. Send Packet commands
            if mqtt_publish_success:
                logger.info(f"Orchestrator: Sending {len(packets_bytes_list)} packets...")
                for i, packet_bytes in enumerate(packets_bytes_list):
                    # Check State Before Sending
                    state = mqtt_manager.get_transfer_state(mac_topic_part)
                    if not state:
                         logger.error(f"Orchestrator: State lost for {mac_topic_part}. Aborting.")
                         mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = "internal_error_state_lost"; break
                    current_time = time.monotonic()
                    if state.error_occurred:
                        logger.error(f"Orchestrator: ESP Error '{state.last_status}'. Aborting.")
                        mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = state.last_status; break
                    if current_time - state.last_update_time > status_timeout_sec:
                        logger.error(f"Orchestrator: Status Timeout. Last: '{state.last_status}'. Aborting.")
                        mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = "error_service_timeout"; break

                    # Send Packet
                    hex_packet_payload = binascii.hexlify(packet_bytes).upper().decode()
                    logger.debug(f"Orchestrator: Publishing PACKET {i+1}/{len(packets_bytes_list)}")
                    try:
                        mqtt_manager.publish(packet_topic, payload=hex_packet_payload, qos=1)
                        await asyncio.sleep(0.01) # Shorter delay
                        mqtt_manager.update_last_action_time(mac_topic_part)
                    except Exception as pub_e:
                        logger.warning(f"Orchestrator: PACKET {i+1} publish failed: {pub_e}")
                        mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = "error_publish_packet"; break

                    if i < len(packets_bytes_list) - 1: await asyncio.sleep(delay_sec)

                # 3. Send End command
                if mqtt_publish_success and not transfer_aborted:
                    logger.debug(f"Orchestrator: Publishing END to {end_topic}")
                    try:
                        mqtt_manager.publish(end_topic, payload="{}", qos=1)
                        await asyncio.sleep(0.1)
                        mqtt_manager.update_last_action_time(mac_topic_part)
                    except Exception as pub_e: logger.warning(f"Orchestrator: END publish failed: {pub_e}")

        except TransferOrchestratorError: # Catch specific subscribe error
             mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = "error_subscribe_status"
        except Exception as e:
            logger.exception(f"Orchestrator: Exception during MQTT publishing: {e}")
            mqtt_publish_success = False; transfer_aborted = True; final_mqtt_status = "error_exception_publish"
        finally:
            logger.info(f"Orchestrator: Cleaning up MQTT state for {mac_topic_part}...")
            if mqtt_manager:
                 mqtt_manager.unsubscribe(status_topic)
                 final_state = mqtt_manager.remove_transfer_state(mac_topic_part)
                 if final_state:
                     # Update final status if not already set by an error/abort reason
                     if final_mqtt_status == "unknown" or not final_mqtt_status.startswith("error"):
                          if final_state.error_occurred: final_mqtt_status = final_state.last_status if final_state.last_status.startswith("error") else "error_unknown"
                          elif not transfer_aborted: final_mqtt_status = final_state.last_status

        mqtt_published = mqtt_publish_success and not transfer_aborted
        if mqtt_published: logger.info(f"Orchestrator: MQTT sequence completed successfully for {mac_address}.")
        else: logger.error(f"Orchestrator: MQTT sequence FAILED/ABORTED for {mac_address}. Final Status: {final_mqtt_status}")

    # --- Attempt Direct BLE Sending ---
    if ble_enabled:
        logger.info(f"Orchestrator: Attempting direct BLE to {mac_address}...")
        try:
            communicator = BleCommunicator(mac_address)
            async with communicator:
                logger.info("Orchestrator: Sending packets via direct BLE...")
                await communicator.send_packets(packets_bytes_list)
                ble_success = True
                logger.info(f"Orchestrator: Image sent via direct BLE to {mac_address}.")
        except (BleakError, BleCommunicationError) as e:
            logger.warning(f"Orchestrator: Direct BLE failed: {e}.")
        except Exception as e:
             logger.exception(f"Orchestrator: Unexpected error during direct BLE: {e}")

    # --- Determine Final Status ---
    final_status = "error" # Default to error
    final_message = "Communication failed. Check logs." # Default message

    if ble_success:
        final_status = "success"
        final_message = f"Image sent successfully via direct BLE to {mac_address}."
        if mqtt_enabled:
            mqtt_detail = f"MQTT OK (Final ESP Status: {final_mqtt_status})" if mqtt_published else f"MQTT FAILED/ABORTED (Final ESP Status: {final_mqtt_status})"
            final_message += f" ({mqtt_detail})."
    elif mqtt_published: # MQTT succeeded and BLE failed/disabled
        final_status = "success"
        final_message = f"Image packets published successfully via MQTT for {mac_address}. Final ESP Status: {final_mqtt_status}."
        if ble_enabled: final_message = f"Direct BLE failed. {final_message}"
    else: # Neither BLE worked nor MQTT finished successfully
        final_status = "error"
        mqtt_error_detail = f"MQTT FAILED/ABORTED (Final ESP Status: {final_mqtt_status})" if mqtt_enabled else "MQTT disabled"
        ble_error_detail = "Direct BLE FAILED" if ble_enabled else "Direct BLE disabled"
        if ble_enabled and mqtt_enabled: final_message = f"{ble_error_detail} and {mqtt_error_detail}."
        elif ble_enabled: final_message = f"{ble_error_detail} ({mqtt_error_detail})."
        elif mqtt_enabled: final_message = f"{mqtt_error_detail} ({ble_error_detail})."
        else: final_message = "Neither direct BLE nor MQTT are enabled."
        if mqtt_enabled and not mqtt_manager: final_message += " MQTT Manager init failed."

    logger.info(f"Orchestrator Result: Status={final_status}, Message={final_message}")
    return {"status": final_status, "message": final_message}