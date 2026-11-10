"""Provisioning-mode switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .advanced import SWITCH_SETTINGS
from .const import CONF_PROVISIONING_MINUTES, DOMAIN, SHELLY_DOMAIN
from .entity import FleetEntity, shelly_device_info
from .runtime import FleetRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [ProvisioningSwitch(runtime)]
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        entities.extend(advanced_switches(runtime, shelly_entry))
    async_add_entities(entities)


def advanced_switches(runtime: FleetRuntime, shelly_entry: ConfigEntry) -> list[SwitchEntity]:
    return [AdvancedSwitch(runtime, shelly_entry, key) for key in SWITCH_SETTINGS]


class ProvisioningSwitch(FleetEntity, SwitchEntity):
    """Arms automatic adoption until the configured timeout."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "provisioning"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "provisioning")

    @property
    def is_on(self) -> bool:
        return self.runtime.provisioning_active

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        minutes = self.runtime.entry.options.get(CONF_PROVISIONING_MINUTES, 30)
        return {"timeout_minutes": minutes, "pending": self.runtime.pending}

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.start_provisioning()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.stop_provisioning()
        self.async_write_ha_state()


class AdvancedSwitch(SwitchEntity):
    """One documented on/off setting for a single Shelly. Disabled until enabled."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, runtime: FleetRuntime, shelly_entry: ConfigEntry, key: str) -> None:
        self.runtime = runtime
        self._shelly_entry = shelly_entry
        self._key = key
        self._attr_unique_id = f"{shelly_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)
        self._available = True
        self._is_on = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_added_to_hass(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        try:
            value = await self.runtime.read_device_setting(self._shelly_entry, self._key)
        except Exception:  # noqa: BLE001
            self._available = False
            return
        self._available = value is not None
        self._is_on = bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write(False)

    async def _write(self, value: bool) -> None:
        try:
            read_back = await self.runtime.write_device_setting(self._shelly_entry, self._key, value)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self._available = read_back is not None
        self._is_on = bool(read_back)
        self.async_write_ha_state()
