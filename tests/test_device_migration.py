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


async def test_duplicate_companion_for_the_same_mac_is_removed_on_setup(hass, monkeypatch, caplog) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    bulk = _entry()
    bulk.add_to_hass(hass)
    hass.config_entries.async_update_entry(bulk, minor_version=4)
    live_id = "01M76K99B9R9WY84CK9NP95F84"
    old_id = "01M74D6D0ERMHSMQHENRHR1ZF8"
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEB7F8B8",
        title="shellymini1pmg3-48f6eeb7f8b8",
        data={CONF_HOST: "192.0.2.20", CONF_PORT: 80, "model": "S3SW-001P8EU"},
        entry_id=live_id,
    )
    shelly.add_to_hass(hass)
    devices = dr.async_get(hass)
    core = devices.async_get_or_create(
        config_entry_id=shelly.entry_id,
        identifiers={("shelly", "48F6EEB7F8B8")},
        connections={(dr.CONNECTION_NETWORK_MAC, "48:f6:ee:b7:f8:b8")},
        name="shellymini1pmg3-48f6eeb7f8b8",
    )
    linked = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={(DOMAIN, f"companion_{live_id}")},
        via_device_id=core.id,
        name="1PM Mini Gen3 · F8B8 · 192.0.2.20",
    )
    orphan = devices.async_get_or_create(
        config_entry_id=bulk.entry_id,
        identifiers={(DOMAIN, f"companion_{old_id}")},
        connections={(dr.CONNECTION_NETWORK_MAC, "48:f6:ee:b7:f8:b8")},
        name="Cheviot",
    )
    registry = er.async_get(hass)
    linked_entity = registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{live_id}_power_on_state",
        config_entry=bulk,
        device_id=linked.id,
    )
    linked_entity_id = linked_entity.entity_id
    orphan_entity = registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{old_id}_power_on_state",
        config_entry=bulk,
        device_id=orphan.id,
    )
    registry.async_update_entity(orphan_entity.entity_id, name="Porch light")
    import logging

    caplog.set_level(logging.INFO)
    assert await hass.config_entries.async_setup(bulk.entry_id)
    await hass.async_block_till_done()
    assert devices.async_get(orphan.id) is None
    assert registry.async_get(orphan_entity.entity_id) is None
    kept = registry.async_get(linked_entity_id)
    assert kept is not None
    assert kept.entity_id == linked_entity_id
    assert kept.device_id == linked.id
    assert kept.name == "Porch light"
    assert devices.async_get(linked.id) is not None
    assert "Removing duplicate Shelly Installer device" in caplog.text
    assert await hass.config_entries.async_unload(bulk.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(bulk.entry_id)
    await hass.async_block_till_done()
    assert devices.async_get(linked.id) is not None
    assert registry.async_get(linked_entity_id).entity_id == linked_entity_id
    assert registry.async_get(linked_entity_id).name == "Porch light"
