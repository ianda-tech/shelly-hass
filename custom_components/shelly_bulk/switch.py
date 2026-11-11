"""Provisioning-mode switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .advanced import SWITCH_SETTINGS
from .const import CONF_PROVISIONING_MINUTES, DOMAIN, SHELLY_DOMAIN
from .entity import FleetEntity, shelly_device_info
from .runtime import FleetRuntime

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [ProvisioningSwitch(runtime), AutoAdoptSwitch(runtime)]
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


class AutoAdoptSwitch(FleetEntity, SwitchEntity):
    """Adopt factory-new Shellies that are not on the device list.

    Only provision the allowlist overrides this switch while that option is on.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "auto_adopt"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "auto_adopt")

    @property
    def is_on(self) -> bool:
        return self.runtime.auto_adopt

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        if self.runtime.auto_adopt and self.runtime.require_allowlist:
            return {
                "status": (
                    "Paused. Only provision the allowlist is on, so devices that "
                    "are not on the list are left alone."
                )
            }
        if self.runtime.effective_auto_adopt:
            return {
                "status": (
                    "On. A factory-new Shelly in range can be adopted, including a neighbour's."
                )
            }
        return {"status": "Off. Find my Shelly only adds devices to the list."}

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.set_auto_adopt(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.set_auto_adopt(False)
        self.async_write_ha_state()


class AdvancedSwitch(CoordinatorEntity, SwitchEntity):
    """One documented on/off setting for a single Shelly.

    The value comes from the device coordinator. Adding the entity does not
    open a connection.
    """

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
    def available(self) -> bool:
        return self._setting() is not None

    @property
    def is_on(self) -> bool:
        return bool(self._setting())

    def _setting(self):
        data = self.coordinator.data
        if not data:
            return None
        return (data.get("settings") or {}).get(self._key)

    async def async_turn_on(self, **kwargs) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write(False)

    async def _write(self, value: bool) -> None:
        try:
            read_back = await self.runtime.write_device_setting(self._shelly_entry, self._key, value)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self.coordinator.patch_setting(self._key, read_back)
