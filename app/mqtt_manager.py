"""
Manages MQTT client connection, subscriptions, publishing, and state tracking
for E-Ink display transfers.
"""
import paho.mqtt.client as mqtt
import logging
import threading
import time
import json
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List, Any # Added List, Any

logger = logging.getLogger(__name__)

# --- Data Class for Transfer State (Copied from main.py) ---
@dataclass
class MqttTransferState:
    last_status: str = "unknown"
    error_occurred: bool = False
    last_update_time: float = 0.0
    # Optional: Add event for signaling completion/error if needed for more complex async handling
    # completion_event: asyncio.Event = field(default_factory=asyncio.Event)

class MqttManager:
    """Handles MQTT interactions and transfer state."""

    def __init__(self, broker: str, port: int, username: Optional[str], password: Optional[str], client_id_prefix: str = "ble-sender-service"):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.client_id = f"{client_id_prefix}-{time.time()}" # Basic unique ID
        self.client: Optional[mqtt.Client] = None
        self._is_connected = False

        # State Tracking
        self.active_transfers: Dict[str, MqttTransferState] = {}
        self.state_lock = threading.Lock()

        # Scan Results Storage
        self.scan_results: Dict[str, List[Dict[str, str]]] = {} # Keyed by a unique scan ID
        self.scan_results_lock = threading.Lock()

    def _on_connect(self, client, userdata, flags, rc):
        """Callback for MQTT connection."""
        if rc == 0:
            self._is_connected = True
            logger.info(f"MQTT connected successfully to {self.broker}:{self.port}")
            # Re-subscribe logic could be added here if needed
        else:
            self._is_connected = False
            logger.error(f"MQTT connection failed with code {rc}")
            # Potentially trigger reconnection attempts or notify application state

    def _on_disconnect(self, client, userdata, rc):
        """Callback for MQTT disconnection."""
        self._is_connected = False
        logger.warning(f"MQTT disconnected with result code {rc}")
        # Clear active transfer states on disconnect for safety
        with self.state_lock:
            self.active_transfers.clear()
            logger.warning("Cleared active MQTT transfer states due to disconnect.")
        # Potentially trigger reconnection attempts

    def _on_message(self, client, userdata, msg):
        """Callback for processing incoming MQTT messages (specifically status)."""
        topic = msg.topic
        try:
            payload = msg.payload.decode('utf-8')
            logger.debug(f"MQTT message received - Topic: {topic}, Payload: {payload}")

            # Expected status topic format: base/MAC_PART/status
            # We need the base topic to parse correctly. Assume it's passed or configured.
            # For now, let's parse assuming a known structure. This needs refinement.
            # TODO: Pass MQTT topic base config to MqttManager or make parsing more robust.
            # Assuming base topics are known for now for parsing.
            # Example: status_base = "eink_display", scan_result_topic = "eink_display/scan/result"
            status_base_topic = "eink_display" # Hardcoded for now, should be configurable
            scan_result_topic = f"{status_base_topic}/scan/result"
            topic_parts = topic.split('/')
            # Check if it's a transfer status topic
            if topic.startswith(status_base_topic) and topic.endswith("/status") and len(topic_parts) >= 3:
                mac_topic_part = topic_parts[-2] # MAC is second to last part
                with self.state_lock:
                    if mac_topic_part in self.active_transfers:
                        state = self.active_transfers[mac_topic_part]
                        state.last_status = payload
                        state.last_update_time = time.monotonic()
                        if payload.lower().startswith("error"):
                            state.error_occurred = True
                            logger.warning(f"Error status '{payload}' received for transfer {mac_topic_part}.")
                        logger.info(f"Updated status for {mac_topic_part}: '{payload}'")
                    else:
                        logger.debug(f"Received status for inactive/unknown transfer: {topic}")

            # Check if it's a scan result topic
            elif topic == scan_result_topic:
                 logger.debug(f"Received scan result: {payload}")
                 try:
                     device_info = json.loads(payload)
                     # TODO: Need a way to associate this with a specific scan request ID
                     # For now, storing in a general list under a default key 'current_scan'
                     # This assumes only one scan runs at a time.
                     scan_id = "current_scan" # Placeholder ID
                     with self.scan_results_lock:
                          if scan_id in self.scan_results:
                               # Add device info if it has name and address
                               if isinstance(device_info, dict) and "name" in device_info and "address" in device_info:
                                    # Avoid duplicates based on address
                                    address = device_info["address"]
                                    if not any(d.get("address") == address for d in self.scan_results[scan_id]):
                                         self.scan_results[scan_id].append(device_info)
                                         logger.info(f"Stored scan result for {address}")
                                    else:
                                         logger.debug(f"Duplicate scan result ignored for {address}")
                               else:
                                    logger.warning(f"Received invalid scan result format: {payload}")
                          else:
                               logger.warning(f"Received scan result but no active scan found for ID '{scan_id}'")

                 except json.JSONDecodeError:
                      logger.error(f"Failed to parse JSON scan result: {payload}")
                 except Exception as e:
                      logger.error(f"Error processing scan result: {e}", exc_info=True)

            else:
                 logger.debug(f"Ignoring message on unhandled topic: {topic}")

        except Exception as e:
            logger.error(f"Error processing MQTT message on topic {topic}: {e}", exc_info=True)

    def connect(self):
        """Connects the MQTT client."""
        if self._is_connected:
            logger.warning("MQTT client already connected.")
            return
        if not self.broker:
             logger.error("MQTT Broker address not configured.")
             raise ValueError("MQTT Broker address is required.")

        try:
            self.client = mqtt.Client(client_id=self.client_id)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            if self.username:
                self.client.username_pw_set(self.username, self.password)

            logger.info(f"Attempting MQTT connection to {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to initialize or connect MQTT client: {e}", exc_info=True)
            self.client = None
            self._is_connected = False
            raise ConnectionError(f"MQTT connection failed: {e}") from e

    def disconnect(self):
        """Disconnects the MQTT client."""
        if self.client:
            logger.info("Disconnecting MQTT client...")
            self.client.loop_stop()
            self.client.disconnect()
            self._is_connected = False # Ensure state is updated
            logger.info("MQTT client disconnected.")
        else:
             logger.warning("MQTT client not initialized, cannot disconnect.")

    def is_connected(self) -> bool:
        """Returns the connection status."""
        # Paho's is_connected() might not be reliable immediately after connect/disconnect
        # Using internal flag managed by callbacks is safer.
        return self._is_connected

    def subscribe(self, topic: str, qos: int = 1) -> Tuple[int, int]:
        """Subscribes to an MQTT topic."""
        if not self.client or not self._is_connected:
            logger.error("Cannot subscribe, MQTT client not connected.")
            raise ConnectionError("MQTT client not connected.")
        logger.debug(f"Subscribing to topic: {topic} (QoS: {qos})")
        result, mid = self.client.subscribe(topic, qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
             logger.error(f"Failed to subscribe to {topic}, error code: {result}")
        return result, mid

    def unsubscribe(self, topic: str) -> Tuple[int, int]:
        """Unsubscribes from an MQTT topic."""
        if not self.client: # Don't need to be connected to attempt unsubscribe
            logger.warning("Cannot unsubscribe, MQTT client not initialized.")
            return (mqtt.MQTT_ERR_INVAL, -1) # Indicate invalid state
        logger.debug(f"Unsubscribing from topic: {topic}")
        result, mid = self.client.unsubscribe(topic)
        if result != mqtt.MQTT_ERR_SUCCESS:
             logger.warning(f"Failed to unsubscribe from {topic}, error code: {result}")
        return result, mid

    def publish(self, topic: str, payload: Optional[str] = None, qos: int = 1, retain: bool = False) -> mqtt.MQTTMessageInfo:
        """Publishes a message to an MQTT topic."""
        if not self.client or not self._is_connected:
            logger.error("Cannot publish, MQTT client not connected.")
            raise ConnectionError("MQTT client not connected.")
        logger.debug(f"Publishing to topic: {topic} (QoS: {qos}) Payload: {payload[:50] if payload else 'None'}...")
        msg_info = self.client.publish(topic, payload, qos, retain)
        # Note: Paho automatically handles waiting for QoS 1/2 in the background loop
        # msg_info.wait_for_publish() can be used but blocks the calling thread.
        # We rely on the background loop and check msg_info.is_published() later if needed.
        return msg_info

    # --- State Management Methods ---

    def init_transfer_state(self, mac_topic_part: str):
        """Initializes the state for a new transfer."""
        with self.state_lock:
            if mac_topic_part in self.active_transfers:
                logger.warning(f"Overwriting existing transfer state for {mac_topic_part}.")
            self.active_transfers[mac_topic_part] = MqttTransferState(last_update_time=time.monotonic())
            logger.debug(f"Initialized transfer state for {mac_topic_part}")

    def get_transfer_state(self, mac_topic_part: str) -> Optional[MqttTransferState]:
        """Gets the current state for a transfer, returns None if not found."""
        with self.state_lock:
            # Return a copy to prevent external modification? Or trust caller?
            # For now, return direct reference under lock.
            return self.active_transfers.get(mac_topic_part)

    def update_last_action_time(self, mac_topic_part: str):
         """Updates the last update time for a transfer state."""
         with self.state_lock:
              if mac_topic_part in self.active_transfers:
                   self.active_transfers[mac_topic_part].last_update_time = time.monotonic()

    def remove_transfer_state(self, mac_topic_part: str) -> Optional[MqttTransferState]:
        """Removes the state for a completed/failed transfer, returning the final state."""
        with self.state_lock:
            state = self.active_transfers.pop(mac_topic_part, None)
            if state:
                 logger.debug(f"Removed transfer state for {mac_topic_part}. Final status was: {state.last_status}")
            else:
                 logger.warning(f"Attempted to remove non-existent transfer state for {mac_topic_part}")
            return state

    # --- Scan Result Methods ---

    def init_scan_results(self, scan_id: str = "current_scan"):
        """Clears previous results and prepares to collect new scan results."""
        with self.scan_results_lock:
            self.scan_results[scan_id] = []
            logger.info(f"Initialized scan results for ID: {scan_id}")

    def get_scan_results(self, scan_id: str = "current_scan") -> List[Dict[str, str]]:
        """Retrieves and clears the collected scan results for a given ID."""
        with self.scan_results_lock:
            results = self.scan_results.pop(scan_id, [])
            logger.info(f"Retrieved {len(results)} scan results for ID: {scan_id}")
            return results