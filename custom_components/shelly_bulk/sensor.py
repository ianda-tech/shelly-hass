"""Diagnostic sensors for adoption progress."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import FleetEntity
from .runtime import FleetRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AdoptedSensor(runtime),
            PendingSensor(runtime),
            FailedSensor(runtime),
            LastErrorSensor(runtime),
        ]
    )


class _CountSensor(FleetEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, runtime: FleetRuntime, suffix: str, key: str) -> None:
        super().__init__(runtime, suffix)
        self._attr_translation_key = suffix
        self._key = key

    @property
    def native_value(self) -> int:
        if self._key == "pending":
            return self.runtime.pending
        return int(getattr(self.runtime, self._key))


class AdoptedSensor(_CountSensor):
    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "adopted", "adopted")


class PendingSensor(_CountSensor):
    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "pending", "pending")


class FailedSensor(_CountSensor):
    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "failed", "failed")


class LastErrorSensor(FleetEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_error"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "last_error")

    @property
    def native_value(self) -> str:
        return self.runtime.last_error or "none"
