import logging
import base64
import binascii
import io
import asyncio
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List

# Import bleak for scanning
from bleak import BleakScanner
from bleak.exc import BleakError

# Import our refactored core logic components
from . import config
from .image_processor import ImageProcessor, ImageProcessingError
from .protocol_formatter import ProtocolFormatter, ProtocolFormattingError
from .packet_builder import PacketBuilder, PacketBuilderError
from .ble_communicator import BleCommunicator, BleCommunicationError

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- FastAPI App Setup ---
app = FastAPI(
    title="BLE E-Ink Sender Service",
    description="API and Web UI to send images to BLE E-Ink displays.",
    version="0.2.0" # Version bump for new feature
)

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
    """Orchestrates the image processing and BLE sending logic."""
    results = {"status": "success", "message": ""}
    try:
        logger.info(f"Processing image for {mac_address} (mode: {mode})...")
        processor = ImageProcessor()
        processed_data = processor.process_image(image_bytes, mode)
        logger.info("Image processed successfully.")

        logger.info("Formatting protocol payload...")
        formatter = ProtocolFormatter()
        hex_payload = formatter.format_payload(processed_data)
        logger.info(f"Payload formatted (type: {hex_payload[:3]}...). Length: {len(hex_payload)}")

        logger.info("Building BLE packets...")
        builder = PacketBuilder()
        packets = builder.build_packets(hex_payload, mac_address)
        logger.info(f"{len(packets)} packets built successfully.")

        logger.info(f"Initiating BLE communication with {mac_address}...")
        communicator = BleCommunicator(mac_address)
        async with communicator:
            logger.info("Sending packets...")
            await communicator.send_packets(packets)
            results["message"] = f"Image successfully sent to {mac_address}."
            logger.info(results["message"])

    except (ImageProcessingError, ProtocolFormattingError, PacketBuilderError, BleCommunicationError) as e:
        logger.error(f"Error during image sending process: {e}")
        results["status"] = "error"
        results["message"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        results["status"] = "error"
        results["message"] = f"An unexpected server error occurred: {e}"
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {e}")

    return results

# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse, summary="Serves the main Web UI page")
async def get_web_ui(request: Request):
    logger.info("Serving Web UI page.")
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/discover_devices",
         response_model=List[DiscoveredDevice],
         summary="Scans for nearby BLE devices advertising 'easyTag'")
async def discover_devices():
    """Scans for BLE devices for 5 seconds and filters for 'easyTag'."""
    logger.info("Starting BLE device discovery...")
    discovered_devices = []
    try:
        # Scan for 5 seconds
        devices = await BleakScanner.discover(timeout=5.0)
        logger.info(f"Scan finished. Found {len(devices)} devices.")
        for device in devices:
            # Filter by name (case-insensitive check for 'easyTag')
            if device.name and device.name.lower().startswith("easytag"):
                logger.debug(f"Found matching device: Name={device.name}, Address={device.address}")
                discovered_devices.append(DiscoveredDevice(name=device.name, address=device.address))

    except BleakError as e:
        logger.error(f"BLE scanning failed: {e}")
        # Return 500 error if scanning itself fails
        raise HTTPException(status_code=500, detail=f"BLE scanning failed: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during device discovery: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected discovery error: {e}")

    logger.info(f"Returning {len(discovered_devices)} filtered devices.")
    return discovered_devices


@app.post("/send_image",
          response_model=ApiResponse,
          summary="Sends an image to a BLE device (accepts JSON or Form data)")
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
            temp_model = SendImageBaseRequest(mac_address=req_mac, mode=req_mode)
            req_mac = temp_model.mac_address
            req_mode = temp_model.mode
        except ValueError as e: # Catch validation errors from Pydantic model
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

    try:
        result = await process_and_send_image(req_mac, image_bytes, req_mode)
        return ApiResponse(status=result["status"], message=result["message"])
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception("Caught unexpected error at endpoint level.")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")

@app.get("/health", summary="Basic health check endpoint")
async def health_check():
    logger.debug("Health check endpoint called.")
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server directly (use 'uvicorn app.main:app --reload' for development)")
    uvicorn.run(app, host="0.0.0.0", port=8000)