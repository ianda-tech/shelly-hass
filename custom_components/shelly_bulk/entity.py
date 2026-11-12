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
            name=f"Shelly Installer ({runtime.site_name})",
            manufacturer=MANUFACTURER,
            model="Shelly Installer",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()


def companion_identifier(entry) -> tuple[str, str]:
    """Stable id for the Shelly Bulk device that belongs to one core Shelly.

    This id is the Shelly config entry id. It does not include the IP or the
    device name, so a new address does not create a second device.
    """
    return (DOMAIN, f"companion_{entry.entry_id}")


def _current_device(device, bulk_entry, shelly_ids: set[str]) -> bool:
    """True for the Shelly Bulk hub or a companion of a Shelly that still exists."""
    for domain, ident in device.identifiers:
        if domain != DOMAIN:
            continue
        if ident == bulk_entry.entry_id:
            return True
        owner = ident.removeprefix("companion_")
        if ident.startswith("companion_") and owner in shelly_ids:
            return True
    return False


def _shelly_id_for_entity(unique_id: str, shelly_ids: set[str], bulk_entry_id: str) -> str | None:
    """Return the Shelly entry id a Shelly Bulk entity belongs to, or None for the hub."""
    matches = [shelly_id for shelly_id in shelly_ids if unique_id.startswith(f"{shelly_id}_")]
    if matches:
        return max(matches, key=len)
    if unique_id.startswith(f"{bulk_entry_id}_"):
        return None
    return ""


def _ensure_companion(hass, bulk_entry, shelly_entry) -> str:
    """Return the current companion device id, creating it if this is the first time."""
    from .groups import companion_device_name, friendly_model

    registry = dr.async_get(hass)
    existing = device_by_identifier(
        registry, companion_identifier(shelly_entry), bulk_entry.entry_id
    )
    if existing is not None:
        return existing.id
    name_by_user, device_name, model, mac, ip = linked_shelly_names(hass, shelly_entry)
    kwargs = {}
    if ip:
        kwargs["configuration_url"] = f"http://{ip}"
    created = registry.async_get_or_create(
        config_entry_id=bulk_entry.entry_id,
        identifiers={companion_identifier(shelly_entry)},
        name=companion_device_name(name_by_user, device_name, model, mac, ip),
        manufacturer="Shelly",
        model=friendly_model(model) or model or "Shelly",
        **kwargs,
    )
    return created.id


def _ensure_hub(hass, bulk_entry) -> str:
    registry = dr.async_get(hass)
    existing = device_by_identifier(registry, (DOMAIN, bulk_entry.entry_id), bulk_entry.entry_id)
    if existing is not None:
        return existing.id
    created = registry.async_get_or_create(
        config_entry_id=bulk_entry.entry_id,
        identifiers={(DOMAIN, bulk_entry.entry_id)},
        name=f"Shelly Installer ({bulk_entry.title})",
        manufacturer=MANUFACTURER,
        model="Shelly Installer",
    )
    return created.id


def _companion_ident(device) -> str:
    for domain, ident in device.identifiers:
        if domain == DOMAIN and str(ident).startswith("companion_"):
            return str(ident)
    return ""


def _device_macs(device) -> set[str]:
    from .util import normalize_mac

    found: set[str] = set()
    for domain, value in device.connections:
        if domain != dr.CONNECTION_NETWORK_MAC:
            continue
        try:
            found.add(normalize_mac(value))
        except ValueError:
            continue
    return found


def _mac_index(registry, shelly_entries: dict) -> dict[str, object]:
    """Map a MAC to the core Shelly config entry that owns it."""
    from .util import normalize_mac

    index: dict[str, object] = {}
    for entry in shelly_entries.values():
        if entry.unique_id:
            try:
                index.setdefault(normalize_mac(str(entry.unique_id)), entry)
            except ValueError:
                pass
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            for mac in _device_macs(device):
                index.setdefault(mac, entry)
    return index


def _macs_for_companion(hass, registry, device, ours) -> set[str]:
    macs = _device_macs(device)
    sensor_mac = _mac_from_entities(hass, ours)
    if sensor_mac:
        macs.add(sensor_mac)
    if device.via_device_id:
        parent = registry.async_get(device.via_device_id)
        if parent is not None:
            macs.update(_device_macs(parent))
    return macs


def _entity_suffix(unique_id: str, owner_id: str) -> str:
    prefix = f"{owner_id}_"
    if unique_id.startswith(prefix):
        return unique_id[len(prefix) :]
    return ""


def _copy_orphan_customisation(entities, orphan_entity, linked_entity) -> None:
    """Copy a name, icon, or user disable onto the linked entity.

    The linked entity keeps its entity id. A customisation it already has wins.
    """
    from homeassistant.helpers.entity_registry import RegistryEntryDisabler

    updates: dict = {}
    if orphan_entity.name and not linked_entity.name:
        updates["name"] = orphan_entity.name
    if orphan_entity.icon and not linked_entity.icon:
        updates["icon"] = orphan_entity.icon
    if (
        orphan_entity.disabled_by == RegistryEntryDisabler.USER
        and linked_entity.disabled_by != RegistryEntryDisabler.USER
    ):
        updates["disabled_by"] = RegistryEntryDisabler.USER
    if not updates:
        return
    entities.async_update_entity(linked_entity.entity_id, **updates)
    _LOGGER.info(
        "Kept customisation from %s on %s without changing its entity id",
        orphan_entity.entity_id,
        linked_entity.entity_id,
    )


def _drop_duplicate_companion(registry, entities, device, sibling, ours, orphan_owner: str, live_owner: str, mac: str) -> None:
    linked_by_suffix = {}
    for entity in er_entries_for_device(entities, sibling.id):
        suffix = _entity_suffix(entity.unique_id or "", live_owner)
        if suffix:
            linked_by_suffix[suffix] = entity
    shown = sorted(device.identifiers)
    for entity in ours:
        suffix = _entity_suffix(entity.unique_id or "", orphan_owner)
        linked = linked_by_suffix.get(suffix) if suffix else None
        if linked is not None:
            _copy_orphan_customisation(entities, entity, linked)
        _LOGGER.info(
            "Removing duplicate entity %s from orphan device %s",
            entity.entity_id,
            shown,
        )
        entities.async_remove(entity.entity_id)
    _LOGGER.info(
        "Removing duplicate Shelly Installer device %s for %s; %s is the linked companion",
        shown,
        mac,
        sorted(sibling.identifiers),
    )
    registry.async_remove_device(device.id)


def er_entries_for_device(entities, device_id: str):
    from homeassistant.helpers import entity_registry as er

    return [
        entity
        for entity in er.async_entries_for_device(entities, device_id, include_disabled_entities=True)
    ]


def _mac_from_entities(hass, entities_on_device) -> str | None:
    """Read a MAC from the restored state of this device's MAC sensor."""
    from .util import normalize_mac

    for entity in entities_on_device:
        unique_id = entity.unique_id or ""
        if not unique_id.endswith("_mac_address"):
            continue
        state = hass.states.get(entity.entity_id)
        if state is None or state.state in {"", "unknown", "unavailable"}:
            continue
        try:
            return normalize_mac(state.state)
        except ValueError:
            continue
    return None


def _shelly_for_mac(shelly_entries: dict, mac: str | None):
    if not mac:
        return None
    from .util import normalize_mac

    for entry in shelly_entries.values():
        if not entry.unique_id:
            continue
        try:
            if normalize_mac(str(entry.unique_id)) == mac:
                return entry
        except ValueError:
            continue
    return None


def _move_entity(entities, entity, owner, hass, bulk_entry, shelly_entries) -> bool:
    try:
        if owner is None:
            target = _ensure_hub(hass, bulk_entry)
        else:
            target = _ensure_companion(hass, bulk_entry, shelly_entries[owner])
        if entity.device_id != target:
            entities.async_update_entity(entity.entity_id, device_id=target)
    except Exception:
        _LOGGER.exception("Could not move %s off stale device", entity.entity_id)
        return False
    return True


def retire_stale_devices(hass, bulk_entry) -> None:
    """Move entities onto the current companion device and drop leftover devices.

    Before 0.2.6 a per-Shelly device was created with identifier
    ``("shelly", <Shelly unique id or entry id>)`` and no name, so Home
    Assistant titled it with this config entry. 0.2.6 added a second device,
    ``("shelly_bulk", "companion_<Shelly entry id>")``. This keeps that second
    device and removes the earlier one. A core Shelly device is left in place;
    only this integration's link to it is removed.
    """
    from homeassistant.helpers import entity_registry as er

    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    shelly_entries = {
        entry.entry_id: entry for entry in hass.config_entries.async_entries(SHELLY_DOMAIN)
    }
    shelly_ids = set(shelly_entries)
    mac_index = _mac_index(registry, shelly_entries)
    by_key = {}
    for entry in shelly_entries.values():
        by_key[entry.entry_id] = entry.entry_id
        if entry.unique_id:
            by_key[str(entry.unique_id)] = entry.entry_id
    for device in list(dr.async_entries_for_config_entry(registry, bulk_entry.entry_id)):
        if _current_device(device, bulk_entry, shelly_ids):
            macs = {item for item in device.connections if item[0] == dr.CONNECTION_NETWORK_MAC}
            if macs and any(ident.startswith("companion_") for _domain, ident in device.identifiers):
                safe_device_update(
                    registry,
                    device.id,
                    new_connections=set(device.connections) - macs,
                )
            continue
        ident = _companion_ident(device)
        orphan_owner = ident.removeprefix("companion_") if ident else ""
        ours = [
            entity
            for entity in er_entries_for_device(entities, device.id)
            if entity.config_entry_id == bulk_entry.entry_id
        ]
        macs = _macs_for_companion(hass, registry, device, ours)
        live = next((mac_index.get(mac) for mac in macs if mac in mac_index), None)
        if live is not None and ident and ident != f"companion_{live.entry_id}":
            sibling = device_by_identifier(
                registry, (DOMAIN, f"companion_{live.entry_id}"), bulk_entry.entry_id
            )
            if sibling is not None and sibling.id != device.id:
                _drop_duplicate_companion(
                    registry,
                    entities,
                    device,
                    sibling,
                    ours,
                    orphan_owner,
                    live.entry_id,
                    next(iter(macs), ""),
                )
                continue
        device_owner = ""
        for domain, value in device.identifiers:
            if domain == SHELLY_DOMAIN and value in by_key:
                device_owner = by_key[value]
                break
        blocked = False
        unmatched = []
        for entity in ours:
            owner = _shelly_id_for_entity(entity.unique_id or "", shelly_ids, bulk_entry.entry_id)
            if owner == "":
                owner = device_owner or ""
            if owner == "":
                unmatched.append(entity)
                continue
            if not _move_entity(entities, entity, owner, hass, bulk_entry, shelly_entries):
                blocked = True
        if unmatched and not blocked:
            linked = _shelly_for_mac(shelly_entries, _mac_from_entities(hass, unmatched))
            if linked is not None:
                target_owner = linked.entry_id
                for entity in unmatched:
                    if not _move_entity(entities, entity, target_owner, hass, bulk_entry, shelly_entries):
                        blocked = True
            else:
                shown = sorted(device.identifiers)
                for entity in unmatched:
                    _LOGGER.info(
                        "Removing %s from orphan device %s; no core Shelly entry matches it",
                        entity.entity_id,
                        shown,
                    )
                    entities.async_remove(entity.entity_id)
                _LOGGER.info(
                    "Removing orphan Shelly Installer device %s. Its Shelly entry is gone and it has no MAC to re-link.",
                    shown,
                )
        if blocked:
            continue
        # A device belongs to one config entry. This list is the devices this
        # integration owns. A core Shelly device is not in the list, so it is
        # not removed. remove_config_entry_id is gone on Home Assistant 2026.11.
        if bulk_entry.entry_id not in device_config_entry_ids(device):
            continue
        try:
            _LOGGER.info(
                "Removing stale Shelly Installer device %s with identifiers %s",
                device.name,
                sorted(device.identifiers),
            )
            registry.async_remove_device(device.id)
        except Exception:
            _LOGGER.exception("Could not remove stale device %s", device.id)


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
