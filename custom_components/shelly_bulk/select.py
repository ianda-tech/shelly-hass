"""Config selects for scanner mode, input behaviour, and power-on state."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .advanced import SELECT_SETTINGS
from .const import (
    BLE_SCANNER_MODES,
    DOMAIN,
    LIGHT_IN_MODES,
    SHELLY_DOMAIN,
    SWITCH_IN_MODES,
)
from .pairing import valid_initial_states
from .entity import shelly_device_info
from .runtime import FleetRuntime

_OPTIONS = {
    "scanner_mode": list(BLE_SCANNER_MODES),
    "input_mode": sorted(SWITCH_IN_MODES),
    "power_on_state": ["off", "on", "restore_last", "match_input"],
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        entities.extend(AdvancedSelect(runtime, shelly_entry, key) for key in SELECT_SETTINGS)
    async_add_entities(entities)


class AdvancedSelect(SelectEntity):
    """One documented choice for a single Shelly. Disabled until the user enables it."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry, key: str) -> None:
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._key = key
        # Input mode and power-on state are the everyday controls. Scanner mode
        # stays off until someone enables the advanced select.
        common = key in {"input_mode", "power_on_state"}
        self._attr_entity_registry_enabled_default = True
        self._attr_should_poll = common
        self._attr_unique_id = f"{shelly_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_options = _OPTIONS[key]
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)
        self._available = True
        self._current: str | None = None
        self._kind = "switch"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._refresh()

    @property
    def available(self) -> bool:
        return self._available

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_update(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        try:
            if self._key in {"input_mode", "power_on_state"}:
                kind, mode, initial = await self.runtime.read_output_pair(self._shelly_entry)
                self._kind = kind or "switch"
                if self._key == "power_on_state":
                    self._attr_options = list(valid_initial_states(self._kind, mode))
                    value = initial
                else:
                    modes = LIGHT_IN_MODES if self._kind != "switch" else SWITCH_IN_MODES
                    self._attr_options = sorted(modes)
                    value = mode
            else:
                value = await self.runtime.read_device_setting(self._shelly_entry, self._key)
        except Exception:  # noqa: BLE001
            self._available = False
            return
        self._current = value if value in self._attr_options else None
        self._available = self._current is not None

    async def async_select_option(self, option: str) -> None:
        try:
            read_back = await self.runtime.write_device_setting(self._shelly_entry, self._key, option)
        except Exception as err:  # noqa: BLE001
            await self._refresh()
            self.async_write_ha_state()
            raise HomeAssistantError(str(err)) from err
        self._current = str(read_back) if read_back in self._attr_options else None
        self._available = self._current is not None
        if self._current is None:
            await self._refresh()
        self.async_write_ha_state()
