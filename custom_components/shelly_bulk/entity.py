"""Shared entity base for Shelly Bulk."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, SHELLY_DOMAIN, VERSION
from .runtime import FleetRuntime


class FleetEntity(Entity):
    """Diagnostic entity attached to the Shelly Bulk service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: FleetRuntime, unique_suffix: str) -> None:
        self.runtime = runtime
        entry = runtime.entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Shelly Bulk ({runtime.site_name})",
            manufacturer=MANUFACTURER,
            model="Shelly Bulk",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()


def shelly_device_info(hass, entry) -> DeviceInfo:
    """Attach an entity to the core Shelly device when it already exists."""
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    primary = next((device for device in devices if device.via_device_id is None), None)
    if primary is None and devices:
        primary = devices[0]
    if primary is not None and primary.identifiers:
        return DeviceInfo(identifiers=set(primary.identifiers))
    return DeviceInfo(identifiers={(SHELLY_DOMAIN, entry.unique_id or entry.entry_id)})
