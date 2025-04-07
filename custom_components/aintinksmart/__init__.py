"""The Ain't Ink Smart integration."""
from __future__ import annotations

import asyncio # Add asyncio import
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, ATTR_ENTITY_ID, ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_extract_config_entry_ids

# Import constants
from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MAC,
    SERVICE_SEND_IMAGE,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
)
# Import the device manager class
from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

# Define service schema based on services.yaml
# Allow extra keys like device_id, entity_id which HA adds automatically
SERVICE_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        # We only define the keys specific to our service logic here.
        # Targeting keys (device_id, entity_id, area_id) are handled by HA helpers
        # and allowed by ALLOW_EXTRA.
        vol.Exclusive(ATTR_IMAGE_DATA, "image_source"): str,
        vol.Exclusive(ATTR_IMAGE_ENTITY_ID, "image_source"): str,
        vol.Required(ATTR_MODE): vol.In(["bw", "bwr"]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ain't Ink Smart from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    mac_address = entry.data[CONF_MAC]

    _LOGGER.info("Setting up Ain't Ink Smart device: %s", mac_address)

    # Instantiate the device manager
    device_manager = AintinksmartDevice(hass, entry)
    try:
        # Perform initial setup (find BLE device, register callbacks)
        await device_manager.async_init()
    except Exception as err: # Catch potential errors during init
        # ConfigEntryNotReady should ideally be raised by async_init if needed
        _LOGGER.error("Error initializing device %s: %s", mac_address, err)
        # Clean up if init fails partially? Depends on async_init implementation
        # await device_manager.async_unload() # Example cleanup
        raise ConfigEntryNotReady(f"Failed to initialize device {mac_address}: {err}") from err

    # Store the manager instance
    hass.data[DOMAIN][entry.entry_id] = device_manager

    # Set up platforms (sensor, camera)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Register Service Call ---
    async def handle_send_image(call: ServiceCall) -> None:
        """Handle the send_image service call."""
        config_entry_ids = await async_extract_config_entry_ids(hass, call)
        _LOGGER.debug("Service call '%s' targeting config entries: %s", SERVICE_SEND_IMAGE, config_entry_ids)

        tasks = []
        for entry_id in config_entry_ids:
            manager = hass.data[DOMAIN].get(entry_id)
            if manager and isinstance(manager, AintinksmartDevice):
                _LOGGER.info("Dispatching send_image to device: %s", manager.mac_address)
                tasks.append(manager.async_handle_send_image_service(call))
            else:
                _LOGGER.warning(
                    "Could not find device manager for config entry %s to handle service call",
                    entry_id,
                )

        if tasks:
            try:
                # Run tasks concurrently and gather results/exceptions
                await asyncio.gather(*tasks)
            except Exception as e:
                 # Log errors from service handling, but don't block HA service call return
                 _LOGGER.error("Error during send_image service execution: %s", e)
                 # Re-raise specific custom exceptions if needed for frontend feedback
                 # raise HomeAssistantError(f"Failed to send image: {e}") from e
        else:
            _LOGGER.warning("Service call %s did not target any known devices.", SERVICE_SEND_IMAGE)


    # Register the service only once
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
        _LOGGER.info("Registering service: %s.%s", DOMAIN, SERVICE_SEND_IMAGE)
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_IMAGE,
            handle_send_image,
            schema=SERVICE_SEND_IMAGE_SCHEMA, # Add schema validation
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    mac_address = entry.data.get(CONF_MAC, "unknown MAC")
    _LOGGER.info("Unloading Ain't Ink Smart device: %s", mac_address)

    # Unload platforms first
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Retrieve and clean up the device manager
    device_manager = hass.data[DOMAIN].get(entry.entry_id)
    if isinstance(device_manager, AintinksmartDevice):
        await device_manager.async_unload()

    # Remove data associated with the entry
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.debug("Successfully removed data for entry %s", entry.entry_id)

    # Remove service if this is the last entry being unloaded
    if not hass.data[DOMAIN]:
         _LOGGER.info("Last entry unloaded, removing service: %s.%s", DOMAIN, SERVICE_SEND_IMAGE)
         # Check if service exists before removing, as it might have failed registration
         if hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
              hass.services.async_remove(DOMAIN, SERVICE_SEND_IMAGE)

    return unload_ok

# Optional: Implement async_migrate_entry if config entry format changes later
# async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
#     """Migrate old entry."""
#     _LOGGER.debug("Migrating from version %s", config_entry.version)
#     # ... migration logic ...
#     _LOGGER.info("Migration to version %s successful", config_entry.version)
#     return True