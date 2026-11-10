"""Provisioning-mode switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PROVISIONING_MINUTES, DOMAIN
from .entity import FleetEntity
from .runtime import FleetRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProvisioningSwitch(runtime)])


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
