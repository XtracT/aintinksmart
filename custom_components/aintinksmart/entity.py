"""Base entity for the Ain't Ink Smart integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING # Use for type hinting cycles

from homeassistant.helpers.device_registry import DeviceInfo, format_mac
# Using Entity as base for now, can switch to CoordinatorEntity if needed later
from homeassistant.helpers.entity import Entity

# Import constants
from .const import DOMAIN, DEFAULT_NAME

# Import device manager type hint safely
if TYPE_CHECKING:
    from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)


class AintinksmartEntity(Entity):
    """Base class for Ain't Ink Smart entities."""

    _attr_should_poll = False # Entities will be updated by the manager/coordinator
    _attr_has_entity_name = True # Assumes HA 2023.x+ for cleaner naming

    def __init__(self, device_manager: AintinksmartDevice) -> None:
        """Initialize the base entity."""
        self._manager = device_manager
        self._mac_address = device_manager.mac_address
        self._attr_unique_id = f"{self._mac_address}_{self.entity_description.key}" # Use EntityDescription key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, format_mac(self._mac_address))},
            name=device_manager.name, # Get name from manager
            manufacturer="Ain't Ink Smart (Custom)",
            # model="E-Ink Display", # Add model if identifiable
            # sw_version="...", # Can be added if firmware version is readable
            connections={("mac", format_mac(self._mac_address))},
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Availability is based on the manager's reported availability
        return self._manager.is_available

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()
        # Register a callback with the device manager to update the entity state
        self._manager.add_listener(self.async_write_ha_state)
        _LOGGER.debug("Entity %s added listener to manager %s", self.entity_id, self._mac_address)


    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        # Remove the callback from the device manager
        self._manager.remove_listener(self.async_write_ha_state)
        _LOGGER.debug("Entity %s removed listener from manager %s", self.entity_id, self._mac_address)
        await super().async_will_remove_from_hass()