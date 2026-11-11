"""Config selects for scanner mode, input behaviour, and power-on state."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_type import CONSUMPTION_TYPES, channel_consumption
from .const import (
    BLE_SCANNER_MODES,
    CONF_BLE_SCANNER_MODE,
    DOMAIN,
    LIGHT_IN_MODES,
    SHELLY_DOMAIN,
    SWITCH_IN_MODES,
)
from .pairing import valid_initial_states
from .entity import shelly_device_info
from .runtime import FleetRuntime

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    runtime.add_consumption_entities = async_add_entities
    entities: list[SelectEntity] = []
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        entities.append(ScannerModeSelect(runtime, shelly_entry))
        entities.append(OutputSelect(runtime, shelly_entry, "input_mode"))
        entities.append(OutputSelect(runtime, shelly_entry, "power_on_state"))
        entities.append(ConsumptionTypeSelect(runtime, shelly_entry, 0))
    async_add_entities(entities)


class ScannerModeSelect(SelectEntity):
    """Bluetooth scanner mode stored on the core Shelly entry. No device read."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "scanner_mode"
    _attr_options = list(BLE_SCANNER_MODES)

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry) -> None:
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._attr_unique_id = f"{shelly_entry.entry_id}_scanner_mode"
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)

    @property
    def current_option(self) -> str | None:
        mode = str(self._shelly_entry.options.get(CONF_BLE_SCANNER_MODE) or "disabled")
        return mode if mode in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.runtime.write_device_setting(self._shelly_entry, "scanner_mode", option)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        updated = self.runtime.hass.config_entries.async_get_entry(self._shelly_entry.entry_id)
        if updated is not None:
            self._shelly_entry = updated
        self.async_write_ha_state()


class OutputSelect(CoordinatorEntity, SelectEntity):
    """Input behaviour or power-on state from the shared device read."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry, key: str) -> None:
        super().__init__(runtime.device_coordinator(shelly_entry))
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._key = key
        self._attr_unique_id = f"{shelly_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)

    @property
    def options(self) -> list[str]:
        output = self._output()
        kind = output.get("kind") or "switch"
        if self._key == "power_on_state":
            return list(valid_initial_states(kind, output.get("in_mode")))
        modes = LIGHT_IN_MODES if kind != "switch" else SWITCH_IN_MODES
        return sorted(modes)

    @property
    def available(self) -> bool:
        return self.current_option is not None

    @property
    def current_option(self) -> str | None:
        output = self._output()
        field = "initial_state" if self._key == "power_on_state" else "in_mode"
        value = output.get(field)
        return value if value in self.options else None

    def _output(self) -> dict:
        data = self.coordinator.data or {}
        output = data.get("output")
        return output if isinstance(output, dict) else {}

    async def async_select_option(self, option: str) -> None:
        try:
            read_back = await self.runtime.write_device_setting(self._shelly_entry, self._key, option)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        if self._key == "power_on_state":
            self.coordinator.patch_output(initial_state=None if read_back is None else str(read_back))
        else:
            self.coordinator.patch_output(in_mode=None if read_back is None else str(read_back))


class ConsumptionTypeSelect(CoordinatorEntity, SelectEntity):
    """Consumption type for one switch channel. A matching value is not written again."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_translation_key = "consumption_type"

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry, channel: int) -> None:
        super().__init__(runtime.device_coordinator(shelly_entry))
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._channel = channel
        self._attr_unique_id = f"{shelly_entry.entry_id}_consumption_type_{channel}"
        self._attr_translation_placeholders = {"channel": str(channel + 1)}
        self._attr_options = list(CONSUMPTION_TYPES)
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)

    @property
    def available(self) -> bool:
        return self.current_option is not None

    @property
    def current_option(self) -> str | None:
        info = self._info()
        channels = list(info.get("channels") or [])
        if self._channel not in channels:
            return None
        values = info.get("values") or {}
        current = values.get(self._channel)
        if current is None:
            current = values.get(str(self._channel))
        if current is None:
            current = channel_consumption(list(info.get("types") or []), self._channel)
        if current not in self._attr_options:
            self._attr_options = [*self._attr_options, current]
        return current

    def _info(self) -> dict:
        data = self.coordinator.data or {}
        info = data.get("consumption")
        return info if isinstance(info, dict) else {}

    def _handle_coordinator_update(self) -> None:
        if self._channel == 0:
            self._add_other_channels(list(self._info().get("channels") or []))
        super()._handle_coordinator_update()

    def _add_other_channels(self, channels: list[int]) -> None:
        adder = getattr(self.runtime, "add_consumption_entities", None)
        if adder is None:
            return
        fresh = []
        for channel in channels:
            if channel == 0:
                continue
            key = (self._shelly_entry.entry_id, channel)
            if key in self.runtime._consumption_added:
                continue
            self.runtime._consumption_added.add(key)
            fresh.append(ConsumptionTypeSelect(self.runtime, self._shelly_entry, channel))
        if fresh:
            adder(fresh)

    async def async_select_option(self, option: str) -> None:
        try:
            read_back = await self.runtime.write_consumption_type(self._shelly_entry, self._channel, option)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        if read_back is not None:
            self.coordinator.patch_consumption(self._channel, read_back)
