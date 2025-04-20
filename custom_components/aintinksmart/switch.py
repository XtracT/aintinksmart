"""Switch platform for Ain't Ink Smart integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, KEY_AUTO_UPDATE_SWITCH
from .device import AintinksmartDevice
from .entity import AintinksmartEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ain't Ink Smart switch entities."""
    device_manager: AintinksmartDevice = hass.data[DOMAIN][entry.entry_id]
    auto_update_switch = AutoUpdateSwitch(entry, device_manager)
    async_add_entities([auto_update_switch])


class AutoUpdateSwitch(AintinksmartEntity, SwitchEntity, RestoreEntity):
    """Switch entity to enable/disable automatic updates."""

    _attr_has_entity_name = True # Use entity name provided by description or class

    def __init__(self, entry: ConfigEntry, device_manager: AintinksmartDevice) -> None:
        """Initialize the switch."""
        from homeassistant.components.switch import SwitchEntityDescription

        # Define entity description before calling super().__init__
        self.entity_description = SwitchEntityDescription(
            key=KEY_AUTO_UPDATE_SWITCH,
            # translation_key is automatically inferred from key
            # name="Enable Auto Update" # Name can be set via translation_key
        )

        super().__init__(device_manager) # Pass manager to base entity
        self._entry = entry
        # unique_id is now set in the base class using entity_description.key
        # self._attr_unique_id = f"{entry.entry_id}_{KEY_AUTO_UPDATE_SWITCH}" # No longer needed here
        # Default state is ON
        self._attr_is_on = True
        # Link to the device manager's flag will be done after state restoration

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added, restore state."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        restored_state = None
        if last_state and last_state.state is not None:
            restored_state = last_state.state == "on"
            _LOGGER.debug(
                "[%s] Restored %s state to %s",
                self._manager.mac_address, self.entity_id, restored_state
            )

        # Set the initial state based on restored value or default
        if restored_state is not None:
            self._attr_is_on = restored_state
        else:
            # Keep the default True if no state was restored
            _LOGGER.debug(
                "[%s] No previous state found for %s, defaulting to %s",
                self._manager.mac_address, self.entity_id, self._attr_is_on
            )

        # Update the device manager's flag based on the final initial state
        self._manager.async_set_auto_update_enabled(self._attr_is_on)
        # No need to call async_write_ha_state() here

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        if self._attr_is_on:
            return # Already on

        _LOGGER.debug("[%s] Turning on auto update", self._manager.mac_address)
        self._attr_is_on = True
        self._manager.async_set_auto_update_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        if not self._attr_is_on:
            return # Already off

        _LOGGER.debug("[%s] Turning off auto update", self._manager.mac_address)
        self._attr_is_on = False
        self._manager.async_set_auto_update_enabled(False)
        self.async_write_ha_state()