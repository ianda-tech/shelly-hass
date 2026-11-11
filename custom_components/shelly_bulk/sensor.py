"""Diagnostic sensors for adoption progress."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SHELLY_DOMAIN
from .entity import FleetEntity, shelly_device_info
from .runtime import FleetRuntime
from .util import display_mac


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        AdoptedSensor(runtime),
        PendingSensor(runtime),
        FailedSensor(runtime),
        LastErrorSensor(runtime),
        SecurityAuditSensor(runtime),
    ]
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        entities.append(ShellyMacSensor(runtime, shelly_entry))
        entities.append(ShellyIpSensor(runtime, shelly_entry))
        entities.append(ShellyWifiSensor(runtime, shelly_entry, "ssid"))
        entities.append(ShellyWifiSensor(runtime, shelly_entry, "rssi"))
    async_add_entities(entities)


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


class ShellyMacSensor(SensorEntity):
    """MAC address of one core Shelly. Enabled so it shows on the device page."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "mac_address"

    def __init__(self, runtime: FleetRuntime, shelly_entry) -> None:
        self.runtime = runtime
        self._entry = shelly_entry
        self._attr_unique_id = f"{shelly_entry.entry_id}_mac_address"
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)
        try:
            self._mac = display_mac(shelly_entry.unique_id or "")
        except ValueError:
            self._mac = str(shelly_entry.unique_id or "")

    @property
    def native_value(self) -> str:
        return self._mac

    async def async_added_to_hass(self) -> None:
        self.runtime.publish_shelly_link(self._entry, str(self._entry.data.get(CONF_HOST) or ""))


class ShellyIpSensor(SensorEntity):
    """Live IP. Uses Shelly.GetStatus when the device answers, otherwise the core host."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_translation_key = "ip_address"
    _attr_scan_interval = timedelta(seconds=60)

    def __init__(self, runtime: FleetRuntime, shelly_entry) -> None:
        self.runtime = runtime
        self._entry = shelly_entry
        self._attr_unique_id = f"{shelly_entry.entry_id}_ip_address"
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)
        self._ip = str(shelly_entry.data.get(CONF_HOST) or "")

    @property
    def native_value(self) -> str:
        return self._ip

    async def async_added_to_hass(self) -> None:
        await self.async_update()

    async def async_update(self) -> None:
        info = await self.runtime.refresh_network(self._entry)
        self._ip = str(info.get("ip") or "")


class ShellyWifiSensor(SensorEntity):
    """SSID or RSSI from the same status read as the IP sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: FleetRuntime, shelly_entry, key: str) -> None:
        self.runtime = runtime
        self._entry = shelly_entry
        self._key = key
        self._attr_unique_id = f"{shelly_entry.entry_id}_{key}"
        self._attr_translation_key = "wifi_ssid" if key == "ssid" else "wifi_rssi"
        self._attr_device_info = shelly_device_info(runtime.hass, shelly_entry)
        self._value = None

    @property
    def native_value(self):
        return self._value

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.add_listener(self._pull))
        self._pull()

    def _pull(self) -> None:
        cached = self.runtime._network.get(self._entry.entry_id) or {}
        self._value = cached.get(self._key)
        if self.hass is not None:
            self.async_write_ha_state()
