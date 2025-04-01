"""
Pydantic models used by the FastAPI application.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Any, List
from . import config # For DEFAULT_COLOR_MODE

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