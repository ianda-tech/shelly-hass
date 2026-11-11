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
        ScanHotspotsButton(runtime),
        ProvisionHotspotsButton(runtime),
        DryRunHotspotsButton(runtime),
    ]
    seen: set[str] = set()

    def _add_hotspot_buttons(found: list[dict]) -> None:
        fresh: list[ButtonEntity] = []
        for item in found:
            mac = str(item.get("sta_mac") or "")
            if not mac or mac in seen:
                continue
            seen.add(mac)
            fresh.append(HotspotProvisionButton(runtime, item))
        if fresh:
            async_add_entities(fresh)

    runtime.add_hotspot_buttons = _add_hotspot_buttons
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


class ScanHotspotsButton(FleetEntity, ButtonEntity):
    """List Shelly setup access points the Supervisor can see."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "scan_hotspots"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "scan_hotspots")

    async def async_press(self) -> None:
        await self.runtime.scan_hotspots()


class ProvisionHotspotsButton(FleetEntity, ButtonEntity):
    """Provision every setup AP from the last scan, one at a time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "provision_hotspots"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "provision_hotspots")

    async def async_press(self) -> None:
        await self.runtime.provision_hotspots(all_found=True)


class DryRunHotspotsButton(FleetEntity, ButtonEntity):
    """Report the hotspot plan without joining an access point."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "dry_run_hotspots"

    def __init__(self, runtime: FleetRuntime) -> None:
        super().__init__(runtime, "dry_run_hotspots")

    async def async_press(self) -> None:
        await self.runtime.provision_hotspots(all_found=True, dry_run=True)


class HotspotProvisionButton(FleetEntity, ButtonEntity):
    """Join one Shelly setup AP, send the site Wi-Fi, and restore wlan0."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: FleetRuntime, item: dict) -> None:
        super().__init__(runtime, f"hotspot_{item['sta_mac']}")
        from .util import display_mac

        self._mac = str(item["sta_mac"])
        self._attr_name = f"Provision via hotspot {display_mac(self._mac)}"

    async def async_press(self) -> None:
        await self.runtime.provision_hotspots(mac=self._mac)


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
