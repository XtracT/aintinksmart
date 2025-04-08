"""Camera platform for Ain't Ink Smart."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature, CameraEntityDescription # Import EntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

# Import constants and base entity
from .const import DOMAIN
from .entity import AintinksmartEntity
# Import device manager type hint safely
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .device import AintinksmartDevice

_LOGGER = logging.getLogger(__name__)

# Define the camera description
CAMERA_DESCRIPTION = CameraEntityDescription(
    key="display_image", # Used for unique_id in base class
    name="Display Image", # Used if _attr_has_entity_name=False
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform."""
    # Get the device manager instance stored in __init__
    device_manager: AintinksmartDevice = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Setting up camera for %s", device_manager.mac_address)

    cameras = [
        AintinksmartCamera(device_manager), # Pass the manager instance
    ]
    async_add_entities(cameras)


from homeassistant.helpers.restore_state import RestoreEntity

class AintinksmartCamera(AintinksmartEntity, Camera, RestoreEntity):
    """Representation of an Ain't Ink Smart Camera entity."""

    entity_description = CAMERA_DESCRIPTION # Assign description
    _attr_supported_features = CameraEntityFeature(0) # No streaming, no controls

    def __init__(self, device_manager: AintinksmartDevice) -> None:
        """Initialize the camera."""
        # Pass manager to the base class __init__
        AintinksmartEntity.__init__(self, device_manager)
        Camera.__init__(self) # Call Camera base __init__
        # Unique ID is now handled by the base class using entity_description.key
        self._last_image_bytes: bytes | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and "last_image_bytes_b64" in last_state.attributes:
            try:
                import base64
                self._last_image_bytes = base64.b64decode(last_state.attributes["last_image_bytes_b64"])
                # Also update the manager's state
                self._manager._last_image_bytes = self._last_image_bytes
                _LOGGER.debug("Restored last image for %s", self._mac_address)
            except Exception as e:
                _LOGGER.error("Error decoding restored image: %s", e)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image."""
        # Get image bytes directly from the device manager's state data property
        _LOGGER.debug("Fetching camera image for %s", self._mac_address)
        # Return the manager's state, which might have been restored
        self._last_image_bytes = self._manager.state_data.get("last_image_bytes")
        return self._last_image_bytes

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self._last_image_bytes:
            import base64
            return {"last_image_bytes_b64": base64.b64encode(self._last_image_bytes).decode("utf-8")}
        return None

    # No need for _handle_coordinator_update here anymore,
    # the base class handles async_write_ha_state via the listener pattern