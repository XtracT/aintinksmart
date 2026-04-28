"""Sensor platform for Ain't Ink Smart."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    STATE_IDLE,
    STATE_ERROR,
    STATE_SENDING,
    STATE_SUCCESS,
    STATE_CONNECTING,
    ATTR_LAST_UPDATE,
    ATTR_LAST_ERROR,
)
from .entity import AintinksmartEntity
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

SENSOR_STATUS_DESCRIPTION = SensorEntityDescription(
    key="status",
    name="Status",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    device_manager: AintinksmartDevice = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Setting up sensor for %s", device_manager.mac_address)

    sensors = [
        AintinksmartStatusSensor(device_manager),
    ]
    async_add_entities(sensors)


class AintinksmartStatusSensor(AintinksmartEntity, SensorEntity):
    """Representation of an Ain't Ink Smart Status Sensor."""

    entity_description = SENSOR_STATUS_DESCRIPTION

    def __init__(self, device_manager: AintinksmartDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device_manager)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
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
        return "mdi:bluetooth"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return device specific state attributes."""
        attrs = {}
        last_update = self._manager.state_data.get(ATTR_LAST_UPDATE)
        last_error = self._manager.state_data.get(ATTR_LAST_ERROR)

        if last_update and isinstance(last_update, datetime):
            attrs[ATTR_LAST_UPDATE] = last_update.isoformat()
        if last_error:
            attrs[ATTR_LAST_ERROR] = last_error
        return attrs
