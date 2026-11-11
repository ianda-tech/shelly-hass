"""Shared entity base for Shelly Bulk."""

from __future__ import annotations

import logging

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, SHELLY_DOMAIN, VERSION
from .runtime import FleetRuntime

_LOGGER = logging.getLogger(__name__)


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


def core_shelly_device(hass, entry):
    """Return the core Shelly device for one Shelly config entry, if it exists."""
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    device = next((item for item in devices if item.via_device_id is None), None)
    if device is None and devices:
        device = devices[0]
    return device


def linked_shelly_names(hass, entry) -> tuple[str, str, str, str, str]:
    """Return user name, device name, model, MAC, and IP for a core Shelly entry."""
    device = core_shelly_device(hass, entry)
    name_by_user = ""
    device_name = entry.title or ""
    if device is not None:
        name_by_user = device.name_by_user or ""
        device_name = device.name or device_name
    model = str(entry.data.get("model") or "")
    mac = str(entry.unique_id or "")
    ip = str(entry.data.get("host") or "")
    return name_by_user, device_name, model, mac, ip


def safe_device_update(registry, device_id: str, **kwargs) -> None:
    """Update a device. A registry error is logged and does not stop setup."""
    if not kwargs:
        return
    try:
        registry.async_update_device(device_id, **kwargs)
    except Exception:
        _LOGGER.exception("Could not update device %s", device_id)


def _device_info_has_field(field: str) -> bool:
    """Return True when this Home Assistant build can store the field on DeviceInfo."""
    names = getattr(DeviceInfo, "_field_set", None)
    if names is not None:
        return field in names
    return field in getattr(DeviceInfo, "__annotations__", {})


def device_by_identifier(registry, identifier: tuple[str, str], *config_entry_ids: str):
    """Look up one device by identifier without the deprecated async_get_device."""
    finder = getattr(registry, "async_get_device_by_identifier", None)
    if finder is not None:
        for entry_id in config_entry_ids:
            if not entry_id:
                continue
            found = finder(identifier, entry_id)
            if found is not None:
                return found
        return None
    listed = getattr(registry, "async_get_devices", None)
    if listed is not None:
        for entry_id in config_entry_ids:
            matches = listed(identifiers={identifier}, config_entry_id=entry_id or None)
            if matches:
                return matches[0]
        return None
    return registry.async_get_device(identifiers={identifier})


def device_config_entry_ids(device) -> set[str]:
    """Return the config entry that owns a device, without the deprecated property."""
    entry_id = getattr(device, "config_entry_id", None)
    if isinstance(entry_id, str) and entry_id:
        return {entry_id}
    entries = getattr(device, "config_entries", None)
    if entries:
        return set(entries)
    primary = getattr(device, "primary_config_entry", None)
    return {primary} if isinstance(primary, str) and primary else set()


def registry_devices(registry) -> list:
    """Return device entries. Older Home Assistant stores them in a dict."""
    devices = registry.devices
    if not devices:
        return []
    sample = next(iter(devices))
    if isinstance(sample, str):
        return list(devices.values())
    return list(devices)


def ensure_companion_devices(hass, bulk_entry) -> None:
    """Create each companion device and link it with via_device_id.

    Home Assistant 2026.11 raises if an entity's DeviceInfo carries via_device,
    because the entity platform forwards that into async_get_or_create. The
    companion is registered here, before platforms add entities, and entity
    DeviceInfo does not include via_device.
    """
    registry = dr.async_get(hass)
    for shelly_entry in hass.config_entries.async_entries(SHELLY_DOMAIN):
        try:
            _register_companion(hass, registry, bulk_entry, shelly_entry)
        except Exception:
            _LOGGER.exception(
                "Could not register the companion device for %s", shelly_entry.title
            )


def _register_companion(hass, registry, bulk_entry, shelly_entry) -> None:
    from .groups import companion_device_name, friendly_model

    name_by_user, device_name, model, _mac, ip = linked_shelly_names(hass, shelly_entry)
    kwargs = {
        "config_entry_id": bulk_entry.entry_id,
        "identifiers": {companion_identifier(shelly_entry)},
        "name": companion_device_name(name_by_user, device_name, model, _mac, ip),
        "manufacturer": "Shelly",
        "model": friendly_model(model) or model or "Shelly",
    }
    if ip:
        kwargs["configuration_url"] = f"http://{ip}"
    core = core_shelly_device(hass, shelly_entry)
    if core is None:
        registry.async_get_or_create(**kwargs)
        return
    try:
        registry.async_get_or_create(**kwargs, via_device_id=core.id)
    except TypeError:
        created = registry.async_get_or_create(**kwargs)
        safe_device_update(registry, created.id, via_device_id=core.id)


def shelly_device_info(hass, entry) -> DeviceInfo:
    """Describe the Shelly Bulk device for one core Shelly.

    The name is the linked Shelly's name plus its MAC and IP, not the hub title.
    The MAC connection stays on the core Shelly device. The link to that device
    is via_device_id, set when the companion is registered. via_device is not
    set: Home Assistant 2026.11 forwards it as a removed parameter and then
    refuses to add the entity.
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
    core = core_shelly_device(hass, entry)
    if core is not None and _device_info_has_field("via_device_id"):
        info["via_device_id"] = core.id
    return info


def update_companion_device(
    hass, entry, *, ip: str | None = None, bulk_entry_id: str | None = None
) -> None:
    """Refresh the companion name when the IP changes, unless the user renamed it.

    Any MAC connection left on this device by 0.2.6 is removed. The core Shelly
    device keeps that connection.
    """
    from .groups import companion_device_name

    registry = dr.async_get(hass)
    owner_ids = (
        [bulk_entry_id]
        if bulk_entry_id
        else [item.entry_id for item in hass.config_entries.async_entries(DOMAIN)]
    )
    device = device_by_identifier(registry, companion_identifier(entry), *owner_ids)
    if device is None:
        return
    name_by_user, device_name, model, mac, stored_ip = linked_shelly_names(hass, entry)
    current_ip = ip if ip is not None else stored_ip
    kwargs: dict = {}
    mac_connections = {
        connection
        for connection in device.connections
        if connection[0] == dr.CONNECTION_NETWORK_MAC
    }
    if mac_connections:
        kwargs["new_connections"] = set(device.connections) - mac_connections
    if not device.name_by_user:
        kwargs["name"] = companion_device_name(name_by_user, device_name, model, mac, current_ip)
    if current_ip:
        kwargs["configuration_url"] = f"http://{current_ip}"
    core = core_shelly_device(hass, entry)
    if core is not None and device.via_device_id != core.id:
        kwargs["via_device_id"] = core.id
    safe_device_update(registry, device.id, **kwargs)
