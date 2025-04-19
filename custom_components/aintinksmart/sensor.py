"""Sensor platform for Ain't Ink Smart."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any # Import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription, # Import EntityDescription
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE # Import standard unavailable state
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util # For timezone handling

# Import constants and base entity
from .const import (
    DOMAIN,
    STATE_IDLE,
    STATE_ERROR,
    STATE_SENDING,
    STATE_SUCCESS,
    STATE_CONNECTING,
    # STATE_UNAVAILABLE is imported from const
    ATTR_LAST_UPDATE,
    ATTR_LAST_ERROR,
    COMM_MODE_MQTT, # Added
)
from .entity import AintinksmartEntity
# Import device manager type hint safely
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

# Define sensor descriptions
SENSOR_STATUS_DESCRIPTION = SensorEntityDescription(
    key="status", # Used for unique_id in base class
    name="Status", # Used if _attr_has_entity_name=False
    # device_class=SensorDeviceClass.ENUM, # Consider if states fit an existing class
    # options=[STATE_IDLE, STATE_CONNECTING, STATE_SENDING, STATE_SUCCESS, STATE_ERROR, STATE_UNAVAILABLE], # If using ENUM
)

SENSOR_MQTT_BRIDGE_STATUS_DESCRIPTION = SensorEntityDescription( # Added
    key="mqtt_bridge_status", # Added
    name="MQTT Gateway Status", # Added
    icon="mdi:mqtt", # Added
    # device_class=SensorDeviceClass.ENUM, # Added - depends on possible values
    # options=["online", "offline", "connecting"], # Added - example options
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    # Get the device manager instance stored in __init__
    device_manager: AintinksmartDevice = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Setting up sensor for %s", device_manager.mac_address)

    sensors = [
        AintinksmartStatusSensor(device_manager), # Pass the manager instance
    ]

    # Add MQTT Gateway Status sensor only if communication mode is MQTT
    if device_manager._comm_mode == COMM_MODE_MQTT: # Accessing protected member for simplicity in example
         _LOGGER.debug("[%s] Adding MQTT Gateway Status sensor", device_manager.mac_address)
         sensors.append(AintinksmartMqttGatewayStatusSensor(device_manager)) # Added

    async_add_entities(sensors)


class AintinksmartStatusSensor(AintinksmartEntity, SensorEntity):
    """Representation of an Ain't Ink Smart Status Sensor."""

    entity_description = SENSOR_STATUS_DESCRIPTION # Assign description

    def __init__(self, device_manager: AintinksmartDevice) -> None:
        """Initialize the sensor."""
        # Pass manager to the base class __init__
        super().__init__(device_manager)
        # Unique ID is now handled by the base class using entity_description.key

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        # Get state directly from the device manager's state data property
        return self._manager.state_data.get("status", STATE_UNAVAILABLE)

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend, based on the state."""
        state = self.native_value
        if state == STATE_SENDING:
            return "mdi:sync"
        if state == STATE_CONNECTING:
            return "mdi:bluetooth-connect"
        if state == STATE_SUCCESS:
            return "mdi:check-circle-outline"
        if state == STATE_ERROR:
            return "mdi:alert-circle-outline"
        if state == STATE_UNAVAILABLE:
            return "mdi:bluetooth-off"
        return "mdi:bluetooth" # Default/Idle icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return device specific state attributes."""
        # Get attributes directly from the device manager's state data property
        attrs = {}
        last_update = self._manager.state_data.get(ATTR_LAST_UPDATE)
        last_error = self._manager.state_data.get(ATTR_LAST_ERROR)

        if last_update and isinstance(last_update, datetime):
            attrs[ATTR_LAST_UPDATE] = last_update.isoformat()
        if last_error:
            attrs[ATTR_LAST_ERROR] = last_error
        return attrs

    # No need for _handle_coordinator_update here anymore,
    # the base class handles async_write_ha_state via the listener pattern


class AintinksmartMqttGatewayStatusSensor(AintinksmartEntity, SensorEntity): # Added
    """Representation of the MQTT Gateway Status Sensor.""" # Added

    entity_description = SENSOR_MQTT_BRIDGE_STATUS_DESCRIPTION # Added

    def __init__(self, device_manager: AintinksmartDevice) -> None: # Added
        """Initialize the sensor.""" # Added
        super().__init__(device_manager) # Added

    @property # Added
    def native_value(self) -> StateType: # Added
        """Return the state of the sensor.""" # Added
        # Get state directly from the device manager's state data property
        return self._manager.state_data.get("mqtt_bridge_status", STATE_UNAVAILABLE) # Added

    @property # Added
    def available(self) -> bool: # Added
        """Return True if the sensor is available.""" # Added
        # The sensor is available if the bridge status is not the initial unavailable state
        return self.native_value != STATE_UNAVAILABLE # Added

