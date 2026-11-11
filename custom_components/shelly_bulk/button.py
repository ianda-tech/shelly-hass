"""Find, reload, and per-device Identify buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SHELLY_DOMAIN
from .entity import FleetEntity, shelly_device_info
from .runtime import FleetRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [
        FindButton(runtime),
        ReloadDeviceListButton(runtime),
        RetryFailedButton(runtime),
    ]
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        entities.append(IdentifyButton(runtime, shelly_entry))
    async_add_entities(entities)


class FindButton(FleetEntity, ButtonEntity):
    """Scan for Shellies that are not on the device list yet."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "find_shelly"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "find_shelly")

    async def async_press(self) -> None:
        await self.runtime.find_my_shelly()


class ReloadDeviceListButton(FleetEntity, ButtonEntity):
    """Read shelly_bulk/devices.csv again."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reload_device_list"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "reload_device_list")

    async def async_press(self) -> None:
        await self.runtime.reload_device_list(force=True)


class RetryFailedButton(FleetEntity, ButtonEntity):
    """Clear failed adoptions so the next advertisement tries those devices."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "retry_failed"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "retry_failed")

    async def async_press(self) -> None:
        self.runtime.retry_failed()


class IdentifyButton(ButtonEntity):
    """Briefly toggle a Shelly output so the physical unit can be found."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "identify"
    _attr_should_poll = False

    def __init__(self, runtime: FleetRuntime, shelly_entry) -> None:
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        # A press is the only action. Nothing flashes until the button is pressed.
        self._attr_entity_registry_enabled_default = True
        self._attr_unique_id = f"{shelly_entry.entry_id}_identify"
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)

    async def async_press(self) -> None:
        await self.runtime.identify_device(self._shelly_entry)
