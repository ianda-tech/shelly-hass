"""Consumption type is written only when it changes. Profile changes are confirmed."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.device_type import (
    apply_default_output,
    consumption_list_with,
    site_default_output,
    write_consumption,
    write_profile,
)

from test_integration import _entry


def test_missing_site_default_is_light() -> None:
    assert site_default_output({}) == "light"
    assert site_default_output({"default_output_type": "fan"}) == "fan"
    assert site_default_output({"default_output_type": "nope"}) == "light"


def test_consumption_list_keeps_other_channels() -> None:
    assert consumption_list_with(["light", ""], 0, "light") is None
    assert consumption_list_with(["light", ""], 0, "switch") == ["switch", "switch"]
    assert consumption_list_with(["light"], 1, "fan") == ["light", "fan"]
    assert consumption_list_with([], 0, "switch") is None


class _Session:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.config = {"switch:0": {"id": 0}, "switch:1": {"id": 1}}
        self.types = ["switch", "light"]
        self.profile = "switch"

    async def call(self, method, params=None):
        self.calls.append(method)
        if method == "Shelly.Reboot":
            raise AssertionError("reboot")
        if method == "Sys.GetConfig":
            return {"ui_data": {"other": True, "consumption_types": list(self.types)}}
        if method == "Sys.SetConfig":
            ui = params["config"]["ui_data"]
            assert ui["other"] is True
            self.types = list(ui["consumption_types"])
            return {}
        if method == "Shelly.GetDeviceInfo":
            return {"profile": self.profile}
        if method == "Shelly.ListProfiles":
            return {"profiles": {"cover": {}, "switch": {}, "rgbw": {}}}
        if method == "Shelly.SetProfile":
            self.profile = params["name"]
            return {"profile_was": "switch"}
        return {}

    async def shutdown(self) -> None:
        return None


async def test_matching_consumption_and_profile_are_not_sent() -> None:
    session = _Session()
    assert await write_consumption(session, 1, "light") == ("light", False)
    assert "Sys.SetConfig" not in session.calls
    assert await write_profile(session, "switch") is False
    assert "Shelly.SetProfile" not in session.calls
    assert "Shelly.Reboot" not in session.calls


async def test_changed_consumption_and_profile_do_not_call_reboot() -> None:
    session = _Session()
    assert await write_consumption(session, 0, "fan") == ("fan", True)
    assert session.types == ["fan", "light"]
    assert session.calls.count("Sys.SetConfig") == 1
    assert await write_profile(session, "cover") is True
    assert session.calls.count("Shelly.SetProfile") == 1
    assert await write_profile(session, "cover") is False
    assert session.calls.count("Shelly.SetProfile") == 1
    assert "Shelly.Reboot" not in session.calls


async def test_device_type_step_requires_the_reboot_box(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    entry = _entry()
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="Porch",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "SNSW-002P16EU"},
    )
    entry.add_to_hass(hass)
    shelly.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    consumption = registry.async_get_entity_id("select", DOMAIN, f"{shelly.entry_id}_consumption_type_0")
    assert consumption is not None

    runtime = hass.data[DOMAIN][entry.entry_id]

    async def _describe(_entry_ids):
        return {"profiles": ["cover", "switch"]}

    recorded: dict = {}

    def _start(entry_ids, *, consumption, profile, confirm_reboot, apply_site_default=False):
        recorded["call"] = (list(entry_ids), consumption, profile, confirm_reboot, apply_site_default)
        return len(entry_ids)

    runtime.describe_device_types = _describe
    runtime.start_device_type = _start
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "device_type"}
    )
    assert result["step_id"] == "device_type"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"group": "all"})
    assert result["step_id"] == "device_type_form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"consumption_type": "light", "profile": "cover", "confirm_profile_reboot": False},
    )
    assert result["errors"]["confirm_profile_reboot"] == "confirm_profile"
    assert "call" not in recorded
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"consumption_type": "light", "profile": "cover", "confirm_profile_reboot": True},
    )
    assert result["type"] == "abort"
    assert result["reason"] == "device_type_started"
    assert recorded["call"][1:] == ("light", "cover", True, False)


async def test_profile_changes_wait_between_devices(hass, monkeypatch) -> None:
    entry = _entry()
    first = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="One",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "SNSW-002P16EU"},
    )
    second = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFD",
        title="Two",
        data={CONF_HOST: "192.0.2.11", CONF_PORT: 80, "model": "SNSW-002P16EU"},
    )
    entry.add_to_hass(hass)
    first.add_to_hass(hass)
    second.add_to_hass(hass)

    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    pauses: list[float] = []
    reloads: list[str] = []

    async def _pause(seconds: float) -> None:
        pauses.append(seconds)

    def _reload_later(shelly_entry, delay: float = 15) -> None:
        reloads.append((shelly_entry.entry_id, delay))

    runtime._pause = _pause
    runtime._reload_shelly_later = _reload_later
    sessions = {first.entry_id: _Session(), second.entry_id: _Session()}

    async def _open(shelly_entry, attempts=None):
        return sessions[shelly_entry.entry_id]

    runtime._open_shelly = _open
    await runtime._apply_device_types([first.entry_id, second.entry_id], "fan", "cover")
    assert pauses == [8]
    assert sessions[first.entry_id].profile == "cover"
    assert sessions[second.entry_id].types[0] == "fan"
    assert all("Shelly.Reboot" not in session.calls for session in sessions.values())
    assert reloads == [
        (first.entry_id, 2),
        (first.entry_id, 15),
        (second.entry_id, 2),
        (second.entry_id, 15),
    ]


async def test_site_default_skips_overrides_and_does_not_reboot() -> None:
    session = _Session()
    assert await apply_default_output(session, "light", {1}) is True
    assert session.types == ["light", "light"]
    assert session.calls.count("Sys.SetConfig") == 1
    assert "Shelly.Reboot" not in session.calls
    session.calls.clear()
    assert await apply_default_output(session, "light", {0}) is False
    assert "Sys.SetConfig" not in session.calls
