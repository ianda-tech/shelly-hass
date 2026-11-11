"""Device list file, discovery planning, and Identify."""

from __future__ import annotations

from pathlib import Path

from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant.common import MockConfigEntry

from custom_components.shelly_bulk.allowlist import merge_allowlist, parse_allowlist_csv
from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.device_list import (
    DEVICE_LIST_TEMPLATE,
    append_device_rows,
    ensure_device_list,
    placeholder_name,
)
from custom_components.shelly_bulk.discover import (
    HeardShelly,
    heard_from_advert,
    identify_enabled_by_default,
    identify_output,
    rows_for_discovery,
)
from custom_components.shelly_bulk.models import AllowDevice, Allowlist

from test_integration import _entry


def test_new_device_list_is_header_only_and_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "shelly_bulk" / "devices.csv"
    assert ensure_device_list(path) is True
    original = path.read_bytes()
    parsed, errors = parse_allowlist_csv(DEVICE_LIST_TEMPLATE)
    assert errors == []
    assert parsed.devices == {}
    path.write_text(path.read_text(encoding="utf-8") + "00:00:00:00:00:0A,Kept,Room\n", encoding="utf-8")
    assert ensure_device_list(path) is False
    assert "Kept" in path.read_text(encoding="utf-8")
    assert path.read_bytes() != original


def test_append_skips_duplicates_and_blank_merge_keeps_names(tmp_path: Path) -> None:
    path = tmp_path / "devices.csv"
    path.write_text("mac,name,room,model_hint\n00:00:00:00:00:0A,Kept,Hall,old\n", encoding="utf-8")
    added = append_device_rows(
        path,
        [
            {"mac": "00000000000A", "name": "Replacement", "room": "Other", "model_hint": "new"},
            {"mac": "00:00:00:00:00:0B", "name": "", "room": "", "model_hint": "Shelly Mini"},
        ],
    )
    assert added == ["00000000000B"]
    text = path.read_text(encoding="utf-8")
    assert "Replacement" not in text
    assert "Kept" in text
    parsed, errors = parse_allowlist_csv(text)
    assert errors == []
    base = Allowlist(devices={"00000000000A": AllowDevice(mac="00000000000A", name="Kept", room="Hall")})
    incoming, _errors = parse_allowlist_csv("mac,name,room\n00:00:00:00:00:0A,,,\n")
    merge_allowlist(base, incoming)
    assert base.devices["00000000000A"].name == "Kept"
    assert base.devices["00000000000A"].room == "Hall"
    merge_allowlist(base, Allowlist())
    assert base.devices["00000000000A"].name == "Kept"


def test_discovery_lists_or_names_and_skips_auth_and_known() -> None:
    payload = bytes([0x01, 0x05, 0x00, 0x0A, 6, 5, 4, 3, 2, 1, 0x0B, 1, 0])
    heard = heard_from_advert("shelly", {0x0BA9: payload}, rssi=-55, source="proxy-a")
    assert heard is not None
    assert heard.mac == "010203040506"
    assert heard.rpc is True
    assert heard.auth is False
    assert heard.rssi == -55
    assert heard.source == "proxy-a"
    locked = HeardShelly("00000000000C", "Shelly Mini", -70, "proxy-b", rpc=False, auth=False)
    authed = HeardShelly("00000000000D", "Shelly Mini", -40, "proxy-b", rpc=True, auth=True)
    rows, locked_macs = rows_for_discovery(
        [heard, locked, authed, heard],
        known={"010203040506"},
        already_added=set(),
        adopt=False,
    )
    assert rows == []
    assert locked_macs == ["00000000000C"]
    rows, locked_macs = rows_for_discovery([heard], known=set(), already_added=set(), adopt=True)
    assert rows[0]["name"] == placeholder_name(heard.model_hint, heard.mac)
    assert rows[0]["room"] == ""
    assert rows[0]["model_hint"]
    assert locked_macs == []


def test_identify_stays_off_for_relays_and_unknown_models() -> None:
    assert identify_enabled_by_default("Shelly Dimmer Gen3") is True
    assert identify_enabled_by_default("Shelly Plus 1PM") is False
    assert identify_enabled_by_default("") is False
    assert identify_enabled_by_default("Shelly 1 Mini Gen4") is False


async def test_identify_toggles_a_switch() -> None:
    class Session:
        def __init__(self):
            self.config = {"switch:0": {}}
            self.calls = []

        async def call(self, method, params=None):
            self.calls.append((method, params))

    session = Session()
    assert await identify_output(session) == "Switch.Set"
    assert session.calls == [("Switch.Set", {"id": 0, "toggle_after": 2})]


def test_placeholder_uses_model_and_mac_tail() -> None:
    assert placeholder_name("Shelly Plus 1PM", "aabbccddeeff") == "Shelly Plus 1PM EEFF"
    assert placeholder_name("", "aabbccddeeff") == "Shelly EEFF"


async def test_setup_creates_the_device_list_and_header_only_import_is_empty(hass) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    path = Path(hass.config.path("shelly_bulk/devices.csv"))
    if path.exists():
        path.unlink()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert path.is_file()
    original = path.read_bytes()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert path.read_bytes() == original
    parsed, errors = parse_allowlist_csv(path.read_text(encoding="utf-8"))
    assert errors == []
    assert parsed.devices == {}
    imported = await hass.services.async_call(
        DOMAIN,
        "import_allowlist",
        {"replace": True},
        blocking=True,
        return_response=True,
    )
    assert imported["count"] == 0
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert await runtime.add_listed_device("00:00:00:00:00:0A", "Example lamp", "Example room")
    assert not await runtime.add_listed_device("00:00:00:00:00:0A", "Other", "Other")
    text = path.read_text(encoding="utf-8")
    assert "Example lamp" in text
    assert "Other" not in text
    from homeassistant.helpers import entity_registry as er

    auto_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_auto_adopt")
    assert auto_id is not None
    assert hass.states.get(auto_id).state == "on"
    assert "Paused" in hass.states.get(auto_id).attributes["status"]
    path.unlink()


async def test_identify_button_is_disabled_for_a_relay(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries", _offline)
    entry = _entry()
    relay = MockConfigEntry(
        domain="shelly",
        unique_id="00000000000A",
        title="Relay",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "Shelly Plus 1PM"},
    )
    light = MockConfigEntry(
        domain="shelly",
        unique_id="00000000000B",
        title="Dimmer",
        data={CONF_HOST: "192.0.2.11", CONF_PORT: 80, "model": "Shelly Dimmer Gen3"},
    )
    relay.add_to_hass(hass)
    light.add_to_hass(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    relay_id = registry.async_get_entity_id("button", DOMAIN, f"{relay.entry_id}_identify")
    light_id = registry.async_get_entity_id("button", DOMAIN, f"{light.entry_id}_identify")
    assert registry.async_get(relay_id).disabled_by is None
    assert registry.async_get(light_id).disabled_by is None
    input_mode = registry.async_get_entity_id("select", DOMAIN, f"{relay.entry_id}_input_mode")
    scanner = registry.async_get_entity_id("select", DOMAIN, f"{relay.entry_id}_scanner_mode")
    delay = registry.async_get_entity_id("number", DOMAIN, f"{relay.entry_id}_auto_off_delay")
    relay_fade = registry.async_get_entity_id("number", DOMAIN, f"{relay.entry_id}_fade_rate")
    dimmer_fade = registry.async_get_entity_id("number", DOMAIN, f"{light.entry_id}_fade_rate")
    assert registry.async_get(input_mode).disabled_by is None
    assert registry.async_get(scanner).disabled_by is None
    assert registry.async_get(delay).disabled_by is None
    assert relay_fade is None
    assert registry.async_get(dimmer_fade).disabled_by is None
