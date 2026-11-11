"""Old Shelly Bulk devices collapse onto one companion per Shelly."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant.common import MockConfigEntry

from custom_components.shelly_bulk import async_migrate_entry, async_remove_config_entry_device
from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.entity import device_by_identifier, shelly_device_info

from test_integration import _entry


async def test_stale_devices_move_onto_one_companion_and_core_shelly_stays(hass) -> None:
    bulk = _entry()
    bulk.add_to_hass(hass)
    hass.config_entries.async_update_entry(bulk, minor_version=2)
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="shelly1pmminig3-48f6eeba6efc",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    shelly.add_to_hass(hass)
    devices = dr.async_get(hass)
    # Core Shelly uses its own identifier. The pre-0.2.6 fallback was
    # ("shelly", <unique id or entry id>) on a device this integration created.
    core = devices.async_get_or_create(
        config_entry_id=shelly.entry_id,
        identifiers={("shelly", "core-48F6EEBA6EFC")},
        connections={(dr.CONNECTION_NETWORK_MAC, "48:f6:ee:ba:6e:fc")},
        name="Porch",
    )
    old = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={("shelly", shelly.entry_id)},
        name=bulk.title,
    )
    empty = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={("shelly", "48F6EEBA6EFC")},
        name=bulk.title,
    )
    entities = er.async_get(hass)
    moved = entities.async_get_or_create(
        "switch",
        DOMAIN,
        f"{shelly.entry_id}_cloud",
        config_entry=bulk,
        device_id=old.id,
        disabled_by=RegistryEntryDisabler.USER,
    )
    entities.async_update_entity(moved.entity_id, name="My cloud")
    core_entity = entities.async_get_or_create(
        "switch",
        "shelly",
        "core-output",
        config_entry=shelly,
        device_id=core.id,
    )
    entity_id = moved.entity_id

    assert await async_migrate_entry(hass, bulk)

    assert bulk.minor_version == 4
    assert devices.async_get(old.id) is None
    assert devices.async_get(empty.id) is None
    kept_core = devices.async_get(core.id)
    assert kept_core is not None
    assert kept_core.name == "Porch"
    assert kept_core.config_entry_id == shelly.entry_id
    assert (dr.CONNECTION_NETWORK_MAC, "48:f6:ee:ba:6e:fc") in kept_core.connections
    companion = device_by_identifier(
        devices,
        (DOMAIN, f"companion_{shelly.entry_id}"),
        bulk.entry_id,
    )
    assert companion is not None
    kept = entities.async_get(entity_id)
    assert kept is not None
    assert kept.entity_id == entity_id
    assert kept.name == "My cloud"
    assert kept.disabled_by is RegistryEntryDisabler.USER
    assert kept.device_id == companion.id
    assert entities.async_get(core_entity.entity_id).device_id == core.id
    companions = [
        device
        for device in dr.async_entries_for_config_entry(devices, bulk.entry_id)
        if any(ident.startswith("companion_") for _domain, ident in device.identifiers)
    ]
    assert len(companions) == 1
    assert await async_remove_config_entry_device(hass, bulk, companion) is False
    assert await async_remove_config_entry_device(hass, bulk, kept_core) is True


async def test_companion_identifier_does_not_change_with_ip(hass) -> None:
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="shelly1pmminig3-48f6eeba6efc",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    shelly.add_to_hass(hass)
    first = shelly_device_info(hass, shelly)
    hass.config_entries.async_update_entry(shelly, data={**shelly.data, CONF_HOST: "192.0.2.99", "model": "S3SW-001P8EU"})
    second = shelly_device_info(hass, shelly)
    assert first["identifiers"] == second["identifiers"] == {(DOMAIN, f"companion_{shelly.entry_id}")}
    assert "connections" not in first
    assert "connections" not in second


async def test_orphan_companion_moves_when_the_mac_sensor_matches(hass) -> None:
    bulk = _entry()
    bulk.add_to_hass(hass)
    hass.config_entries.async_update_entry(bulk, minor_version=3)
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="Porch",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    shelly.add_to_hass(hass)
    devices = dr.async_get(hass)
    orphan = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={(DOMAIN, "companion_01M74D6D0ERMHSMQHENRHR1ZF8")},
        name="Cheviot",
    )
    entities = er.async_get(hass)
    mac_entity = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "01M74D6D0ERMHSMQHENRHR1ZF8_mac_address",
        config_entry=bulk,
        device_id=orphan.id,
    )
    hass.states.async_set(mac_entity.entity_id, "48:F6:EE:BA:6E:FC")
    select_entity = entities.async_get_or_create(
        "select",
        DOMAIN,
        "01M74D6D0ERMHSMQHENRHR1ZF8_power_on_state",
        config_entry=bulk,
        device_id=orphan.id,
    )
    assert await async_migrate_entry(hass, bulk)
    assert devices.async_get(orphan.id) is None
    companion = device_by_identifier(devices, (DOMAIN, f"companion_{shelly.entry_id}"), bulk.entry_id)
    assert companion is not None
    assert entities.async_get(mac_entity.entity_id).device_id == companion.id
    assert entities.async_get(select_entity.entity_id).device_id == companion.id


async def test_orphan_companion_without_a_mac_is_removed(hass) -> None:
    bulk = _entry()
    bulk.add_to_hass(hass)
    hass.config_entries.async_update_entry(bulk, minor_version=3)
    devices = dr.async_get(hass)
    orphan = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={(DOMAIN, "companion_01M74D6D0ERMHSMQHENRHR1ZF8")},
        name="Cheviot",
    )
    entities = er.async_get(hass)
    mac_entity = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "01M74D6D0ERMHSMQHENRHR1ZF8_mac_address",
        config_entry=bulk,
        device_id=orphan.id,
    )
    hass.states.async_set(mac_entity.entity_id, "unavailable")
    assert await async_migrate_entry(hass, bulk)
    assert devices.async_get(orphan.id) is None
    assert entities.async_get(mac_entity.entity_id) is None
    assert await async_remove_config_entry_device(hass, bulk, orphan) is True
