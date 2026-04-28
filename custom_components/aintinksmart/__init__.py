"""The Ain't Ink Smart integration."""
from __future__ import annotations

import asyncio
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_extract_config_entry_ids

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MAC,
    SERVICE_SEND_IMAGE,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
)
from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Exclusive(ATTR_IMAGE_DATA, "image_source"): str,
        vol.Exclusive(ATTR_IMAGE_ENTITY_ID, "image_source"): str,
        vol.Required(ATTR_MODE): vol.In(["bw", "bwr"]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Options updated for %s, reloading entry", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ain't Ink Smart from a config entry."""
    try:
        hass.data.setdefault(DOMAIN, {})
        mac_address = entry.data[CONF_MAC]

        _LOGGER.info("Setting up Ain't Ink Smart device: %s", mac_address)

        device_manager = AintinksmartDevice(hass, entry)
        try:
            await device_manager.async_init()
        except Exception as err:
            _LOGGER.error("Error initializing device %s: %s", mac_address, err, exc_info=True)
            raise ConfigEntryNotReady(f"Failed to initialize device {mac_address}: {err}") from err

        hass.data[DOMAIN][entry.entry_id] = device_manager

        entry.async_on_unload(entry.add_update_listener(options_update_listener))

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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
                    await asyncio.gather(*tasks)
                except Exception as e:
                    _LOGGER.error("Error during send_image service execution: %s", e)
            else:
                _LOGGER.warning("Service call %s did not target any known devices.", SERVICE_SEND_IMAGE)

        async def handle_force_update(call: ServiceCall) -> None:
            """Handle the force_update service call."""
            entity_ids = call.data.get("entity_id")
            if not entity_ids:
                _LOGGER.warning("No entity_id provided for force_update service call")
                return

            if isinstance(entity_ids, str):
                entity_ids = [e.strip() for e in entity_ids.split(",")]

            ent_reg = er.async_get(hass)
            dev_reg = dr.async_get(hass)

            config_entry_ids = set()
            for entity_id in entity_ids:
                entity_entry = ent_reg.async_get(entity_id)
                if not entity_entry:
                    _LOGGER.warning("Entity %s not found in registry", entity_id)
                    continue
                device_id = entity_entry.device_id
                if not device_id:
                    _LOGGER.warning("Entity %s has no device_id", entity_id)
                    continue
                device_entry = dev_reg.async_get(device_id)
                if not device_entry:
                    _LOGGER.warning("Device %s not found for entity %s", device_id, entity_id)
                    continue
                config_entry_ids.update(device_entry.config_entries)

            tasks = []
            for entry_id in config_entry_ids:
                manager = hass.data[DOMAIN].get(entry_id)
                if manager and isinstance(manager, AintinksmartDevice):
                    source_entity_id = getattr(manager, "_source_entity_id_override", None)
                    mode = getattr(manager, "_auto_update_mode_override", "bwr")
                    if not source_entity_id:
                        _LOGGER.warning("No source entity selected for device %s", manager.mac_address)
                        continue
                    _LOGGER.info("Force updating device %s from source entity %s", manager.mac_address, source_entity_id)
                    tasks.append(manager._trigger_update_from_source(source_entity_id, mode))
                else:
                    _LOGGER.warning("No device manager found for config entry %s", entry_id)

            if tasks:
                await asyncio.gather(*tasks)

        if not hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SEND_IMAGE,
                handle_send_image,
                schema=SERVICE_SEND_IMAGE_SCHEMA,
            )
            _LOGGER.debug("Registered service: %s.%s", DOMAIN, SERVICE_SEND_IMAGE)

        if not hass.services.has_service(DOMAIN, "force_update"):
             hass.services.async_register(
                 DOMAIN,
                 "force_update",
                 handle_force_update,
             )
             _LOGGER.debug("Registered service: %s.force_update", DOMAIN)

        return True

    except Exception as e:
        _LOGGER.error("Exception in async_setup_entry for %s: %s", mac_address, e, exc_info=True)
        return False



async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    mac_address = entry.data.get(CONF_MAC, "unknown MAC")
    _LOGGER.info("Unloading Ain't Ink Smart device: %s", mac_address)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    device_manager = hass.data[DOMAIN].get(entry.entry_id)
    if isinstance(device_manager, AintinksmartDevice):
        await device_manager.async_unload()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.debug("Successfully removed data for entry %s", entry.entry_id)

    if not hass.data[DOMAIN]:
         _LOGGER.info("Last entry unloaded, removing service: %s.%s", DOMAIN, SERVICE_SEND_IMAGE)
         if hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
              hass.services.async_remove(DOMAIN, SERVICE_SEND_IMAGE)

    return unload_ok
