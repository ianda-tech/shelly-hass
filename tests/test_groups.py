"""Bulk groups, short labels, and MAC/IP on the device."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.groups import (
    companion_device_name,
    RELAY_FIELDS,
    DeviceCard,
    confirmation_text,
    device_label,
    model_options,
    room_options,
    select_cards,
    short_name,
    ticked_updates,
)
from custom_components.shelly_bulk.util import display_mac

from test_integration import _entry


def test_hostname_is_not_used_as_the_label() -> None:
    name, unnamed = short_name("", "shelly1pmminig3-48f6eeba6efc", "S3SW-001P8EU", "48:F6:EE:BA:6E:FC")
    assert unnamed is True
    assert "shelly1pm" not in name.lower()
    assert name.endswith("6EFC")
    label = device_label(name, "", "48:F6:EE:BA:6E:FC", "192.0.2.10")
    assert "48:F6:EE:BA:6E:FC" in label
    assert "192.0.2.10" in label
    assert "no room" in label


def test_a_user_name_is_kept() -> None:
    name, unnamed = short_name("Porch", "shelly1pmminig3-48f6eeba6efc", "S3SW-001P8EU", "48:F6:EE:BA:6E:FC")
    assert name == "Porch"
    assert unnamed is False


def test_groups_count_models_and_rooms_and_confirm_mac_and_ip() -> None:
    cards = [
        DeviceCard("a", "1PM Mini Gen3 · 6EFC · no room · 48:F6:EE:BA:6E:FC · 192.0.2.10", "", "", "S3SW-001P8EU", "1PM Mini Gen3", "48:F6:EE:BA:6E:FC", "192.0.2.10", True, False),
        DeviceCard("b", "Porch · Hall · AA:BB:CC:DD:EE:FF · 192.0.2.11", "Hall", "hall", "S3SW-001P8EU", "1PM Mini Gen3", "AA:BB:CC:DD:EE:FF", "192.0.2.11", False, False),
        DeviceCard("c", "Dimmer · 0001 · no room · 00:00:00:00:00:01 · 192.0.2.12", "", "", "SNDM-0013US", "Dimmer Gen3", "00:00:00:00:00:01", "192.0.2.12", True, True),
    ]
    models = {item["value"]: item["label"] for item in model_options(cards)}
    assert "2 devices" in models["S3SW-001P8EU"]
    rooms = {item["value"]: item["label"] for item in room_options(cards)}
    assert rooms["__none__"].startswith("No room")
    assert "2 devices" in rooms["__none__"]
    assert select_cards(cards, "unnamed")[0].entry_id == "a" or len(select_cards(cards, "unnamed")) == 2
    text = confirmation_text(select_cards(cards, "model", model="S3SW-001P8EU"))
    assert text.startswith("This will change 2 devices")
    assert "192.0.2.10" in text
    assert "48:F6:EE:BA:6E:FC" in text


def test_companion_name_uses_the_shelly_not_the_hub() -> None:
    named = companion_device_name("Porch", "shelly1pmminig3-48f6eeba6efc", "S3SW-001P8EU", "48F6EEB7C5D8", "192.168.1.20")
    assert named.startswith("Porch · ")
    assert "48:F6:EE:B7:C5:D8" in named
    assert named.endswith("192.168.1.20")
    assert "shelly1pm" not in named.lower()
    unnamed = companion_device_name("", "shelly1pmminig3-48f6eeba6efc", "S3SW-001P8EU", "48F6EEB7C5D8", "192.168.1.20")
    assert unnamed.startswith("1PM Mini Gen3 · C5D8 · ")
    assert unnamed.endswith("192.168.1.20")
    assert "Cheviot" not in unnamed


def test_only_ticked_fields_are_sent() -> None:
    updates = ticked_updates(
        {"change_input_mode": True, "input_mode": "detached", "change_auto_off": False, "auto_off": True},
        RELAY_FIELDS,
    )
    assert updates == {"input_mode": "detached"}


async def test_upgrade_reenables_only_integration_disabled_entities(hass) -> None:
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.entity_registry import RegistryEntryDisabler

    from custom_components.shelly_bulk import _reenable_integration_disabled

    entry = _entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    integration = registry.async_get_or_create(
        "switch",
        DOMAIN,
        "integration_off",
        config_entry=entry,
        disabled_by=RegistryEntryDisabler.INTEGRATION,
    )
    user = registry.async_get_or_create(
        "switch",
        DOMAIN,
        "user_off",
        config_entry=entry,
        disabled_by=RegistryEntryDisabler.USER,
    )
    _reenable_integration_disabled(hass, entry)
    assert registry.async_get(integration.entity_id).disabled_by is None
    assert registry.async_get(user.entity_id).disabled_by is RegistryEntryDisabler.USER


async def test_mac_sensor_and_visit_link(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries", _offline)
    entry = _entry()
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="shelly1pmminig3-48f6eeba6efc",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    entry.add_to_hass(hass)
    shelly.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=shelly.entry_id,
        identifiers={("shelly", "48F6EEBA6EFC")},
        name="shelly1pmminig3-48f6eeba6efc",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mac_states = [item for item in hass.states.async_all("sensor") if item.entity_id.endswith("mac_address")]
    assert mac_states
    assert "1pm_mini_gen3" in mac_states[0].entity_id
    assert "example_site" not in mac_states[0].entity_id
    assert mac_states[0].state == display_mac("48F6EEBA6EFC")
    companion = registry.async_get_device(identifiers={("shelly_bulk", f"companion_{shelly.entry_id}")})
    assert companion is not None
    assert companion.name == "1PM Mini Gen3 · 6EFC · 192.0.2.10"
    assert (dr.CONNECTION_NETWORK_MAC, "48:f6:ee:ba:6e:fc") in companion.connections
    assert companion.configuration_url == "http://192.0.2.10"
    registry.async_update_device(companion.id, name_by_user="My porch")
    runtime = hass.data[DOMAIN][entry.entry_id]
    from custom_components.shelly_bulk.entity import update_companion_device

    update_companion_device(hass, shelly, ip="192.0.2.40")
    renamed = registry.async_get(companion.id)
    assert renamed.name_by_user == "My porch"
    assert renamed.configuration_url == "http://192.0.2.40"
    ip_states = [item for item in hass.states.async_all("sensor") if item.entity_id.endswith("ip_address")]
    assert ip_states[0].state == "192.0.2.10"
    runtime = hass.data[DOMAIN][entry.entry_id]
    label = runtime.adopted_device_choices()[0]["label"]
    assert "shelly1pm" not in label.lower()
    assert "48:F6:EE:BA:6E:FC" in label
    assert "192.0.2.10" in label
