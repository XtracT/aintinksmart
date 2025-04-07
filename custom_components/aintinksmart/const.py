"""Constants for the Ain't Ink Smart integration."""
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "aintinksmart"

PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.CAMERA, # Optional, based on plan
]

# Configuration keys
CONF_MAC: Final = "mac_address"

# Default values
DEFAULT_NAME: Final = "Ain't Ink Smart Display"

# Status States (can be expanded)
STATE_IDLE: Final = "idle"
STATE_CONNECTING: Final = "connecting"
STATE_SENDING: Final = "sending_image"
STATE_ERROR: Final = "error"
STATE_SUCCESS: Final = "success" # Represents last send attempt success
STATE_UNAVAILABLE: Final = "unavailable" # Standard HA state

# Attributes
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_LAST_ERROR: Final = "last_error"

# Service Details
SERVICE_SEND_IMAGE: Final = "send_image"
ATTR_IMAGE_DATA: Final = "image_data"
ATTR_IMAGE_ENTITY_ID: Final = "image_entity_id"
ATTR_MODE: Final = "mode" # bw or bwr

# BLE Details
IMG_CHAR_UUID: Final = "00001525-1212-efde-1523-785feabcd123"
# NOTIFY_CHAR_UUID: Final = "00001526-1212-efde-1523-785feabcd123" # Add if needed later