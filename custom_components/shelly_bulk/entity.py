"""Shared entity base for Shelly Bulk."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, VERSION
from .runtime import FleetRuntime


class FleetEntity(Entity):
    """Diagnostic entity attached to the Shelly Bulk service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: FleetRuntime, unique_suffix: str) -> None:
        self.runtime = runtime
        entry = runtime.entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Shelly Bulk ({runtime.site_name})",
            manufacturer=MANUFACTURER,
            model="Shelly Bulk",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()


def companion_identifier(entry) -> tuple[str, str]:
    """Stable id for the Shelly Bulk device that belongs to one core Shelly."""
    return (DOMAIN, f"companion_{entry.entry_id}")


def linked_shelly_names(hass, entry) -> tuple[str, str, str, str, str]:
    """Return user name, device name, model, MAC, and IP for a core Shelly entry."""
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    device = next((item for item in devices if item.via_device_id is None), None)
    if device is None and devices:
        device = devices[0]
    name_by_user = ""
    device_name = entry.title or ""
    if device is not None:
        name_by_user = device.name_by_user or ""
        device_name = device.name or device_name
    model = str(entry.data.get("model") or "")
    mac = str(entry.unique_id or "")
    ip = str(entry.data.get("host") or "")
    return name_by_user, device_name, model, mac, ip


def shelly_device_info(hass, entry) -> DeviceInfo:
    """Describe the Shelly Bulk device for one core Shelly.

    The name is the linked Shelly's name plus its MAC and IP, not the hub title.
    """
    from .groups import companion_device_name, friendly_model

    name_by_user, device_name, model, mac, ip = linked_shelly_names(hass, entry)
    info = DeviceInfo(
        identifiers={companion_identifier(entry)},
        name=companion_device_name(name_by_user, device_name, model, mac, ip),
        manufacturer="Shelly",
        model=friendly_model(model) or model or "Shelly",
    )
    if ip:
        info["configuration_url"] = f"http://{ip}"
    if mac:
        try:
            from .util import display_mac

            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, display_mac(mac))}
        except ValueError:
            pass
    return info


def update_companion_device(hass, entry, *, ip: str | None = None) -> None:
    """Refresh the companion name when the IP changes, unless the user renamed it."""
    from .groups import companion_device_name

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={companion_identifier(entry)})
    if device is None:
        return
    name_by_user, device_name, model, mac, stored_ip = linked_shelly_names(hass, entry)
    current_ip = ip if ip is not None else stored_ip
    kwargs = {}
    if not device.name_by_user:
        kwargs["name"] = companion_device_name(name_by_user, device_name, model, mac, current_ip)
    if current_ip:
        kwargs["configuration_url"] = f"http://{current_ip}"
    if mac:
        try:
            from .util import display_mac

            kwargs["merge_connections"] = {(dr.CONNECTION_NETWORK_MAC, display_mac(mac))}
        except ValueError:
            pass
    if kwargs:
        registry.async_update_device(device.id, **kwargs)
