"""
Configuration and constants for the BLE E-Ink Sender Service.
"""

# BLE Characteristic UUIDs
IMG_CHAR_UUID = "00001525-1212-efde-1523-785feabcd123"
NOTIFY_CHAR_UUID = "00001526-1212-efde-1523-785feabcd123"

# XOR Secret String (Required by device protocol)
# Note: This is a long string, potentially sensitive if the protocol is proprietary.
SECRET_STR = (
    "b8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97d60015bab2cdefb7ae0fcb099b599cc44"
    "d391645dde4b89b6e50f53dc046ec25acb8b26356ec4473bd3f36e6495d756703a4bb835139f0b161423b5f286c4e97"
    "d60015bab2cdefb7ae0fcb099b599ac44d391645dde4b89b6e50f53dc046ec25ac"
)

# CRC16 Calculation Table (Required by device protocol)
CRC_TABLE = [0, 32773, 32783, 10, 32795, 30, 20, 32785, 32819, 54, 60, 32825, 40, 32813, 32807, 34]

# Other Protocol Constants (Extracted from original script's build_ble_packets)
HEADER_PACKET_TYPE = bytes([0xFF, 0xFC])
HEADER_TAG = b"easyTag"
HEADER_PROTOCOL_BYTE_VAL = 98
HEADER_PROTOCOL_BYTE_INDEX = 9 # Index where the special byte is placed (not XORed)
HEADER_BT_ID = b"BT"
HEADER_LENGTH = 20
DATA_CHUNK_PAYLOAD_LENGTH = 200
DATA_CHUNK_TOTAL_LENGTH = 204 # Includes index and CRC

# Image Processing Defaults
DEFAULT_COLOR_MODE = "bwr"
IMAGE_PROCESSING_THRESHOLD = 128
PAD_MULTIPLE = 8 # Dimensions padded to nearest multiple of 8