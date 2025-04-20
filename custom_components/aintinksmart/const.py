"""Constants for the Ain't Ink Smart integration."""
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "aintinksmart"

PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.CAMERA,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH, # Add SWITCH platform
]

# Configuration keys
CONF_MAC: Final = "mac_address"
NUMBER_KEY_PACKET_DELAY = "packet_delay"
CONF_COMM_MODE: Final = "communication_mode"
CONF_MQTT_BASE_TOPIC: Final = "mqtt_base_topic"

# Default values
DEFAULT_NAME: Final = "Ain't Ink Smart Display"
DEFAULT_PACKET_DELAY_MS = 20
DEFAULT_COMM_MODE: Final = "ble" # Default to BLE
DEFAULT_MQTT_BASE_TOPIC: Final = "aintinksmart/gateway"

# Status States (can be expanded)
STATE_IDLE: Final = "idle"
STATE_CONNECTING: Final = "connecting"
STATE_SENDING: Final = "sending_image"
STATE_ERROR: Final = "error"
STATE_SUCCESS: Final = "success"  # Represents last send attempt success
STATE_ERROR_CONNECTION: Final = "connection_error"
STATE_ERROR_TIMEOUT: Final = "timeout_error"
STATE_ERROR_SEND: Final = "send_error"
STATE_ERROR_IMAGE_FETCH: Final = "image_fetch_error"
STATE_ERROR_IMAGE_PROCESS: Final = "image_process_error"
STATE_ERROR_UNKNOWN: Final = "unknown_error"
STATE_UNAVAILABLE: Final = "unavailable"  # Standard HA state

# Communication Modes
COMM_MODE_BLE: Final = "ble"
COMM_MODE_MQTT: Final = "mqtt"

# Attributes
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_LAST_ERROR: Final = "last_error"

# MQTT Topics
MQTT_BRIDGE_STATUS_TOPIC_SUFFIX: Final = "bridge/status"

# Sensor Keys (used in state_data and entity descriptions)
SENSOR_KEY_MQTT_DISPLAY_TRANSFER_STATUS: Final = "mqtt_display_transfer_status"

# Service Details
SERVICE_SEND_IMAGE: Final = "send_image"
ATTR_IMAGE_DATA: Final = "image_data"
ATTR_IMAGE_ENTITY_ID: Final = "image_entity_id"
ATTR_MODE: Final = "mode" # bw or bwr

# BLE Details
IMG_CHAR_UUID: Final = "00001525-1212-efde-1523-785feabcd123"
# NOTIFY_CHAR_UUID: Final = "00001526-1212-efde-1523-785feabcd123" # Add if needed later

# Entity Keys
KEY_AUTO_UPDATE_SWITCH: Final = "auto_update_switch"