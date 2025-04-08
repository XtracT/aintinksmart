"""Select platform for Ain't Ink Smart integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er

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

class SourceEntitySelect(AintinksmartEntity, SelectEntity):
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
        """Populate options on add."""
        await super().async_added_to_hass()
        self._update_options()

    @callback
    def _update_options(self):
        """Update options list with all camera/image entities."""
        entity_reg = er.async_get(self.hass)
        options = []
        for entity in entity_reg.entities.values():
            if entity.domain in ("camera", "image"):
                options.append(entity.entity_id)
        self._attr_options = options
        # Set current option if unset
        if not self._attr_current_option and options:
            self._attr_current_option = options[0]
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting an option."""
        _LOGGER.info("Source entity for %s set to %s", self._device_manager.mac_address, option)
        self._attr_current_option = option
        self._device_manager._source_entity_id_override = option
        self.async_write_ha_state()

class UpdateModeSelect(AintinksmartEntity, SelectEntity):
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

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting an option."""
        _LOGGER.info("Update mode for %s set to %s", self._device_manager.mac_address, option)
        self._attr_current_option = option
        self._device_manager._auto_update_mode_override = option
        self.async_write_ha_state()