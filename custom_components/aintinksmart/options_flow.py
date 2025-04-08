"""Options flow for Ain't Ink Smart integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class AintinksmartOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Ain't Ink Smart options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> dict:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_create_entry(title="", data={})

async def async_get_options_flow(
    config_entry: config_entries.ConfigEntry,
) -> AintinksmartOptionsFlowHandler:
    """Get the options flow handler."""
    return AintinksmartOptionsFlowHandler(config_entry)