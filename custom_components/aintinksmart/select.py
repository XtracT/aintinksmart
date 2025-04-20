"""Select platform for Ain't Ink Smart integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import RestoreEntity # Import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ain't Ink Smart select entities."""
    device_manager = hass.data[DOMAIN][entry.entry_id]
    source_select = SourceEntitySelect(hass, entry, device_manager)
    mode_select = UpdateModeSelect(hass, entry, device_manager)
    async_add_entities([source_select, mode_select])

from .entity import AintinksmartEntity

class SourceEntitySelect(AintinksmartEntity, SelectEntity, RestoreEntity): # Add RestoreEntity
    """Select entity to choose source image/camera."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_manager) -> None:
        self.hass = hass
        self._entry = entry
        self._device_manager = device_manager
        self._manager = device_manager
        self._mac_address = device_manager.mac_address
        self._attr_name = "Source Entity"
        self._attr_unique_id = f"{entry.entry_id}_source_entity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_manager.formatted_mac)},
            name=f"Ain't Ink Smart {device_manager.mac_address}",
            manufacturer="Ain't Ink Smart (Custom)",
        )
        self._attr_options = []
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added, restore state."""
        await super().async_added_to_hass()

        # Populate options first
        self._update_options()

        # Attempt to restore the last state
        last_state = await self.async_get_last_state()
        restored = False
        if last_state and last_state.state in self._attr_options:
            self._attr_current_option = last_state.state
            self._device_manager._source_entity_id_override = last_state.state
            restored = True
            _LOGGER.debug(
                "Restored %s state to %s", self.entity_id, self._attr_current_option
            )

        # If not restored and no option set yet, set default
        if not restored and not self._attr_current_option and self._attr_options:
            self._attr_current_option = self._attr_options[0]
            self._device_manager._source_entity_id_override = self._attr_options[0]
            _LOGGER.debug(
                "Setting default %s state to %s", self.entity_id, self._attr_current_option
            )

        # No need to call async_write_ha_state() here, HA handles it after setup

    @callback
    def _update_options(self):
        """Update options list with all camera/image entities."""
        entity_reg = er.async_get(self.hass)
        options = []
        for entity in entity_reg.entities.values():
            if entity.domain in ("camera", "image"):
                options.append(entity.entity_id)
        self._attr_options = sorted(options) # Sort for consistency
        # Default setting moved to async_added_to_hass

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting an option."""
        _LOGGER.info("Source entity for %s set to %s", self._device_manager.mac_address, option)
        self._attr_current_option = option
        self._device_manager._source_entity_id_override = option
        self.async_write_ha_state()

class UpdateModeSelect(AintinksmartEntity, SelectEntity, RestoreEntity): # Add RestoreEntity
    """Select entity to choose update mode."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_manager) -> None:
        from homeassistant.components.select import SelectEntityDescription

        self.hass = hass
        self._entry = entry
        self._device_manager = device_manager
        self._manager = device_manager
        self._mac_address = device_manager.mac_address
        self._manager = device_manager
        self.entity_description = SelectEntityDescription(
            key="update_mode",
            name="Update Mode",
        )
        AintinksmartEntity.__init__(self, device_manager)
        SelectEntity.__init__(self)
        self._attr_name = "Update Mode"
        self._attr_unique_id = f"{entry.entry_id}_update_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_manager.formatted_mac)},
            name=f"Ain't Ink Smart {device_manager.mac_address}",
            manufacturer="Ain't Ink Smart (Custom)",
        )
        self._attr_options = ["bw", "bwr"]
        self._attr_current_option = "bwr"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added, restore state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in self._attr_options:
            self._attr_current_option = last_state.state
            self._device_manager._auto_update_mode_override = last_state.state
            _LOGGER.debug(
                "Restored %s state to %s", self.entity_id, self._attr_current_option
            )
        # If not restored, the default from __init__ remains

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting an option."""
        _LOGGER.info("Update mode for %s set to %s", self._device_manager.mac_address, option)
        self._attr_current_option = option
        self._device_manager._auto_update_mode_override = option
        self.async_write_ha_state()