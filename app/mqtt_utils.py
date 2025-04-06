# app/mqtt_utils.py
"""
MQTT Utility functions, including status publishing.
"""
import logging
import json
from typing import Optional, Dict, Any, Callable, Coroutine

import aiomqtt

logger = logging.getLogger(__name__) # Use a logger specific to this module

async def publish_status(client: aiomqtt.Client, mac: str, status_msg: str, details: Optional[Dict] = None, default_status_topic: Optional[str] = None):
    """Helper to publish status to the default topic."""
    # Use the passed default_status_topic argument if provided, otherwise fallback (needs import)
    # Import config value directly here if needed, or rely on it being passed.
    # For simplicity, let's assume it MUST be passed or is None.
    
    actual_default_status_topic = default_status_topic 

    if not actual_default_status_topic:
        logger.debug(f"Status for {mac}: {status_msg} - Details: {details} (Not published: default topic unknown)")
        return 
    try:
        payload = {"mac_address": mac, "status": status_msg}
        if details:
            payload.update({k: v for k, v in details.items() if k not in ['mac_address', 'status']})
            # Prioritize status_msg and mac passed to function
            payload["status"] = status_msg 
            payload["mac_address"] = mac
            
        logger.debug(f"Publishing status: {payload} to {actual_default_status_topic}")
        
        if not isinstance(client, aiomqtt.Client):
             logger.error(f"CRITICAL: Invalid MQTT client object passed to publish_status. Expected aiomqtt.Client, got Type: {type(client)}. MAC: {mac}, Status: {status_msg}")
             return 

        await client.publish(actual_default_status_topic, payload=json.dumps(payload), qos=0)

    except Exception as e:
        logger.error(f"Failed to publish default status (Client type: {type(client)}): {e}", exc_info=True)