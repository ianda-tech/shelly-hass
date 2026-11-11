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
            SecurityAuditSensor(runtime),
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


class SecurityAuditSensor(FleetEntity, SensorEntity):
    """Latest security checklist across the audited Shelly devices."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "security_audit"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "security_audit")

    @property
    def native_value(self) -> str:
        rows = self.runtime.last_audit
        if not rows:
            return "not_audited"
        passed = sum(1 for row in rows if row.get("ok"))
        return f"{passed}/{len(rows)}"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        devices = []
        for row in self.runtime.last_audit:
            devices.append(
                {
                    "mac": row.get("mac"),
                    "firmware": row.get("firmware"),
                    "auth_on": row.get("auth_on"),
                    "cloud_off": row.get("cloud_off"),
                    "ap_off": row.get("ap_off"),
                    "ble_rpc_off": row.get("ble_rpc_off"),
                    "ok": row.get("ok"),
                    "issues": row.get("issues") or [],
                }
            )
        return {"devices": devices}
