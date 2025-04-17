"""Number platform for Ain't Ink Smart."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity # Correct import
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

# Import constants and base entity
from .const import DOMAIN, NUMBER_KEY_PACKET_DELAY, DEFAULT_PACKET_DELAY_MS
from .entity import AintinksmartEntity

# Import device manager type hint safely
if TYPE_CHECKING:
    from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

# Define the number entity description
NUMBER_ENTITY_DESCRIPTION = NumberEntityDescription(
    key=NUMBER_KEY_PACKET_DELAY,
    name="Packet Delay",
    icon="mdi:timer-outline",
    native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    native_min_value=1.0,  # Use float for RestoreNumberEntity compatibility
    native_max_value=500.0, # Increased max based on potential proxy needs
    native_step=1.0,
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    # Get the device manager instance stored in __init__
    device_manager: AintinksmartDevice = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Setting up number entity for %s", device_manager.mac_address)

    entities = [
        AintInkSmartPacketDelayNumber(device_manager),
    ]
    async_add_entities(entities)


class AintInkSmartPacketDelayNumber(AintinksmartEntity, NumberEntity, RestoreEntity): # Inherit from RestoreEntity
    """Representation of the Packet Delay number entity."""

    entity_description = NUMBER_ENTITY_DESCRIPTION

    def __init__(self, device_manager: AintinksmartDevice) -> None:
        """Initialize the number entity."""
        super().__init__(device_manager)
        # Unique ID is handled by the base class using entity_description.key
        self._attr_native_value: float | None = None # Initialize attribute

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._attr_native_value

    async def async_added_to_hass(self) -> None:
        """Restore last state when added."""
        # Call the base AintinksmartEntity's method first
        await super(AintinksmartEntity, self).async_added_to_hass()
        # Then call RestoreEntity method to load the last state
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
                _LOGGER.debug("[%s] Restored packet delay: %s ms", self._mac_address, self._attr_native_value)
            except (ValueError, TypeError):
                _LOGGER.warning("[%s] Could not parse restored state '%s', using default.", self._mac_address, last_state.state)
                self._attr_native_value = float(DEFAULT_PACKET_DELAY_MS)
        else:
            self._attr_native_value = float(DEFAULT_PACKET_DELAY_MS)
            _LOGGER.debug("[%s] No previous packet delay found, using default: %s ms", self._mac_address, self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        _LOGGER.debug("[%s] Setting packet delay to: %s ms", self._mac_address, value)
        self._attr_native_value = value
        # RestoreEntity handles persistence automatically when state is written
        self.async_write_ha_state() # Update HA state (and trigger persistence)