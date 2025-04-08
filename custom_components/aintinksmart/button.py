"""Button platform for Ain't Ink Smart integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ain't Ink Smart button."""
    device_manager = hass.data[DOMAIN][entry.entry_id]
    button = ForceUpdateButton(hass, entry, device_manager)
    async_add_entities([button])

from .entity import AintinksmartEntity

class ForceUpdateButton(AintinksmartEntity, ButtonEntity):
    """Button to force update the e-ink display."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_manager) -> None:
        self.hass = hass
        self._entry = entry
        self._device_manager = device_manager
        from homeassistant.components.button import ButtonEntityDescription

        self.entity_description = ButtonEntityDescription(
            key="force_update_button",
            name="Force Update Display",
        )
        AintinksmartEntity.__init__(self, device_manager)
        ButtonEntity.__init__(self)
        self._attr_name = "Force Update Display"

    async def async_press(self) -> None:
        """Handle button press."""
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(self.hass)

        # Find select entities by unique_id
        source_select_unique_id = f"{self._entry.entry_id}_source_entity"
        mode_select_unique_id = f"{self._entry.entry_id}_update_mode"

        source_select_entity_id = ent_reg.async_get_entity_id("select", DOMAIN, source_select_unique_id)
        mode_select_entity_id = ent_reg.async_get_entity_id("select", DOMAIN, mode_select_unique_id)

        source_state = self.hass.states.get(source_select_entity_id) if source_select_entity_id else None
        mode_state = self.hass.states.get(mode_select_entity_id) if mode_select_entity_id else None

        _LOGGER.warning("DEBUG: Button checking source select entity_id: %s, state: %s", source_select_entity_id, source_state)
        _LOGGER.warning("DEBUG: Button checking mode select entity_id: %s, state: %s", mode_select_entity_id, mode_state)

        if not source_state or not source_state.state or source_state.state in ("unknown", "unavailable"):
            _LOGGER.warning("No source entity selected for force update button")
            return
        source_entity_id = source_state.state

        mode = "bwr"
        if mode_state and mode_state.state in ("bw", "bwr"):
            mode = mode_state.state

        _LOGGER.info("Button pressed: Forcing update from source entity %s", source_entity_id)
        await self._device_manager._trigger_update_from_source(source_entity_id, mode)