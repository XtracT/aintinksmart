"""The Ain't Ink Smart integration."""
from __future__ import annotations

import asyncio
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.service import async_extract_config_entry_ids

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MAC,
    SERVICE_SEND_IMAGE,
    ATTR_IMAGE_PATH,
    ATTR_IMAGE_DATA,
    ATTR_IMAGE_ENTITY_ID,
    ATTR_MODE,
)
from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_IMAGE_PATH): str,
        vol.Optional(ATTR_IMAGE_DATA): str,
        vol.Optional(ATTR_IMAGE_ENTITY_ID): str,
        vol.Required(ATTR_MODE): vol.In(["bw", "bwr"]),
    },
    extra=vol.ALLOW_EXTRA,
)


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

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        async def handle_send_image(call: ServiceCall) -> None:
            """Handle the send_image service call."""
            config_entry_ids = await async_extract_config_entry_ids(call)
            tasks = []
            for entry_id in config_entry_ids:
                manager = hass.data[DOMAIN].get(entry_id)
                if manager and isinstance(manager, AintinksmartDevice):
                    tasks.append(manager.async_handle_send_image(call))

            if tasks:
                await asyncio.gather(*tasks)
            else:
                _LOGGER.warning("Service call %s did not target any known devices.", SERVICE_SEND_IMAGE)

        if not hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SEND_IMAGE,
                handle_send_image,
                schema=SERVICE_SEND_IMAGE_SCHEMA,
            )

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

    if not hass.data[DOMAIN]:
        if hass.services.has_service(DOMAIN, SERVICE_SEND_IMAGE):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_IMAGE)

    return unload_ok
