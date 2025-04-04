# app/main.py
"""
Main entry point for the BLE E-Ink Sender Service.
Handles configuration loading, logging setup, and starting the service loop.
"""
import logging
import asyncio
import os
import json
import signal
from typing import Optional, Dict, Any, List, Literal

# --- Global State ---
# Stores asyncio.Event objects keyed by MAC address, signaling gateway readiness
gateway_ready_events: Dict[str, asyncio.Event] = {}
gateway_ready_lock = asyncio.Lock() # Protects access to gateway_ready_events
GATEWAY_CONNECT_TIMEOUT = 60.0 # Seconds to wait for gateway 'connected_ble' status

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__) # Define logger here for other modules to import

# --- Configuration ---
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_GATEWAY_BASE_TOPIC = os.getenv("MQTT_GATEWAY_BASE_TOPIC", "aintinksmart/gateway")
MQTT_REQUEST_TOPIC = os.getenv("MQTT_REQUEST_TOPIC", "aintinksmart/service/request/send_image")
MQTT_SCAN_REQUEST_TOPIC = os.getenv("MQTT_SCAN_REQUEST_TOPIC", "aintinksmart/service/request/scan")
MQTT_DEFAULT_STATUS_TOPIC = os.getenv("MQTT_DEFAULT_STATUS_TOPIC", "aintinksmart/service/status/default")
EINK_PACKET_DELAY_MS = int(os.getenv("EINK_PACKET_DELAY_MS", "20"))

USE_GATEWAY = os.getenv("USE_GATEWAY", "false").lower() == "true"
BLE_ENABLED = os.getenv("BLE_ENABLED", "true").lower() == "true"

OPERATING_MODE: Optional[Literal['mqtt', 'ble']] = None
if USE_GATEWAY and MQTT_BROKER:
    OPERATING_MODE = 'mqtt'
elif BLE_ENABLED:
    OPERATING_MODE = 'ble'
else:
    logger.error("Configuration Error: Neither USE_GATEWAY (with MQTT_BROKER) nor BLE_ENABLED is set. Service cannot operate.")
    OPERATING_MODE = None

# --- Derived Config ---
GATEWAY_STATUS_WILDCARD = f"{MQTT_GATEWAY_BASE_TOPIC}/display/+/status"


if __name__ == "__main__":
    # Import run_service here to avoid circular imports at module level
    try:
        from .service import run_service
    except ImportError as e:
         logger.error(f"Failed to import service components: {e}")
         logger.error("Ensure all service files (main.py, service.py, processing.py, etc.) are present in the 'app' directory.")
         exit(1)

    # Log operating mode only when run as main script
    if OPERATING_MODE == 'mqtt':
        logger.info("Operating Mode: MQTT Gateway")
    elif OPERATING_MODE == 'ble':
        logger.info("Operating Mode: Direct BLE")
    # else: Error already logged

    if OPERATING_MODE:
        logger.info("Starting service...")
        try:
             asyncio.run(run_service())
        except KeyboardInterrupt:
             logger.info("Service interrupted by user (KeyboardInterrupt).")
        except Exception as e:
             logger.exception("Unhandled exception during service execution.")
        finally:
             logger.info("Service shutdown complete.")
    else:
         logger.error("Service cannot start due to configuration error (no valid operating mode).")