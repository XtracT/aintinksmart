"""Constants for the Ain't Ink Smart integration."""
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "aintinksmart"

PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.CAMERA,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
]

# Configuration keys
CONF_MAC: Final = "mac_address"
NUMBER_KEY_PACKET_DELAY = "packet_delay"

# Default values
DEFAULT_NAME: Final = "Ain't Ink Smart Display"
DEFAULT_PACKET_DELAY_MS = 20

# Status States
STATE_IDLE: Final = "idle"
STATE_CONNECTING: Final = "connecting"
STATE_SENDING: Final = "sending_image"
STATE_ERROR: Final = "error"
STATE_SUCCESS: Final = "success"
STATE_ERROR_CONNECTION: Final = "connection_error"
STATE_ERROR_TIMEOUT: Final = "timeout_error"
STATE_ERROR_SEND: Final = "send_error"
STATE_ERROR_IMAGE_FETCH: Final = "image_fetch_error"
STATE_ERROR_IMAGE_PROCESS: Final = "image_process_error"
STATE_ERROR_UNKNOWN: Final = "unknown_error"
STATE_UNAVAILABLE: Final = "unavailable"

# Attributes
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_LAST_ERROR: Final = "last_error"

# Service Details
SERVICE_SEND_IMAGE: Final = "send_image"
ATTR_IMAGE_DATA: Final = "image_data"
ATTR_IMAGE_ENTITY_ID: Final = "image_entity_id"
ATTR_MODE: Final = "mode"

# BLE Details
IMG_CHAR_UUID: Final = "00001525-1212-efde-1523-785feabcd123"

# Entity Keys
KEY_AUTO_UPDATE_SWITCH: Final = "auto_update_switch"
