import logging
import base64
import binascii
import io
import asyncio
import os
import json
import time # <--- Added import for time.sleep()
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List

# Import bleak for scanning and direct BLE
from bleak import BleakScanner
from bleak.exc import BleakError

# Import MQTT client
import paho.mqtt.client as mqtt

# Import our refactored core logic components
from . import config # Still useful for some constants like UUIDs
from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError # Keep for direct BLE

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

# --- MQTT Client Setup ---
mqtt_client = None
if MQTT_ENABLED:
    try:
        mqtt_client = mqtt.Client(client_id="ble-sender-service") # Add protocol version if needed
        if MQTT_USERNAME:
            mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # Define basic callbacks (optional but good practice)
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info(f"MQTT connected successfully to {MQTT_BROKER}:{MQTT_PORT}")
            else:
                logger.error(f"MQTT connection failed with code {rc}")

        def on_disconnect(client, userdata, rc):
            logger.warning(f"MQTT disconnected with result code {rc}")
            # Consider adding reconnection logic here if needed for long-running tasks

        mqtt_client.on_connect = on_connect
        mqtt_client.on_disconnect = on_disconnect

        logger.info(f"Attempting MQTT connection to {MQTT_BROKER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start() # Start background thread for network loop
    except Exception as e:
        logger.error(f"Failed to initialize or connect MQTT client: {e}")
        mqtt_client = None # Ensure client is None if setup fails
        MQTT_ENABLED = False # Disable MQTT if connection fails at startup
else:
    logger.info("MQTT is disabled (MQTT_BROKER not set or MQTT_ENABLED=false).")

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
    if mqtt_client:
        logger.info("Disconnecting MQTT client...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Pydantic Models ---
class SendImageBaseRequest(BaseModel):
    mac_address: str = Field(..., description="Target device BLE MAC address (e.g., AA:BB:CC:DD:EE:FF)")
    mode: Optional[str] = config.DEFAULT_COLOR_MODE

    @validator('mac_address')
    def validate_mac_address(cls, v):
        import re
        if not re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', v):
            raise ValueError('Invalid MAC address format')
        return v.upper()

    @validator('mode')
    def validate_mode(cls, v):
        if v not in ['bw', 'bwr']:
            raise ValueError("Mode must be 'bw' or 'bwr'")
        return v

class SendImageApiRequest(SendImageBaseRequest):
    image_data: str = Field(..., description="Base64 encoded image data string")

class ApiResponse(BaseModel):
    status: str
    message: str
    details: Optional[Any] = None

class DiscoveredDevice(BaseModel):
    name: str
    address: str

# --- Helper Function for Core Logic ---
async def process_and_send_image(
    mac_address: str,
    image_bytes: bytes,
    mode: str
) -> Dict[str, Any]:
    """
    Orchestrates image processing, packet building, and attempts sending
    via direct BLE (if enabled) and/or MQTT (if enabled).
    """
    ble_success = False
    mqtt_published = False
    final_status = "error"
    final_message = "No communication methods enabled or configured."

    try:
        # 1. Process Image
        logger.info(f"Processing image for {mac_address} (mode: {mode})...")
        processor = ImageProcessor()
        processed_data = processor.process_image(image_bytes, mode)
        logger.info("Image processed successfully.")

        # 2. Format Payload
        logger.info("Formatting protocol payload...")
        formatter = ProtocolFormatter()
        hex_payload = formatter.format_payload(processed_data)
        logger.info(f"Payload formatted (type: {hex_payload[:3]}...). Length: {len(hex_payload)}")

        # 3. Build Packets
        logger.info("Building BLE packets...")
        builder = PacketBuilder()
        packets_bytes_list = builder.build_packets(hex_payload, mac_address)
        logger.info(f"{len(packets_bytes_list)} packets built successfully.")

        # --- Attempt MQTT Publishing (3-Topic Protocol for Custom Firmware) ---
        if MQTT_ENABLED and mqtt_client:
            mac_topic_part = mac_address.replace(":", "")
            start_topic = f"{MQTT_EINK_TOPIC_BASE}/{mac_topic_part}/command/start"
            packet_topic = f"{MQTT_EINK_TOPIC_BASE}/{mac_topic_part}/command/packet"
            end_topic = f"{MQTT_EINK_TOPIC_BASE}/{mac_topic_part}/command/end"
            delay_sec = EINK_PACKET_DELAY_MS / 1000.0

            logger.info(f"Starting MQTT transfer to {mac_address} via base topic {MQTT_EINK_TOPIC_BASE}...")
            mqtt_publish_success = True # Track overall success

            try:
                # 1. Send Start command with packet count
                start_payload = json.dumps({"total_packets": len(packets_bytes_list)})
                logger.debug(f"Publishing START to {start_topic} with payload: {start_payload}")
                msg_info_start = mqtt_client.publish(start_topic, payload=start_payload, qos=1)
                msg_info_start.wait_for_publish(timeout=5)
                if not msg_info_start.is_published():
                    logger.warning(f"START command publish failed or timed out (mid={msg_info_start.mid}).")
                    mqtt_publish_success = False
                else:
                    # 2. Send Packet commands
                    logger.info(f"Sending {len(packets_bytes_list)} packets with {EINK_PACKET_DELAY_MS}ms delay...")
                    for i, packet_bytes in enumerate(packets_bytes_list):
                        hex_payload = binascii.hexlify(packet_bytes).upper().decode()
                        logger.debug(f"Publishing PACKET {i+1}/{len(packets_bytes_list)} to {packet_topic}")
                        msg_info_packet = mqtt_client.publish(packet_topic, payload=hex_payload, qos=1)
                        # Wait for confirmation before logging success and sleeping
                        msg_info_packet.wait_for_publish(timeout=5)
                        if not msg_info_packet.is_published():
                            logger.warning(f"PACKET {i+1} publish failed or timed out (mid={msg_info_packet.mid}).")
                            mqtt_publish_success = False
                            break # Stop sending packets if one fails
                        else:
                            logger.debug(f"PACKET {i+1} publish confirmed.") # Add confirmation log

                        # Delay before sending the next packet
                        if i < len(packets_bytes_list) - 1:
                            time.sleep(delay_sec)

                    # 3. Send End command (optional, firmware now relies on count)
                    if mqtt_publish_success:
                        logger.debug(f"Publishing END to {end_topic}")
                        logger.debug(f"Publishing END to {end_topic}")
                        msg_info_end = mqtt_client.publish(end_topic, payload="{}", qos=1)
                        msg_info_end.wait_for_publish(timeout=5)
                        if not msg_info_end.is_published():
                            logger.warning(f"END command publish failed or timed out (mid={msg_info_end.mid}).")
                            mqtt_publish_success = False

            except Exception as e:
                logger.exception(f"Exception during MQTT 3-topic publishing: {e}")
                mqtt_publish_success = False

            mqtt_published = mqtt_publish_success # Set overall flag
            if mqtt_published:
                 logger.info(f"MQTT transfer sequence completed for {mac_address}.")
            else:
                 logger.error(f"MQTT transfer sequence failed or was interrupted for {mac_address}.")

        # --- Attempt Direct BLE Sending ---
        if BLE_ENABLED:
            logger.info(f"Attempting direct BLE communication with {mac_address}...")
            try:
                communicator = BleCommunicator(mac_address)
                async with communicator: # Handles connect/disconnect
                    logger.info("Sending packets via direct BLE...")
                    await communicator.send_packets(packets_bytes_list)
                    ble_success = True
                    logger.info(f"Image successfully sent to {mac_address} via direct BLE.")
            except (BleakError, BleCommunicationError) as e:
                logger.warning(f"Direct BLE communication failed: {e}. "
                               f"{'Relying on MQTT if configured.' if MQTT_ENABLED else 'MQTT not configured.'}")
            except Exception as e:
                 logger.exception(f"Unexpected error during direct BLE communication: {e}")
                 # Log full traceback for unexpected errors

        # --- Determine Final Status (Updated for 3-Topic MQTT) ---
        if ble_success:
            final_status = "success"
            final_message = f"Image sent successfully via direct BLE to {mac_address}."
            if mqtt_published:
                final_message += f" (Also published via MQTT to base topic {MQTT_EINK_TOPIC_BASE})."
            elif MQTT_ENABLED:
                 final_message += f" (MQTT publishing failed or was skipped - Base Topic: {MQTT_EINK_TOPIC_BASE})."
        elif mqtt_published:
            final_status = "success" # Treat MQTT publish as success if BLE failed/disabled
            final_message = f"Image packets published successfully via MQTT (Base Topic: {MQTT_EINK_TOPIC_BASE}) for {mac_address}."
            if BLE_ENABLED: # If BLE was enabled but failed
                 final_message = f"Direct BLE failed. {final_message}"
        else:
            # Neither worked or was enabled/configured properly
            final_status = "error"
            if BLE_ENABLED and not MQTT_ENABLED:
                 final_message = "Direct BLE communication failed and MQTT is not configured/enabled."
            elif not BLE_ENABLED and MQTT_ENABLED:
                 final_message = f"MQTT publishing failed (Base Topic: {MQTT_EINK_TOPIC_BASE}) and direct BLE is disabled."
            elif BLE_ENABLED and MQTT_ENABLED:
                 final_message = f"Both direct BLE communication and MQTT publishing failed (Base Topic: {MQTT_EINK_TOPIC_BASE})."
            elif not BLE_ENABLED and not MQTT_ENABLED:
                 final_message = "Neither direct BLE nor MQTT are enabled/configured."
            elif MQTT_ENABLED and not mqtt_client:
                 final_message = "MQTT is enabled but client failed to initialize/connect."
            else: # Catch-all for unexpected state
                 final_message = "Communication failed. Check logs for details."


    except (ImageProcessingError, ProtocolFormattingError, PacketBuilderError) as e:
        logger.error(f"Error during image processing/packet building: {e}")
        raise HTTPException(status_code=500, detail=str(e)) # These are server errors
    except Exception as e:
        logger.exception(f"An unexpected error occurred in process_and_send_image: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {e}")

    # Raise HTTPException if the final status is error
    if final_status == "error":
         raise HTTPException(status_code=500, detail=final_message)

    return {"status": final_status, "message": final_message}


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
         summary="Scans for nearby BLE devices advertising 'easyTag'")
async def discover_devices():
    """Scans for BLE devices for 5 seconds and filters for 'easyTag'."""
    if not BLE_ENABLED:
         logger.warning("Discovery endpoint called but direct BLE is disabled.")
         raise HTTPException(status_code=403, detail="Direct BLE is disabled in server configuration.")

    logger.info("Starting BLE device discovery...")
    discovered_devices = []
    try:
        devices = await BleakScanner.discover(timeout=5.0)
        logger.info(f"Scan finished. Found {len(devices)} devices.")
        for device in devices:
            if device.name and device.name.lower().startswith("easytag"):
                logger.debug(f"Found matching device: Name={device.name}, Address={device.address}")
                discovered_devices.append(DiscoveredDevice(name=device.name, address=device.address))
    except BleakError as e:
        logger.error(f"BLE scanning failed: {e}")
        raise HTTPException(status_code=500, detail=f"BLE scanning failed: {e}. Ensure service has BLE access.")
    except Exception as e:
        logger.exception(f"Unexpected error during device discovery: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected discovery error: {e}")

    logger.info(f"Returning {len(discovered_devices)} filtered devices.")
    return discovered_devices


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

    # --- Execute Core Logic ---
    try:
        result = await process_and_send_image(req_mac, image_bytes, req_mode)
        # process_and_send_image now raises HTTPException on failure
        return ApiResponse(status=result["status"], message=result["message"])
    except HTTPException as e:
        # Re-raise HTTP exceptions directly
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Caught unexpected error at endpoint level.")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")


@app.get("/health", summary="Basic health check endpoint")
async def health_check():
    logger.debug("Health check endpoint called.")
    mqtt_status = "connected" if MQTT_ENABLED and mqtt_client and mqtt_client.is_connected() else "disconnected/disabled"
    ble_status = "enabled" if BLE_ENABLED else "disabled"
    return {"status": "ok", "ble_direct": ble_status, "mqtt": mqtt_status}

# --- Main Execution Guard ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server directly (use 'uvicorn app.main:app --reload' for development)")
    # Note: Environment variables should be set before running this directly
    uvicorn.run(app, host="0.0.0.0", port=8000)