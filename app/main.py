import logging
import base64
import binascii
import io
import asyncio
import os
import json
import time # Already imported, ensure it's there
# import threading # Moved to MqttManager
# from dataclasses import dataclass, field # Moved to MqttManager
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
# from pydantic import BaseModel, Field, validator # No longer needed directly here for these models
from typing import Optional, Dict, Any, List

# Import bleak for scanning and direct BLE
from bleak import BleakScanner
from bleak.exc import BleakError

# Import MQTT client
# import paho.mqtt.client as mqtt # Handled by MqttManager

# Import our refactored core logic components
from . import config # Still useful for some constants like UUIDs
from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError # Keep for direct BLE
from .models import SendImageBaseRequest, SendImageApiRequest, ApiResponse, DiscoveredDevice # Import models
from .mqtt_manager import MqttManager # Don't need MqttTransferState here anymore
from .transfer_orchestrator import orchestrate_image_transfer, TransferOrchestratorError # Import orchestrator

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration from Environment Variables ---
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
# MQTT_COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC", "ble_sender/command/send_image") # Removed
# New variables for 3-topic protocol
MQTT_EINK_TOPIC_BASE = os.getenv("MQTT_EINK_TOPIC_BASE", "eink_display") # Base for eink topics
EINK_PACKET_DELAY_MS = int(os.getenv("EINK_PACKET_DELAY_MS", "20")) # Default delay between packet messages set to 20ms
MQTT_STATUS_TIMEOUT_SEC = int(os.getenv("MQTT_STATUS_TIMEOUT_SEC", "60")) # Timeout for status updates (e.g., 60 seconds)

# --- State Tracking (Moved to MqttManager) ---

# Determine if direct BLE should be attempted
BLE_ENABLED = os.getenv("BLE_ENABLED", "true").lower() == "true"

# Determine if MQTT should be enabled (Logic remains the same, based on MQTT_BROKER)
_mqtt_enabled_env = os.getenv("MQTT_ENABLED", "").lower() # Get value, default to empty string if unset
if MQTT_BROKER:
    if _mqtt_enabled_env == "false":
        # Explicitly disabled via environment variable
        MQTT_ENABLED = False
        logger.info("MQTT is disabled (MQTT_ENABLED=false).")
    else:
        # Enable if MQTT_BROKER is set and MQTT_ENABLED is not explicitly "false"
        # This covers cases where MQTT_ENABLED is unset or set to "true" (or anything else)
        MQTT_ENABLED = True
        logger.info("MQTT is enabled (MQTT_BROKER is set and MQTT_ENABLED is not 'false').")
else:
    # Disabled because MQTT_BROKER is not set
    MQTT_ENABLED = False
    logger.info("MQTT is disabled (MQTT_BROKER not set).")

# --- MQTT Manager Setup ---
mqtt_manager: Optional[MqttManager] = None
if MQTT_ENABLED:
    try:
        mqtt_manager = MqttManager(
            broker=MQTT_BROKER,
            port=MQTT_PORT,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD
        )
        mqtt_manager.connect()
        # Don't check connection status immediately here, as connect() runs in background.
        # Rely on checks within the orchestrator or health check later.
    except Exception as e:
        logger.error(f"Failed to initialize or connect MqttManager: {e}", exc_info=True)
        mqtt_manager = None
        MQTT_ENABLED = False # Disable MQTT if setup fails
else:
    logger.info("MQTT is disabled by configuration (MQTT_BROKER not set or MQTT_ENABLED=false).")

if not BLE_ENABLED:
    logger.info("Direct BLE is disabled (BLE_ENABLED=false).")


# --- FastAPI App Setup ---
app = FastAPI(
    title="BLE E-Ink Sender Service (Hybrid)",
    description="API/Web UI to send images to BLE E-Ink displays via direct BLE and/or MQTT.",
    version="0.3.0" # Version bump for hybrid feature
)

@app.on_event("shutdown")
def shutdown_event():
    if mqtt_manager:
        mqtt_manager.disconnect()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Pydantic Models (Moved to app/models.py) ---

# --- Helper Function (Moved to app/transfer_orchestrator.py) ---


# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse, summary="Serves the main Web UI page")
async def get_web_ui(request: Request):
    logger.info("Serving Web UI page.")
    # Pass enabled features to template if needed for UI adjustments
    return templates.TemplateResponse("index.html", {
        "request": request,
        "ble_enabled": BLE_ENABLED,
        "mqtt_enabled": MQTT_ENABLED
        })

@app.get("/discover_devices",
         response_model=List[DiscoveredDevice],
         summary="Scans for nearby BLE devices advertising 'easyTag' via direct BLE and/or MQTT gateway")
async def discover_devices():
    """
    Scans for BLE devices advertising 'easyTag'.
    Uses direct BLE scan if BLE_ENABLED=true.
    Uses MQTT gateway scan if MQTT_ENABLED=true.
    Combines results.
    """
    # Allow discovery if EITHER BLE or MQTT is enabled
    if not BLE_ENABLED and not MQTT_ENABLED:
         logger.warning("Discovery endpoint called but both BLE and MQTT are disabled.")
         raise HTTPException(status_code=403, detail="Configuration Error: Neither direct BLE nor MQTT discovery is enabled.")

    all_found_devices: Dict[str, DiscoveredDevice] = {} # Use dict to handle duplicates by MAC

    # --- Direct BLE Scan ---
    if BLE_ENABLED:
        logger.info("Starting direct BLE device discovery...")
        try:
            direct_devices = await BleakScanner.discover(timeout=5.0)
            logger.info(f"Direct scan finished. Found {len(direct_devices)} devices.")
            for device in direct_devices:
                # Filter devices based on name (case-insensitive)
                if device.name and device.name.lower().startswith("easytag"):
                    logger.debug(f"Direct Found: Name={device.name}, Address={device.address}")
                    # Add/update in dict, ensuring address is uppercase for consistent key
                    all_found_devices[device.address.upper()] = DiscoveredDevice(name=device.name, address=device.address.upper())
        except BleakError as e:
            logger.error(f"Direct BLE scanning failed: {e}. Continuing with MQTT if enabled.")
            # Don't raise HTTPException here, allow MQTT scan to proceed if enabled
        except Exception as e:
            logger.exception(f"Unexpected error during direct BLE discovery: {e}. Continuing with MQTT if enabled.")

    # --- MQTT Gateway Scan ---
    if MQTT_ENABLED and mqtt_manager:
        if not mqtt_manager.is_connected():
             logger.warning("MQTT discovery requested but manager is not connected. Skipping.")
        else:
            logger.info("Starting MQTT gateway device discovery...")
            scan_result_topic = f"{MQTT_EINK_TOPIC_BASE}/scan/result"
            scan_command_topic = f"{MQTT_EINK_TOPIC_BASE}/scan/command"
            # Use scan duration from ESP + buffer time
            # TODO: Make SCAN_DURATION_SECONDS available from config if possible
            scan_wait_time = 18 # ESP scans for 15s (SCAN_DURATION_SECONDS), wait a bit longer
            scan_id = "current_scan" # Simple ID for now

            try:
                # Prepare to receive results
                mqtt_manager.init_scan_results(scan_id)

                # Subscribe to results
                sub_result, _ = mqtt_manager.subscribe(scan_result_topic, qos=0) # QoS 0 is fine for discovery
                if sub_result != 0:
                     logger.error(f"Failed to subscribe to MQTT scan result topic: {scan_result_topic}")
                     # Proceed without MQTT scan if subscribe fails
                else:
                    try:
                        # Publish scan command
                        logger.info(f"Publishing scan command to {scan_command_topic}")
                        mqtt_manager.publish(scan_command_topic, payload="", qos=0)

                        # Wait for results
                        logger.info(f"Waiting {scan_wait_time} seconds for MQTT scan results...")
                        await asyncio.sleep(scan_wait_time)

                    finally:
                        # Unsubscribe regardless of publish success/failure after waiting
                        logger.debug(f"Unsubscribing from {scan_result_topic}")
                        mqtt_manager.unsubscribe(scan_result_topic)

                    # Get results collected during the wait
                    mqtt_results = mqtt_manager.get_scan_results(scan_id)
                    logger.info(f"MQTT scan finished. Received {len(mqtt_results)} results.")

                    # Add MQTT results to the combined dictionary
                    for device_info in mqtt_results:
                         # Ensure address is uppercase for consistent key
                         address_upper = device_info.get("address", "").upper()
                         if address_upper:
                              # Add/update in dict
                              all_found_devices[address_upper] = DiscoveredDevice(
                                   name=device_info.get("name", "Unknown"),
                                   address=address_upper
                              )

            except ConnectionError as e:
                 logger.error(f"MQTT Connection Error during discovery: {e}")
                 # Don't raise, just log that MQTT scan failed
            except Exception as e:
                 logger.exception(f"Unexpected error during MQTT discovery: {e}")
                 # Don't raise, just log

    # Convert combined dictionary values back to a list
    final_device_list = list(all_found_devices.values())
    logger.info(f"Returning {len(final_device_list)} unique discovered devices.")
    return final_device_list


@app.post("/send_image",
          response_model=ApiResponse,
          summary="Sends an image to a BLE device (via direct BLE and/or MQTT)")
async def send_image_endpoint(
    mac_address: Optional[str] = Form(None),
    mode: Optional[str] = Form(config.DEFAULT_COLOR_MODE),
    image_file: Optional[UploadFile] = File(None),
    request_data: Optional[SendImageApiRequest] = None # For JSON body
    ):
    logger.info("Received request to /send_image")
    image_bytes: bytes
    req_mac: str
    req_mode: str

    # Determine request source and extract data
    if request_data: # JSON request
        logger.info("Processing JSON API request.")
        req_mac = request_data.mac_address
        req_mode = request_data.mode
        try:
            image_bytes = base64.b64decode(request_data.image_data)
            logger.info(f"Decoded Base64 image data ({len(image_bytes)} bytes).")
        except (binascii.Error, TypeError) as e:
            logger.error(f"Invalid Base64 image data received: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid Base64 image data: {e}")
        except Exception as e:
             logger.error(f"Error decoding Base64: {e}")
             raise HTTPException(status_code=400, detail=f"Error decoding Base64: {e}")

    elif image_file and mac_address: # Form data request
        logger.info("Processing Form data request.")
        req_mac = mac_address
        req_mode = mode or config.DEFAULT_COLOR_MODE
        try:
            # Validate form data using Pydantic model
            temp_model = SendImageBaseRequest(mac_address=req_mac, mode=req_mode)
            req_mac = temp_model.mac_address
            req_mode = temp_model.mode
        except ValueError as e:
             logger.warning(f"Form data validation failed: {e}")
             raise HTTPException(status_code=400, detail=f"Invalid form data: {e}")

        contents = await image_file.read()
        image_bytes = contents
        logger.info(f"Read image file '{image_file.filename}' ({len(image_bytes)} bytes).")
        await image_file.close()
    else:
        logger.warning("Invalid request to /send_image. Missing JSON body or form fields.")
        raise HTTPException(status_code=400, detail="Invalid request. Provide JSON body or form data (mac_address, image_file).")

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image data/file is empty.")

    # --- Pre-check: MQTT configured but failed to connect? ---
    # Check if MQTT was intended to be enabled (broker set) but manager is None (init/connect failed)
    if MQTT_BROKER and not mqtt_manager:
         logger.error("MQTT is configured but manager failed to initialize/connect. Aborting request.")
         raise HTTPException(status_code=503, detail="MQTT Service Unavailable: Failed to connect to broker during startup.")

    # --- Execute Core Logic via Orchestrator ---
    try:
        result = await orchestrate_image_transfer(
            mac_address=req_mac,
            image_bytes=image_bytes,
            mode=req_mode,
            mqtt_manager=mqtt_manager, # Pass the manager instance
            ble_enabled=BLE_ENABLED,
            mqtt_enabled=MQTT_ENABLED,
            mqtt_base_topic=MQTT_EINK_TOPIC_BASE,
            packet_delay_ms=EINK_PACKET_DELAY_MS,
            status_timeout_sec=MQTT_STATUS_TIMEOUT_SEC
        )
        # orchestrate_image_transfer returns dict with status and message
        return ApiResponse(status=result["status"], message=result["message"])
    except TransferOrchestratorError as e:
         logger.error(f"Orchestration failed: {e}")
         raise HTTPException(status_code=500, detail=f"Transfer failed: {e}")
    except ConnectionError as e: # Catch MQTT connection errors
         logger.error(f"MQTT Connection Error during transfer: {e}")
         raise HTTPException(status_code=503, detail=f"MQTT Service Unavailable: {e}")
    except HTTPException as e:
        # Re-raise HTTP exceptions directly (e.g., validation errors)
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Caught unexpected error at /send_image endpoint level.")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")


@app.get("/health", summary="Basic health check endpoint")
async def health_check():
    logger.debug("Health check endpoint called.")
    # Use mqtt_manager instance to check status
    mqtt_status = "connected" if MQTT_ENABLED and mqtt_manager and mqtt_manager.is_connected() else "disconnected/disabled"
    ble_status = "enabled" if BLE_ENABLED else "disabled"
    return {"status": "ok", "ble_direct": ble_status, "mqtt": mqtt_status}

# --- Main Execution Guard ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server directly (use 'uvicorn app.main:app --reload' for development)")
    # Note: Environment variables should be set before running this directly
    uvicorn.run(app, host="0.0.0.0", port=8000)