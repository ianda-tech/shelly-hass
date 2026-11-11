"""Live number settings on each adopted Shelly. Common ones are enabled."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SHELLY_DOMAIN
from .device_settings import model_is_dimmer
from .entity import shelly_device_info
from .runtime import FleetRuntime

PARALLEL_UPDATES = 1

_SPECS = {
    "auto_off_delay": {"min": 0, "max": 86400, "step": 0.5, "dimmer_only": False},
    "fade_rate": {"min": 1, "max": 5, "step": 1, "dimmer_only": True},
    "transition_duration": {"min": 0, "max": 10800, "step": 0.5, "dimmer_only": True},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        model = str(shelly_entry.data.get("model") or "")
        dimmer = model_is_dimmer(model)
        for key, spec in _SPECS.items():
            if spec["dimmer_only"] and not dimmer:
                continue
            entities.append(LiveNumber(runtime, shelly_entry, key, spec))
    async_add_entities(entities)


class LiveNumber(CoordinatorEntity, NumberEntity):
    """One numeric Shelly setting. The state is the value from the device coordinator."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry, key: str, spec: dict) -> None:
        super().__init__(runtime.device_coordinator(shelly_entry))
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._key = key
        self._attr_unique_id = f"{shelly_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)

    @property
    def available(self) -> bool:
        return self._raw() is not None

    @property
    def native_value(self) -> float | None:
        raw = self._raw()
        if raw is None:
            return None
        return float(raw)

    def _raw(self):
        data = self.coordinator.data
        if not data:
            return None
        return (data.get("settings") or {}).get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        try:
            read_back = await self.runtime.write_device_setting(self._shelly_entry, self._key, value)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        if read_back is None:
            raise HomeAssistantError("The device did not accept this value")
        self.coordinator.patch_setting(self._key, read_back)
